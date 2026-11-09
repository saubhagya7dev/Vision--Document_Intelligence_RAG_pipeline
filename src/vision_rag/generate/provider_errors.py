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
        self.retry_after: float | None = None
        self.daily_quota = False


def quota_details(error: errors.APIError) -> tuple[bool, bool, float | None]:
    payload = error.details
    if not isinstance(payload, dict):
        return False, False, None
    payload = payload.get("error", payload)
    if not isinstance(payload, dict):
        return False, False, None
    daily, minute, delay = False, False, None
    details = payload.get("details", [])
    if not isinstance(details, list):
        return daily, minute, delay
    for item in details:
        if not isinstance(item, dict):
            continue
        raw = item.get("retryDelay")
        if isinstance(raw, str) and raw.endswith("s"):
            try:
                seconds = float(raw[:-1])
                if 0 < seconds <= 86400:
                    delay = seconds
            except ValueError:
                pass
        violations = item.get("violations", [])
        if isinstance(violations, list):
            for violation in violations:
                if isinstance(violation, dict):
                    identifier = str(violation.get("quotaId", "")).lower()
                    daily |= "perday" in identifier
                    minute |= "perminute" in identifier
    return daily, minute, delay


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
            daily, minute, delay = (
                quota_details(error) if code == 429 else (False, False, None)
            )
            if code == 429:
                status, message = (
                    429,
                    (
                        "The answer provider quota is exhausted. Use Find pages for "
                        "local retrieval, or retry after the provider quota resets."
                    ),
                )
                if daily:
                    message = (
                        "The daily answer-provider quota for this model is exhausted. "
                        "Wait for its reset or configure another model/account with "
                        "available quota. Find pages remains available."
                    )
                elif minute:
                    message = (
                        "The answer provider's short-term rate limit is still active. "
                        "Try again shortly. Find pages remains available."
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
            failure = ProviderFailure(
                status,
                message,
                retryable=code in (500, 502, 503, 504)
                or (
                    code == 429
                    and not daily
                    and minute
                    and delay is not None
                    and delay <= 30
                ),
            )
            failure.retry_after, failure.daily_quota = delay, daily
            raise failure from None

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = parameters.bind(*args, **kwargs).arguments
        owner = bound.get("self")
        attempts = max(1, min(3, int(getattr(owner, "attempts", 1))))
        cancelled = bound.get("cancelled")
        checkpoint(cancelled)
        quota_hold = getattr(owner, "_provider_quota", None)
        if quota_hold and quota_hold[0] > monotonic():
            raise ProviderFailure(429, quota_hold[1])
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
                if (
                    error.daily_quota
                    and error.retry_after is not None
                    and owner is not None
                ):
                    owner._provider_quota = (
                        monotonic() + error.retry_after,
                        str(error),
                    )
                if not error.retryable or attempt + 1 == attempts:
                    raise
                retry_pause(
                    max(min(2.0, 0.5 * 2**attempt), error.retry_after or 0), cancelled
                )
        raise AssertionError("Provider attempts must be positive")

    return wrapped
