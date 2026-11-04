"""Small transparent experimental router; train only on disjoint source families."""

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from vision_rag.retrieval.engine import TIERS


def features(query: str, documents: int) -> list[float]:
    lower = query.lower()
    return [
        1.0,
        min(len(query), 1000) / 200,
        min(documents, 6) / 6,
        float(any(w in lower for w in ("chart", "bar", "diagram", "color", "plot"))),
        float(
            any(
                w in lower
                for w in ("scan", "image-only", "registration", "handwritten")
            )
        ),
        float(any(w in lower for w in ("compare", "both", "difference"))),
        float(bool(re.search(r"[A-Za-z]+\d+", query))),
        sum(c.isdigit() for c in query) / max(len(query), 1),
    ]


class CostRouter:
    def __init__(self, weights: Any, profile: str = "") -> None:
        self.weights = np.asarray(weights, dtype=np.float64)
        if self.weights.shape != (8, 4) or not np.isfinite(self.weights).all():
            raise ValueError("Invalid router coefficients")
        self.profile = profile

    def choose(self, query: str, documents: int = 0) -> str:
        return TIERS[
            int(np.argmax(np.asarray(features(query, documents)) @ self.weights))
        ]

    @classmethod
    def train(cls, samples: list[dict[str, Any]], profile: str) -> "CostRouter":
        if len(samples) < 12:
            raise ValueError("At least 12 development samples are required")
        x = np.asarray([features(s["query"], s["documents"]) for s in samples])
        y = np.eye(4)[[s["label"] for s in samples]]
        weights = np.zeros((8, 4))
        for _ in range(1200):
            logits = x @ weights
            logits -= logits.max(axis=1, keepdims=True)
            probs = np.exp(logits)
            probs /= probs.sum(axis=1, keepdims=True)
            weights -= 0.2 * (x.T @ (probs - y) / len(x) + 0.01 * weights)
        return cls(weights, profile)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profile": self.profile,
                    "weights": self.weights.tolist(),
                },
                indent=2,
            )
            + "\n"
        )

    @classmethod
    def load(cls, path: Path) -> "CostRouter":
        data = json.loads(path.read_text())
        if data["version"] != 1:
            raise ValueError("Unsupported router version")
        return cls(data["weights"], data["profile"])


def heuristic(query: str) -> str:
    return "visual" if features(query, 0)[3] or features(query, 0)[4] else "text"
