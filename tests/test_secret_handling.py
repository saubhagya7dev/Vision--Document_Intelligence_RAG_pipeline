import io
import logging

from pydantic import SecretStr

from vision_rag.config import settings
from vision_rag.telemetry import SecretFilter


def test_config_repr_and_exception_logs_do_not_expose_credentials(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", SecretStr("fixture-provider-key"))
    monkeypatch.setattr(settings, "access_token", SecretStr("fixture-owner-token"))
    assert "fixture-provider-key" not in repr(settings)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(SecretFilter())
    logger = logging.Logger("secret-fixture")
    logger.addHandler(handler)
    try:
        raise RuntimeError("fixture-provider-key")
    except RuntimeError:
        logger.exception("Token %s", "fixture-owner-token")
    assert "fixture-" not in output.getvalue()
    assert "RuntimeError: [redacted]" in output.getvalue()
