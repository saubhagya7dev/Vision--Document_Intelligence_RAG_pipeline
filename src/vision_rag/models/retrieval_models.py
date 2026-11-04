"""Serialize model switches: one visual model on the accelerator at a time."""

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel
from vision_rag.models.text_embedder import TextEmbeddingModel


class RetrievalModels:
    def __init__(
        self, device: str = "auto", precision: str = "auto", cache: Path | None = None
    ) -> None:
        self.device, self.precision = device, precision
        self.lock = threading.RLock()
        self.text: TextEmbeddingModel | None = None
        self.visual: ColPaliEmbeddingModel | None = None
        self.text_key = self.visual_key = ""
        self.cache = cache

    def text_model(self, spec: dict[str, Any]) -> TextEmbeddingModel:
        key = json.dumps([spec["text_model"], spec["text_revision"]])
        if self.text is None or key != self.text_key:
            if self.text is not None:
                self.text.close()
            self.text = None
            self.text_key = ""
            self.text = TextEmbeddingModel(spec["text_model"], spec["text_revision"])
            self.text_key = key
        if self.text.dimensions != spec["text_dimensions"]:
            raise ValueError("Text encoder dimensions do not match index profile")
        return self.text

    def encode_text(
        self, spec: dict[str, Any], texts: list[str], query: bool = False
    ) -> list[Any]:
        with self.lock:
            return self.text_model(spec).encode(texts, query)

    def split_text(self, spec: dict[str, Any], text: str) -> list[str]:
        with self.lock:
            return self.text_model(spec).split(text)

    def encode_visual(
        self,
        spec: dict[str, Any],
        items: list[Any],
        images: bool,
        multivector: bool = True,
    ) -> list[Any]:
        key = json.dumps(
            [
                spec["visual_model"],
                spec["visual_revision"],
                spec["visual_base_revision"],
            ]
        )
        with self.lock:
            cached = None
            artifact = None
            if images and len(items) == 1 and self.cache is not None:
                image = items[0]
                fingerprint = hashlib.sha256(
                    key.encode() + str(image.size).encode() + image.tobytes()
                ).hexdigest()
                artifact = self.cache / (fingerprint + ".npz")
                if artifact.exists():
                    try:
                        with np.load(artifact, allow_pickle=False) as arrays:
                            cached = arrays["tokens"].astype(np.float32)
                        if (
                            cached.ndim != 2
                            or cached.shape[0] == 0
                            or cached.shape[1] != spec["visual_dimensions"]
                            or not np.isfinite(cached).all()
                        ):
                            cached = None
                    except (OSError, ValueError, KeyError):
                        cached = None
            if cached is not None:
                return [
                    cached.tolist() if multivector else cached.mean(axis=0).tolist()
                ]
            if self.visual is None or key != self.visual_key:
                if self.visual is not None:
                    self.visual.close()
                self.visual = None
                self.visual_key = ""
                self.visual = ColPaliEmbeddingModel(
                    spec["visual_model"],
                    self.device,
                    self.precision,
                    1,
                    revision=spec["visual_revision"],
                    base_revision=spec["visual_base_revision"],
                )
                self.visual_key = key
            if multivector or images:
                output = self.visual.encode_multivectors(items, images)
                if artifact is not None:
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    temporary = artifact.with_suffix(f".{uuid4().hex}.tmp")
                    try:
                        with temporary.open("wb") as stream:
                            np.savez_compressed(
                                stream, tokens=np.asarray(output[0], dtype=np.float32)
                            )
                        os.replace(temporary, artifact)
                    finally:
                        temporary.unlink(missing_ok=True)
                return (
                    output
                    if multivector
                    else [np.asarray(tokens).mean(axis=0).tolist() for tokens in output]
                )
            return (
                self.visual.encode_images(items)
                if images
                else self.visual.encode_queries(items)
            )

    def close(self) -> None:
        with self.lock:
            if self.visual is not None:
                self.visual.close()
            if self.text is not None:
                self.text.close()
            self.visual = self.text = None
