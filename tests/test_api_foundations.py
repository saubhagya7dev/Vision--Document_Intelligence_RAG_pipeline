from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from vision_rag.api import routes
from vision_rag.api.main import app
from vision_rag.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "qdrant_in_memory", True)
    monkeypatch.setattr(settings, "model_warmup", False)
    for name in ("_loader", "_vdb", "_pipeline", "_synthesizer"):
        monkeypatch.setattr(routes, name, None)
    monkeypatch.setattr(routes, "_model_state", "not_loaded")
    with TestClient(app) as client:
        yield client


def make_pdf(path, pages=3):
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=100, height=200)
            page.close()
        pdf.save(str(path))
    return path.read_bytes()


def test_library_and_preview_do_not_initialize_models(client, tmp_path, monkeypatch):
    make_pdf(tmp_path / "report.pdf")
    monkeypatch.setattr(routes, "get_components", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(pdfium.PdfPage, "render", MagicMock(side_effect=AssertionError))
    response = client.get("/api/v1/documents")
    assert response.json()[0]["page_count"] == 3
    assert response.headers["X-Trace-ID"]
    assert client.get("/api/v1/ready").status_code == 503
    assert client.get("/api/v1/missing").status_code == 404


def test_preview_returns_only_requested_page_and_thumbnail(client, tmp_path):
    make_pdf(tmp_path / "report.pdf")
    assert (
        client.get("/api/v1/documents/report.pdf/pages/2").headers["content-type"]
        == "image/jpeg"
    )
    assert (
        client.get("/api/v1/documents/report.pdf/pages/2?thumbnail=true").status_code
        == 200
    )
    assert client.get("/api/v1/documents/report.pdf/pages/0").status_code == 404
    assert client.get("/api/v1/documents/report.pdf/pages/4").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x", "top_k": 0},
        {"query": "x", "top_k": 21},
    ],
)
def test_invalid_query_never_loads_models(client, monkeypatch, payload):
    initialize = MagicMock(side_effect=AssertionError)
    monkeypatch.setattr(routes, "get_components", initialize)
    assert client.post("/api/v1/query", json=payload).status_code == 422
    initialize.assert_not_called()


def test_upload_limits_header_and_traversal(client, monkeypatch):
    initialize = MagicMock(side_effect=AssertionError)
    monkeypatch.setattr(routes, "get_components", initialize)
    for name, content in [
        ("../escape.pdf", b"%PDF-test"),
        ("C:escape.pdf", b"%PDF-test"),
        ("x.pdf", b"not a PDF"),
    ]:
        assert (
            client.post(
                "/api/v1/ingest", files={"file": (name, content, "application/pdf")}
            ).status_code
            == 400
        )
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    assert (
        client.post(
            "/api/v1/ingest", files={"file": ("large.pdf", b"x" * (1024 * 1024 + 1))}
        ).status_code
        == 413
    )
    initialize.assert_not_called()


def test_upload_success_and_duplicate_preserve_original(client, tmp_path, monkeypatch):
    data = make_pdf(tmp_path / "fixture.pdf")
    pipeline = MagicMock()
    monkeypatch.setattr(routes, "get_components", lambda: (pipeline, None))
    response = client.post("/api/v1/ingest", files={"file": ("report.PDF", data)})
    assert response.status_code == 200
    assert (tmp_path / "report.PDF").read_bytes() == data
    assert (
        client.post("/api/v1/ingest", files={"file": ("report.PDF", data)}).status_code
        == 409
    )
    pipeline.ingest_document.assert_called_once()


def test_upload_failure_cleans_source_and_partial_vectors(
    client, tmp_path, monkeypatch
):
    data = make_pdf(tmp_path / "fixture.pdf")
    pipeline = MagicMock()
    pipeline.ingest_document.side_effect = RuntimeError("private details")
    monkeypatch.setattr(routes, "get_components", lambda: (pipeline, None))
    store = routes.get_store()
    store.upsert(
        ["00000000-0000-0000-0000-000000000001"],
        [[1.0] * 128],
        [{"source": str((tmp_path / "report.pdf").resolve())}],
    )
    response = client.post("/api/v1/ingest", files={"file": ("report.pdf", data)})
    assert response.status_code == 500
    assert "private details" not in response.text
    assert not (tmp_path / "report.pdf").exists()
    assert store.get_collection_info()["points_count"] == 0
    assert not list(tmp_path.glob("*.upload"))


def test_health_remains_responsive_during_blocking_query(client, monkeypatch):
    started, finish = Event(), Event()
    synthesizer = MagicMock()

    def query(**kwargs):
        started.set()
        assert finish.wait(5)
        return "answer", []

    synthesizer.query.side_effect = query
    monkeypatch.setattr(routes, "get_components", lambda: (None, synthesizer))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/v1/query", json={"query": "test"})
        try:
            assert started.wait(5)
            assert client.get("/health").status_code == 200
        finally:
            finish.set()
        assert future.result(timeout=5).status_code == 200


def test_stats_and_deletion_work_without_model_initialization(client, tmp_path):
    path = tmp_path / "report.pdf"
    make_pdf(path)
    store = routes.get_store()
    store.upsert(
        ["00000000-0000-0000-0000-000000000001"],
        [[1.0] * 128],
        [{"source": str(path.resolve())}],
    )
    assert client.get("/api/v1/stats").json()["total_vectors"] == 1
    assert client.delete("/api/v1/documents/report.pdf").status_code == 200
    assert client.get("/api/v1/stats").json()["total_vectors"] == 0
    assert not path.exists()


def test_component_initialization_is_shared_and_resources_close(client, monkeypatch):
    from vision_rag.models import colpali_embedder, gemini_generator

    embedder, generator = MagicMock(), MagicMock()
    load_model = MagicMock(return_value=embedder)
    monkeypatch.setattr(colpali_embedder, "ColPaliEmbeddingModel", load_model)
    monkeypatch.setattr(
        gemini_generator, "GeminiGenerator", MagicMock(return_value=generator)
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        components = list(pool.map(lambda _: routes.get_components(), range(4)))
    assert all(pair[0] is components[0][0] for pair in components)
    load_model.assert_called_once()
    assert client.get("/api/v1/ready").status_code == 200
    routes.shutdown_components()
    embedder.close.assert_called_once()
    generator.close.assert_called_once()


def test_failed_initialization_is_visible_and_can_be_retried(client, monkeypatch):
    from vision_rag.models import colpali_embedder, gemini_generator

    embedder, generator = MagicMock(), MagicMock()
    load_model = MagicMock(side_effect=[RuntimeError("model failed"), embedder])
    monkeypatch.setattr(colpali_embedder, "ColPaliEmbeddingModel", load_model)
    monkeypatch.setattr(
        gemini_generator, "GeminiGenerator", MagicMock(return_value=generator)
    )
    with pytest.raises(RuntimeError, match="model failed"):
        routes.get_components()
    assert routes._model_state == "failed"
    assert client.get("/api/v1/ready").status_code == 503
    generator.close.assert_called_once()
    routes.get_components()
    assert routes._model_state == "ready"


def test_lifespan_can_warm_up_before_serving(tmp_path, monkeypatch):
    from vision_rag.api import main

    monkeypatch.setattr(settings, "model_warmup", True)
    initialize, shutdown = MagicMock(), MagicMock()
    monkeypatch.setattr(main, "get_components", initialize)
    monkeypatch.setattr(main, "shutdown_components", shutdown)
    with TestClient(app) as warmed:
        initialize.assert_called_once()
        assert warmed.get("/health").status_code == 200
    shutdown.assert_called_once()
