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

        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        for secret in (settings.provider_api_key, settings.access_token):
            value = (
                secret.get_secret_value()
                if isinstance(secret, SecretStr)
                else secret
            )
            if value:
                message = message.replace(str(value), "[redacted]")
        record.msg, record.args = message, ()
        record.exc_info = None
        record.exc_text = None
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
