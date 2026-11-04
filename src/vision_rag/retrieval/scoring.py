"""Exact late interaction and rank fusion, independent of model libraries."""

from typing import Any

import numpy as np


def matrix(value: Any) -> np.ndarray[Any, Any]:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2 or not array.shape[0] or not array.shape[1]:
        raise ValueError("Expected a nonempty token-by-dimension matrix")
    if not np.isfinite(array).all():
        raise ValueError("Embedding contains nonfinite values")
    return array


def maxsim(query: Any, document: Any) -> float:
    q, d = matrix(query), matrix(document)
    if q.shape[1] != d.shape[1]:
        raise ValueError("Query and document dimensions differ")
    # No synthetic zero rows: those would incorrectly clamp negative maxima.
    return float((q @ d.T).max(axis=1).sum(dtype=np.float64))


def centroid(tokens: Any) -> list[float]:
    value = matrix(tokens).mean(axis=0)
    norm = float(np.linalg.norm(value))
    if norm <= 0:
        raise ValueError("Token centroid is zero")
    return [float(x) for x in value / norm]


def fuse(
    channels: list[list[dict[str, Any]]], method: str = "rrf", limit: int = 40
) -> list[dict[str, Any]]:
    if method not in ("rrf", "borda"):
        raise ValueError("Unknown rank fusion method")
    hits: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for channel in channels:
        seen = set()
        for rank, hit in enumerate(channel, 1):
            key = str(hit["id"])
            if key in seen:
                continue
            seen.add(key)
            hits.setdefault(key, hit)
            scores[key] = scores.get(key, 0) + (
                1 / (60 + rank)
                if method == "rrf"
                else (len(channel) + 1 - rank) / max(len(channel), 1)
            )
    return [
        {**hits[key], "score": scores[key], "score_kind": method}
        for key in sorted(hits, key=lambda k: (-scores[k], k))[:limit]
    ]
