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
            "still unavailable",
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
    provider.attempts = 3
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


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("private"),
        httpx.ConnectError("private"),
        errors.ServerError(503, {"error": {"message": "private"}}),
    ],
)
def test_transient_full_answer_failure_recovers_within_one_attempt_budget(
    monkeypatch, failure
):
    from vision_rag.generate import provider_errors

    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 3
    provider.client = MagicMock()
    success = SimpleNamespace(
        text='{"status":"insufficient","claims":[]}', usage_metadata=None
    )
    provider.client.models.generate_content.side_effect = [failure, failure, success]
    pauses = []
    monkeypatch.setattr(
        provider_errors,
        "retry_pause",
        lambda seconds, cancelled: pauses.append(seconds),
    )
    assert provider.generate_grounded("question", [], []) == {
        "status": "insufficient",
        "claims": [],
    }
    assert provider.client.models.generate_content.call_count == 3
    assert pauses == [0.5, 1.0]


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 501])
def test_permanent_and_quota_failures_are_not_retried(monkeypatch, code):
    from vision_rag.generate import provider_errors

    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 3
    provider.client = MagicMock()
    provider.client.models.generate_content.side_effect = errors.APIError(
        code, {"error": {"message": "private"}}
    )
    pause = MagicMock()
    monkeypatch.setattr(provider_errors, "retry_pause", pause)
    with pytest.raises(ProviderFailure):
        provider.generate_grounded("question", [], [])
    assert provider.client.models.generate_content.call_count == 1
    pause.assert_not_called()


def test_repeated_timeout_stops_at_the_configured_attempt_limit(monkeypatch):
    from vision_rag.generate import provider_errors

    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 2
    provider.client = MagicMock()
    provider.client.models.generate_content.side_effect = httpx.ReadTimeout("private")
    monkeypatch.setattr(provider_errors, "retry_pause", lambda *_: None)
    with pytest.raises(ProviderFailure) as caught:
        provider.generate_grounded("question", [], [])
    assert caught.value.status_code == 504
    assert provider.client.models.generate_content.call_count == 2


def test_cancellation_stops_automatic_recovery_before_another_call():
    from vision_rag.generate.events import QuestionCancelled

    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 2
    provider.client = MagicMock()
    cancelled = [False]

    def fail(**kwargs):
        cancelled[0] = True
        raise httpx.ReadTimeout("private")

    provider.client.models.generate_content.side_effect = fail
    with pytest.raises(QuestionCancelled):
        provider.generate_grounded("question", [], [], cancelled=lambda: cancelled[0])
    assert provider.client.models.generate_content.call_count == 1


def quota_error(identifier, delay):
    return errors.ClientError(
        429,
        {
            "error": {
                "details": [
                    {"violations": [{"quotaId": identifier}]},
                    {"retryDelay": delay},
                ]
            }
        },
    )


def test_known_daily_quota_blocks_further_calls_until_reported_reset(monkeypatch):
    from vision_rag.generate import provider_errors

    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 3
    provider.client = MagicMock()
    clock = [100.0]
    monkeypatch.setattr(provider_errors, "monotonic", lambda: clock[0])
    provider.client.models.generate_content.side_effect = [
        quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "3600s"),
        SimpleNamespace(
            text='{"status":"insufficient","claims":[]}', usage_metadata=None
        ),
    ]
    for _ in range(3):
        with pytest.raises(ProviderFailure, match="daily"):
            provider.generate_grounded("question", [], [])
    assert provider.client.models.generate_content.call_count == 1
    clock[0] += 3601
    assert provider.generate_grounded("question", [], [])["status"] == "insufficient"
    assert provider.client.models.generate_content.call_count == 2


def test_short_rate_limit_waits_once_then_recovers(monkeypatch):
    from vision_rag.generate import provider_errors

    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 2
    provider.client = MagicMock()
    provider.client.models.generate_content.side_effect = [
        quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "2s"),
        SimpleNamespace(
            text='{"status":"insufficient","claims":[]}', usage_metadata=None
        ),
    ]
    pauses = []
    monkeypatch.setattr(
        provider_errors, "retry_pause", lambda seconds, _: pauses.append(seconds)
    )
    assert provider.generate_grounded("question", [], [])["status"] == "insufficient"
    assert pauses == [2] and provider.client.models.generate_content.call_count == 2


def test_long_rate_limit_is_not_blindly_retried():
    provider = object.__new__(GeminiGenerator)
    provider.model_name, provider.attempts = "fixture", 3
    provider.client = MagicMock()
    provider.client.models.generate_content.side_effect = quota_error(
        "RequestsPerMinute", "90s"
    )
    with pytest.raises(ProviderFailure, match="short-term"):
        provider.generate_grounded("question", [], [])
    assert provider.client.models.generate_content.call_count == 1
