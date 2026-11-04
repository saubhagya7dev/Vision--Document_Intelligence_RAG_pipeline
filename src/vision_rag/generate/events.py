"""Internal streaming callbacks; final structured answers remain authoritative."""

from typing import Any, Callable

Emit = Callable[[str, dict[str, Any]], None]
Cancelled = Callable[[], bool]


class QuestionCancelled(RuntimeError):
    pass


def checkpoint(cancelled: Cancelled | None) -> None:
    if cancelled and cancelled():
        raise QuestionCancelled("Question cancelled")
