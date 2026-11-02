from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from vision_rag.api import routes
from vision_rag.api.main import app
from vision_rag.config import settings
from vision_rag.ingest.pipeline import IngestionPipeline


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "library")
    monkeypatch.setattr(settings, "qdrant_mode", "memory")
    monkeypatch.setattr(settings, "ingestion_worker_enabled", False)
    monkeypatch.setattr(settings, "import_legacy_pdfs", False)
    monkeypatch.setattr(settings, "model_warmup", False)
    # Preserve Phase 2's all-page-vector contract in its regression fixtures.
    monkeypatch.setattr(settings, "hybrid_ingestion", False)
    monkeypatch.setattr(settings, "render_dpi", 72)
    for name in ("_loader", "_vdb", "_pipeline", "_synthesizer", "_library"):
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


def upload(client, tmp_path, pages=3, filename="report.pdf"):
    data = make_pdf(tmp_path / "fixture.pdf", pages)
    response = client.post("/api/v1/ingest", files={"file": (filename, data)})
    assert response.status_code == 202
    return response.json(), data


def complete(monkeypatch):
    lib = routes.get_library()
    encoder = MagicMock()
    encoder.encode_images.side_effect = lambda images: [[1.0] * 128 for _ in images]
    pipeline = IngestionPipeline(lib.loader, encoder, lib.store, batch_size=1)
    monkeypatch.setattr(lib, "pipeline", lambda: pipeline)
    assert lib.process_one()
    return encoder


def test_upload_returns_durable_job_without_initializing_model(
    client, tmp_path, monkeypatch
):
    lib = routes.get_library()
    initialize = MagicMock(side_effect=AssertionError)
    monkeypatch.setattr(lib, "pipeline", initialize)
    job, data = upload(client, tmp_path, filename="report.PDF")
    assert job["state"] == "uploaded"
    assert job["total_pages"] == 3
    assert client.get("/api/v1/jobs/" + job["id"]).json()["id"] == job["id"]
    assert client.get("/api/v1/versions/" + job["version_id"] + "/file").content == data
    assert not (settings.data_dir / "report.PDF").exists()
    initialize.assert_not_called()
    duplicate = client.post(
        "/api/v1/ingest", files={"file": ("renamed.pdf", data)}
    ).json()
    assert duplicate["deduplicated"] and duplicate["id"] == job["id"]


def test_metadata_inventory_never_renders(client, tmp_path, monkeypatch):
    upload(client, tmp_path)
    monkeypatch.setattr(pdfium.PdfPage, "render", MagicMock(side_effect=AssertionError))
    response = client.get("/api/v1/documents")
    assert response.json()[0]["page_count"] == 3
    assert response.json()[0]["state"] == "uploaded"
    assert response.headers["X-Trace-ID"]
    assert client.get("/api/v1/ready").status_code == 503
    assert client.get("/api/v1/missing").status_code == 404


def test_version_page_preview_and_thumbnail(client, tmp_path):
    job, _ = upload(client, tmp_path)
    url = "/api/v1/versions/" + job["version_id"] + "/pages/"
    assert client.get(url + "2").headers["content-type"] == "image/jpeg"
    assert client.get(url + "2?thumbnail=true").status_code == 200
    assert client.get(url + "0").status_code == 404
    assert client.get(url + "4").status_code == 404
    assert client.get("/api/v1/documents/report.pdf/pages/2").status_code == 200


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
    routes.get_library().max_upload_bytes = 1024
    assert (
        client.post(
            "/api/v1/ingest", files={"file": ("large.pdf", b"x" * 1025)}
        ).status_code
        == 413
    )


def test_failure_retry_cancel_and_progress_contract(client, tmp_path, monkeypatch):
    job, _ = upload(client, tmp_path)
    lib = routes.get_library()
    monkeypatch.setattr(lib, "pipeline", MagicMock(side_effect=RuntimeError("private")))
    lib.process_one()
    failed = client.get("/api/v1/jobs/" + job["id"]).json()
    assert failed["state"] == "failed" and "private" not in str(failed)
    assert client.post("/api/v1/jobs/" + job["id"] + "/retry").status_code == 202
    assert client.post("/api/v1/jobs/" + job["id"] + "/cancel").status_code == 202
    lib.process_one()
    assert lib.metadata.job(job["id"])["state"] == "cancelled"
    assert client.post("/api/v1/jobs/" + job["id"] + "/retry").status_code == 202
    complete(monkeypatch)
    ready = client.get("/api/v1/jobs/" + job["id"]).json()
    assert ready["state"] == "ready" and ready["pages_done"] == 3
    assert client.post("/api/v1/jobs/" + job["id"] + "/cancel").status_code == 409


