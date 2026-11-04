import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vision_rag.generate.events import QuestionCancelled
from vision_rag.models.gemini_generator import GeminiGenerator, draft_claims


def test_provider_stream_emits_decoded_provisional_text_and_final_json():
    provider = object.__new__(GeminiGenerator)
    provider.model_name = "fake"
    provider.client = MagicMock()
    raw = json.dumps(
        {
            "status": "supported",
            "claims": [{"text": "Revenue is 120 units. café", "citations": ["E1"]}],
        }
    )
    provider.client.models.generate_content_stream.return_value = iter(
        SimpleNamespace(text=raw[i : i + 4], usage_metadata=None)
        for i in range(0, len(raw), 4)
    )
    deltas = []
    result = provider.generate_grounded_stream(
        "revenue", [{"id": "E1"}], [], deltas.append
    )
    assert "".join(deltas) == result["claims"][0]["text"]
    assert len([d for d in deltas if d]) > 2
    assert (
        draft_claims('{"text":"<img src=x onerror=bad()>')
        == "<img src=x onerror=bad()>"
    )


def test_cancelled_provider_stream_is_closed_and_never_publishes():
    provider = object.__new__(GeminiGenerator)
    provider.model_name = "fake"
    provider.client = MagicMock()
    closed = []

    def stream():
        try:
            yield SimpleNamespace(text='{"text":"draft', usage_metadata=None)
        finally:
            closed.append(True)

    provider.client.models.generate_content_stream.return_value = stream()
    with pytest.raises(QuestionCancelled):
        provider.generate_grounded_stream(
            "question", [{"id": "E1"}], [], lambda _: None, lambda: True
        )
    assert closed
