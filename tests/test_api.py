from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from vision_rag.api.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("vision_rag.api.routes.get_components")
def test_query_endpoint(mock_get_components):
    # Mock the synthesizer
    mock_synthesizer = MagicMock()
    mock_synthesizer.query.return_value = (
        "Generated mock answer",
        [{"source": "test.pdf", "page": 1}],
    )

    mock_get_components.return_value = (None, mock_synthesizer)

    response = client.post(
        "/api/v1/query", json={"query": "What is the revenue?", "top_k": 2}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Generated mock answer"
    assert len(data["sources"]) == 1

    mock_synthesizer.query.assert_called_once_with(
        user_query="What is the revenue?", top_k=2
    )
