"""Stage timings without document content or credentials."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4

from pydantic import SecretStr

trace_id: ContextVar[str] = ContextVar("trace_id", default="startup")
logger = logging.getLogger("vision_rag.timings")


class SecretFilter(logging.Filter):
    """Redact configured credentials, including formatted exception messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        from vision_rag.config import settings

        secrets = [
            secret.get_secret_value() if isinstance(secret, SecretStr) else secret
            for secret in (settings.provider_api_key, settings.access_token)
        ]

        def redact(value: Any) -> Any:
            if isinstance(value, str):
                for secret in secrets:
                    if secret:
                        value = value.replace(secret, "[redacted]")
                return value
            if isinstance(value, tuple):
                return tuple(redact(item) for item in value)
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if value is None or isinstance(value, (int, float, bool)):
                return value
            return redact(str(value))

        # Uvicorn reuses args for its colored message and access fields. Keep
        # their structure and numeric types instead of flattening the record.
        record.msg = redact(record.msg)
        record.args = redact(record.args)
        if "color_message" in record.__dict__:
            record.__dict__["color_message"] = redact(record.__dict__["color_message"])
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def protect_logs() -> None:
    handlers = set(logging.getLogger().handlers)
    for item in logging.Logger.manager.loggerDict.values():
        if isinstance(item, logging.Logger):
            handlers.update(item.handlers)
    for handler in handlers:
        if not any(isinstance(f, SecretFilter) for f in handler.filters):
            handler.addFilter(SecretFilter())


@contextmanager
def trace(value: str | None = None) -> Iterator[str]:
    token = trace_id.set(value or uuid4().hex)
    try:
        yield trace_id.get()
    finally:
        trace_id.reset(token)


@contextmanager
def stage(name: str, **fields: Any) -> Iterator[None]:
    started = perf_counter()
    outcome = "ok"
    try:
        yield
    except BaseException:
        outcome = "error"
        raise
    finally:
        logger.info(
            json.dumps(
                {
                    "trace_id": trace_id.get(),
                    "stage": name,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "outcome": outcome,
                    **fields,
                }
            )
        )
