import io
import logging

import pytest
from pydantic import SecretStr
from uvicorn.logging import AccessFormatter, DefaultFormatter

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


@pytest.mark.parametrize("colors", [False, True])
def test_uvicorn_startup_and_access_formatting_survives_redaction(monkeypatch, colors):
    secret = "fixture-owner-token"
    monkeypatch.setattr(settings, "access_token", SecretStr(secret))
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "fixture",
        1,
        "Uvicorn running on %s://%s:%d",
        ("http", "127.0.0.1", 8000),
        None,
    )
    record.color_message = "Uvicorn running on %s://%s:%d"
    SecretFilter().filter(record)
    output = DefaultFormatter("%(message)s", use_colors=colors).format(record)
    assert "http://127.0.0.1:8000" in output
    assert "%s" not in output and "%d" not in output
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "fixture",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", "/" + secret, "1.1", 200),
        None,
    )
    SecretFilter().filter(record)
    output = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=colors,
    ).format(record)
    assert secret not in output
    assert "[redacted]" in output and "200" in output