def test_explicit_version_keeps_old_active_until_ready(client, tmp_path, monkeypatch):
    first, old_data = upload(client, tmp_path)
    complete(monkeypatch)
    new_data = make_pdf(tmp_path / "changed.pdf", 2)
    assert (
        client.post(
            "/api/v1/ingest", files={"file": ("report.pdf", new_data)}
        ).status_code
        == 409
    )
    second = client.post(
        "/api/v1/documents/" + first["document_id"] + "/versions",
        files={"file": ("report.pdf", new_data)},
    ).json()
    lib = routes.get_library()
    assert lib.ready_builds() == [first["build_id"]]
    complete(monkeypatch)
    assert lib.ready_builds() == [second["build_id"]]
    old_url = "/api/v1/versions/" + first["version_id"] + "/file"
    assert client.get(old_url).content == old_data
    versions = client.get(
        "/api/v1/documents/" + first["document_id"] + "/versions"
    ).json()
    assert [version["ordinal"] for version in versions] == [2, 1]


def test_logical_delete_is_immediate_cleanup_is_retryable(
    client, tmp_path, monkeypatch
):
    job, _ = upload(client, tmp_path)
    complete(monkeypatch)
    assert client.get("/api/v1/stats").json()["total_vectors"] == 3
    deletion = client.delete("/api/v1/documents/" + job["document_id"])
    assert deletion.status_code == 202
    assert client.get("/api/v1/documents").json() == []
    assert client.get("/api/v1/stats").json()["total_vectors"] == 0
    assert client.get("/api/v1/stats").json()["pending_jobs"] == 1
    assert client.get("/api/v1/jobs/" + job["id"]).json()["document_deleted"]
    assert (
        client.get("/api/v1/versions/" + job["version_id"] + "/file").status_code == 404
    )
    lib = routes.get_library()
    original = lib.store.delete_by_payload_filter
    monkeypatch.setattr(
        lib.store, "delete_by_payload_filter", MagicMock(side_effect=RuntimeError)
    )
    lib.process_one()
    deletion_id = deletion.json()["id"]
    assert client.get("/api/v1/jobs/" + deletion_id).json()["state"] == "failed"
    monkeypatch.setattr(lib.store, "delete_by_payload_filter", original)
    assert client.post("/api/v1/jobs/" + deletion_id + "/retry").status_code == 202
    lib.process_one()
    assert lib.metadata.job(deletion_id)["state"] == "ready"


def test_health_responsive_during_query(client, monkeypatch):
    started, finish = Event(), Event()
    synthesizer = MagicMock()

    def query(**kwargs):
        started.set()
        assert finish.wait(5)
        return "answer", []

    synthesizer.query.side_effect = query
    monkeypatch.setattr(routes.get_library(), "ready_builds", lambda: ["test"])
    monkeypatch.setattr(routes, "get_components", lambda: (None, synthesizer))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/v1/query", json={"query": "test"})
        try:
            assert started.wait(5)
            assert client.get("/health").status_code == 200
        finally:
            finish.set()
        assert future.result(timeout=5).status_code == 200


def test_component_initialization_shared_and_cleanup(client, monkeypatch):
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


def test_embedding_initialization_failure_can_retry_without_provider(
    client, monkeypatch
):
    from vision_rag.models import colpali_embedder, gemini_generator

    embedder = MagicMock()
    load_model = MagicMock(side_effect=[RuntimeError("model failed"), embedder])
    provider = MagicMock(side_effect=AssertionError)
    monkeypatch.setattr(colpali_embedder, "ColPaliEmbeddingModel", load_model)
    monkeypatch.setattr(gemini_generator, "GeminiGenerator", provider)
    with pytest.raises(RuntimeError):
        routes.get_pipeline()
    assert routes._model_state == "failed"
    routes.get_pipeline()
    assert routes._model_state == "ready"
    provider.assert_not_called()


def test_job_trace_records_are_correlated_without_document_content(
    client, tmp_path, caplog, monkeypatch
):
    import json
    import logging

    job, _ = upload(client, tmp_path, filename="private-report.pdf")
    with caplog.at_level(logging.INFO, logger="vision_rag.timings"):
        complete(monkeypatch)
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "vision_rag.timings"
    ]
    assert {"rendering", "embedding", "database_upsert", "ingestion_job"} <= {
        record["stage"] for record in records
    }
    assert all(record["trace_id"] == job["id"] for record in records)
    assert "private-report" not in str(records)


def test_unready_query_and_unknown_job_do_not_initialize_models(client, monkeypatch):
    initialize = MagicMock(side_effect=AssertionError)
    monkeypatch.setattr(routes, "get_components", initialize)
    assert (
        client.post("/api/v1/query", json={"query": "test"}).json()["answer"]
        == "No ready documents found."
    )
    assert client.get("/api/v1/jobs/missing").status_code == 404
    assert client.post("/api/v1/jobs/missing/retry").status_code == 404
    assert client.get("/api/v1/versions/missing/file").status_code == 404
    initialize.assert_not_called()


def test_startup_warmup_uses_embedding_pipeline_without_provider(client, monkeypatch):
    from vision_rag.api import main

    initialize = MagicMock()
    monkeypatch.setattr(settings, "model_warmup", True)
    monkeypatch.setattr(main, "get_pipeline", initialize)
    with TestClient(app) as warmed:
        initialize.assert_called_once()
        assert warmed.get("/health").status_code == 200
