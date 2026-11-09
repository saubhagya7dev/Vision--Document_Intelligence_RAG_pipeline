"""Public provider failures without SDK messages, URLs or credentials."""

from functools import wraps
from inspect import signature
from time import monotonic, sleep
from typing import Callable, ParamSpec, TypeVar

import httpx
from google.genai import errors

from vision_rag.generate.events import Cancelled, checkpoint

P = ParamSpec("P")
R = TypeVar("R")


class ProviderFailure(RuntimeError):
    def __init__(self, status_code: int, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = status_code  # Existing diagnostic runners record this field.
        self.retryable = retryable


def retry_pause(seconds: float, cancelled: Cancelled | None) -> None:
    """Keep cancellation responsive during bounded backoff."""
    deadline = monotonic() + seconds
    while True:
        checkpoint(cancelled)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(0.1, remaining))


def provider_request(function: Callable[P, R]) -> Callable[P, R]:
    """Normalize only failures raised inside a provider adapter call."""

    parameters = signature(function)

    def invoke(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except httpx.TimeoutException:
            raise ProviderFailure(
                504,
                "The answer provider timed out after the allowed attempts. "
                "Try fewer documents or use Find pages for local retrieval.",
                retryable=True,
            ) from None
        except httpx.TransportError:
            raise ProviderFailure(
                503,
                "The connection to the answer provider failed. Check your network "
                "and retry, or use Find pages for local retrieval.",
                retryable=True,
            ) from None
        except errors.APIError as error:
            code = error.code
            if code == 429:
                status, message = (
                    429,
                    (
                        "The answer provider quota is exhausted. Use Find pages for "
                        "local retrieval, or retry after the provider quota resets."
                    ),
                )
            elif code in (401, 403):
                status, message = (
                    503,
                    (
                        "The answer provider denied access. Check the configured API "
                        "key and model permissions. Find pages remains available."
                    ),
                )
            elif code == 404:
                status, message = (
                    503,
                    (
                        "The configured answer model is unavailable. Check the model "
                        "configuration. Find pages remains available."
                    ),
                )
            elif code is not None and code >= 500:
                status, message = (
                    503,
                    (
                        "The answer provider is still unavailable after the allowed "
                        "attempts. Try again later. Find pages remains available."
                    ),
                )
            else:
                status, message = (
                    502,
                    (
                        "The answer provider rejected the request. Check the "
                        "configured model and request limits. "
                        "Find pages remains available."
                    ),
                )
            raise ProviderFailure(
                status, message, retryable=code in (500, 502, 503, 504)
            ) from None

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = parameters.bind(*args, **kwargs).arguments
        owner = bound.get("self")
        attempts = max(1, min(3, int(getattr(owner, "attempts", 1))))
        cancelled = bound.get("cancelled")
        # Never replay a stream that may already have emitted provisional text.
        if bound.get("on_delta") is not None:
            attempts = 1
        for attempt in range(attempts):
            checkpoint(cancelled)
            try:
                result = invoke(*args, **kwargs)
                checkpoint(cancelled)
                return result
            except ProviderFailure as error:
                if not error.retryable or attempt + 1 == attempts:
                    raise
                retry_pause(min(2.0, 0.5 * 2**attempt), cancelled)
        raise AssertionError("Provider attempts must be positive")

    return wrapped
