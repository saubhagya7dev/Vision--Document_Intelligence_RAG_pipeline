"""Stage timings without document content or credentials."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4

trace_id: ContextVar[str] = ContextVar("trace_id", default="startup")
logger = logging.getLogger("vision_rag.timings")


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
