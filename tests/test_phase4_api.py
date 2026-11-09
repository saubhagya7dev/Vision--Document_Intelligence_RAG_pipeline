import pytest
from fastapi.testclient import TestClient
from test_phase4_indexes import FakeModels

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes
from vision_rag.api.main import app
from vision_rag.config import settings


class FakeProvider:
    last_usage = {"prompt_token_count": 12, "candidates_token_count": 3}

    def close(self):
        pass

    def generate_grounded(self, query, evidence, images):
        return {
            "status": "supported",
            "claims": [
                {"text": "Revenue is 120 units.", "citations": [evidence[0]["id"]]}
            ],
        }


@pytest.fixture
def client(tmp_path, monkeypatch):
    from vision_rag.models import gemini_generator

    for key, value in {
        "data_dir": tmp_path / "library",
        "qdrant_mode": "local",
        "ingestion_worker_enabled": False,
        "import_legacy_pdfs": False,
        "model_warmup": False,
        "phase4_enabled": True,
        "hybrid_ingestion": True,
        "render_dpi": 72,
    }.items():
        monkeypatch.setattr(settings, key, value)
    for key in (
        "_loader",
        "_vdb",
        "_pipeline",
        "_synthesizer",
        "_library",
        "_retrieval_models",
    ):
        monkeypatch.setattr(routes, key, None)
    models = FakeModels()
    monkeypatch.setattr(routes, "get_retrieval_models", lambda: models)
    monkeypatch.setattr(
        gemini_generator, "GeminiGenerator", lambda **kwargs: FakeProvider()
    )
    with TestClient(app) as client:
        yield client


def test_phase4_api_build_query_scope_and_rollback(client, tmp_path):
    path = create_pdf(tmp_path / "fixture.pdf", ("text", "table"))
    job = client.post(
        "/api/v1/ingest", files={"file": ("report.pdf", path.read_bytes())}
    ).json()
    library = routes.get_library()
    library.process_one()
    assert client.post("/api/v1/query", json={"query": "ALPHA42"}).status_code == 409
    queued = client.post("/api/v1/indexes", json={}).json()
    assert queued["state"] == "queued"
    library.process_one()
    state = client.get("/api/v1/indexes").json()
    assert state["active"] == queued["id"]
    response = client.post(
        "/api/v1/query", json={"query": "ALPHA42", "document_ids": [job["document_id"]]}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["grounding_status"] == "supported"
    assert result["claims"][0]["citations"] == [result["sources"][0]["evidence_id"]]
    assert result["sources"][0]["version_id"] == job["version_id"]
    assert result["original_query"] == result["retrieval_query"] == "ALPHA42"
    assert result["provider_usage"] == [FakeProvider.last_usage]
    assert (
        client.post(
            "/api/v1/query", json={"query": "ALPHA42", "document_ids": []}
        ).json()["sources"]
        == []
    )
    assert (
        client.post(
            "/api/v1/query", json={"query": "ALPHA42", "document_ids": ["missing"]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/query", json={"query": "ALPHA42", "page_start": 3, "page_end": 1}
        ).status_code
        == 422
    )
    second = client.post("/api/v1/indexes", json={"activate_when_ready": False}).json()
    library.process_one()
    assert client.get("/api/v1/indexes").json()["active"] == queued["id"]
    assert client.post(f"/api/v1/indexes/{second['id']}/activate").status_code == 200
    assert client.post(f"/api/v1/indexes/{queued['id']}/activate").status_code == 200
    assert client.post(f"/api/v1/indexes/{queued['id']}/cancel").status_code == 409


def test_find_pages_needs_no_provider_and_quota_is_actionable(
    client, tmp_path, monkeypatch
):
    path = create_pdf(tmp_path / "fixture.pdf", ("text", "table"))
    client.post("/api/v1/ingest", files={"file": ("report.pdf", path.read_bytes())})
    library = routes.get_library()
    library.process_one()
    library.retrieval.queue()
    library.process_one()

    def no_provider():
        raise AssertionError("Find pages must not initialize the provider")

    monkeypatch.setattr(routes, "get_components", no_provider)
    result = client.post(
        "/api/v1/query", json={"query": "ALPHA42", "evidence_only": True}
    )
    assert result.status_code == 200
    assert result.json()["sources"]
    assert result.json()["provider_calls"] == 0
    assert result.json()["grounding_status"] == "evidence_only"

    class Quota(Exception):
        code = 429

    def exhausted():
        raise Quota()

    monkeypatch.setattr(routes, "get_components", exhausted)
    result = client.post("/api/v1/query", json={"query": "ALPHA42"})
    assert result.status_code == 429
    assert "Find pages" in result.json()["detail"]


@pytest.mark.parametrize(
    "status,detail", [(504, "provider timed out"), (503, "provider unavailable")]
)
def test_provider_failures_keep_their_actionable_http_status(
    client, tmp_path, monkeypatch, status, detail
):
    from vision_rag.generate.provider_errors import ProviderFailure

    path = create_pdf(tmp_path / "provider.pdf", ("text",))
    client.post("/api/v1/ingest", files={"file": ("provider.pdf", path.read_bytes())})
    library = routes.get_library()
    library.process_one()
    library.retrieval.queue()
    library.process_one()

    def fail():
        raise ProviderFailure(status, detail)

    monkeypatch.setattr(routes, "get_components", fail)
    response = client.post("/api/v1/query", json={"query": "ALPHA42"})
    assert response.status_code == status
    assert response.json()["detail"] == detail


def test_warmup_loads_models_and_lazy_adapter_is_not_ready(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(settings, "phase4_enabled", True)
    models = MagicMock(text=None, visual=None)
    monkeypatch.setattr(routes, "_model_state", "ready")
    monkeypatch.setattr(routes, "_retrieval_models", models)
    assert routes.model_state() == "not_loaded"
    monkeypatch.setattr(routes, "get_pipeline", lambda: None)
    routes.warmup_components()
    models.encode_text.assert_called_once()
    models.encode_visual.assert_called_once()


def test_provider_retries_and_deadlines_are_bounded(monkeypatch):
    from unittest.mock import MagicMock

    from vision_rag.models import gemini_generator

    constructor = MagicMock()
    monkeypatch.setattr(gemini_generator.genai, "Client", constructor)
    generator = gemini_generator.GeminiGenerator(
        "fake", "not-a-real-key", timeout_ms=2000, attempts=2
    )
    options = constructor.call_args.kwargs["http_options"]
    assert options.timeout == 2000 and options.retry_options.attempts == 2
    assert options.retry_options.http_status_codes == [429, 500, 502, 503, 504]
    generator.close()
