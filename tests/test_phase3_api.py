import pytest
from fastapi.testclient import TestClient

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes
from vision_rag.api.main import app
from vision_rag.config import settings


@pytest.fixture
def hybrid_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "library")
    monkeypatch.setattr(settings, "qdrant_mode", "local")
    monkeypatch.setattr(settings, "ingestion_worker_enabled", False)
    monkeypatch.setattr(settings, "import_legacy_pdfs", False)
    monkeypatch.setattr(settings, "model_warmup", False)
    monkeypatch.setattr(settings, "phase4_enabled", False)
    monkeypatch.setattr(settings, "hybrid_ingestion", True)
    monkeypatch.setattr(settings, "render_dpi", 72)
    for name in ("_loader", "_vdb", "_pipeline", "_synthesizer", "_library"):
        monkeypatch.setattr(routes, name, None)
    with TestClient(app) as client:
        yield client


def test_processing_api_and_text_only_query_do_not_load_visual_model(
    hybrid_client,
    tmp_path,
    monkeypatch,
):
    from unittest.mock import MagicMock

    from vision_rag.models import colpali_embedder, gemini_generator

    model = MagicMock(side_effect=AssertionError("Unnecessary visual model load"))
    monkeypatch.setattr(colpali_embedder, "ColPaliEmbeddingModel", model)
    generator = MagicMock()
    generator.generate.return_value = "Revenue is 120 units."
    monkeypatch.setattr(gemini_generator, "GeminiGenerator", lambda **kw: generator)
    source = create_pdf(tmp_path / "source.pdf", ("text", "text"))
    response = hybrid_client.post(
        "/api/v1/ingest", files={"file": ("report.pdf", source.read_bytes())}
    )
    assert response.status_code == 202
    job = response.json()
    lib = routes.get_library()
    lib.process_one()
    version = job["version_id"]
    base = f"/api/v1/versions/{version}"
    record = hybrid_client.get(base + "/pages/1/text").json()
    assert record["data"]["quality"] == "usable" and record["chunks"]
    result = hybrid_client.post("/api/v1/query", json={"query": "ALPHA42 revenue"})
    assert (
        result.status_code == 200
        and result.json()["sources"][0]["version_id"] == version
    )
    assert result.json()["sources"][0]["channel"] == "lexical"
    model.assert_not_called()
    assert (
        hybrid_client.post(
            base + "/pages/1/processing", json={"mode": "invalid"}
        ).status_code
        == 422
    )
    assert (
        hybrid_client.post(
            base + "/pages/99/processing", json={"mode": "auto"}
        ).status_code
        == 404
    )
    task = hybrid_client.post(base + "/pages/1/processing", json={"mode": "skip"})
    assert task.status_code == 202
    task_id = task.json()["id"]
    assert (
        hybrid_client.post(
            base + "/pages/1/processing", json={"mode": "auto"}
        ).status_code
        == 409
    )
    lib.process_one()
    assert hybrid_client.get("/api/v1/page-tasks/" + task_id).json()["state"] == "ready"
    assert hybrid_client.get(base + "/pages/1/text").json()["chunks"] == []
    assert len(hybrid_client.get(base + "/processing").json()["pages"]) == 2
    assert (
        hybrid_client.delete("/api/v1/documents/" + job["document_id"]).status_code
        == 202
    )
    assert hybrid_client.get(base + "/pages/1/text").status_code == 404
    assert hybrid_client.get("/api/v1/page-tasks/" + task_id).status_code == 404


def test_chunk_settings_reject_invalid_overlap():
    from pydantic import ValidationError

    from vision_rag.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, text_chunk_limit=100, text_chunk_overlap=100)


def test_data_controls_confirmation_history_and_reset(hybrid_client, tmp_path):
    source = create_pdf(tmp_path / "source.pdf", ("text",))
    first = hybrid_client.post(
        "/api/v1/ingest", files={"file": ("first.pdf", source.read_bytes())}
    ).json()
    lib = routes.get_library()
    lib.process_one()
    hybrid_client.post(
        "/api/v1/ingest",
        files={"file": ("queued.pdf", source.read_bytes() + b"\n% queued")},
    )
    assert len(hybrid_client.get("/api/v1/jobs").json()) == 2
    assert (
        hybrid_client.post(
            "/api/v1/maintenance", json={"action": "reset", "confirmation": "CLEAR"}
        ).status_code
        == 422
    )
    assert (
        hybrid_client.post(
            "/api/v1/maintenance",
            json={"action": "reset", "confirmation": "DELETE"},
            headers={"origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
    assert len(lib.documents()) == 2
    response = hybrid_client.post(
        "/api/v1/maintenance", json={"action": "history", "confirmation": "CLEAR"}
    )
    assert response.status_code == 200
    history = hybrid_client.get("/api/v1/jobs").json()
    assert len(history) == 1 and history[0]["state"] == "uploaded"
    assert hybrid_client.get("/api/v1/jobs/" + first["id"]).status_code == 200
    assert len(lib.documents()) == 2
    assert (
        hybrid_client.post(
            "/api/v1/maintenance", json={"action": "cache", "confirmation": "CLEAR"}
        ).status_code
        == 200
    )
    assert (
        hybrid_client.post(
            "/api/v1/maintenance", json={"action": "reset", "confirmation": "DELETE"}
        ).status_code
        == 200
    )
    assert hybrid_client.get("/api/v1/documents").json() == []
    assert hybrid_client.get("/api/v1/jobs").json() == []
    assert hybrid_client.get("/api/v1/stats").json()["total_vectors"] == 0
    assert hybrid_client.get("/api/v1/jobs/" + first["id"]).status_code == 404


def test_current_frontend_assets_are_versioned(hybrid_client):
    response = hybrid_client.get("/workspace")
    assert response.headers["cache-control"] == "no-store"
    assert "/static/styles.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    assert hybrid_client.get("/api/v1/documents").headers["cache-control"] == "no-store"
