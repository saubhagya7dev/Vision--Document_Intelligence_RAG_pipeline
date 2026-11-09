from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors

from vision_rag.generate.provider_errors import ProviderFailure
from vision_rag.models.gemini_generator import GeminiGenerator


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (httpx.ReadTimeout("private transport message"), 504, "timed out"),
        (httpx.ConnectError("private proxy URL"), 503, "connection"),
        (
            errors.ServerError(503, {"error": {"message": "private SDK message"}}),
            503,
            "temporarily unavailable",
        ),
        (
            errors.ClientError(429, {"error": {"message": "private SDK message"}}),
            429,
            "quota",
        ),
        (
            errors.ClientError(403, {"error": {"message": "private SDK message"}}),
            503,
            "denied access",
        ),
    ],
)
def test_stream_failures_close_partial_stream_and_hide_sdk_details(
    error, status, detail
):
    provider = object.__new__(GeminiGenerator)
    provider.model_name = "fixture"
    provider.client = MagicMock()
    closed, deltas = [], []

    def stream():
        try:
            yield SimpleNamespace(text='{"claims":[{"text":"draft', usage_metadata=None)
            raise error
        finally:
            closed.append(True)

    provider.client.models.generate_content_stream.return_value = stream()
    with pytest.raises(ProviderFailure) as caught:
        provider.generate_grounded_stream("question", [{"id": "E1"}], [], deltas.append)
    assert caught.value.status_code == status
    assert detail in str(caught.value)
    assert "private" not in str(caught.value)
    assert closed and deltas
    provider.client.models.generate_content.assert_not_called()
