from fastapi.testclient import TestClient

from vision_rag.api.main import app


def test_health_check():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
