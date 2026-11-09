"""Public provider failures without SDK messages, URLs or credentials."""

from functools import wraps
from typing import Callable, ParamSpec, TypeVar

import httpx
from google.genai import errors

P = ParamSpec("P")
R = TypeVar("R")


class ProviderFailure(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = status_code  # Existing diagnostic runners record this field.


def provider_request(function: Callable[P, R]) -> Callable[P, R]:
    """Normalize only failures raised inside a provider adapter call."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except httpx.TimeoutException:
            raise ProviderFailure(
                504,
                "The answer provider timed out. Retry without streaming, choose "
                "fewer documents, or use Find pages for local retrieval.",
            ) from None
        except httpx.TransportError:
            raise ProviderFailure(
                503,
                "The connection to the answer provider failed. Check your network "
                "and retry, or use Find pages for local retrieval.",
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
                        "The answer provider is temporarily unavailable. Retry without "
                        "streaming or try again later. Find pages remains available."
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
            raise ProviderFailure(status, message) from None

    return wrapped
