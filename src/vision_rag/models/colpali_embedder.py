"""ColPali baseline encoder with bounded, serialized inference."""

import threading
from typing import Any, cast

from PIL import Image

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.runtime import select_device
from vision_rag.telemetry import stage


class ColPaliEmbeddingModel(BaseEmbeddingModel):
    def __init__(
        self,
        model_name: str = "vidore/colpali-v1.3",
        device: str | None = "auto",
        precision: str = "auto",
        batch_size: int = 2,
    ) -> None:
        # Heavy dependencies are loaded only during explicit initialization.
        with stage("model_imports"):
            from colpali_engine.models import ColPali, ColPaliProcessor

        self.device, dtype = select_device(device or "auto", precision)
        if batch_size < 1:
            raise ValueError("Batch size must be positive")
        self.batch_size = batch_size
        self._lock = threading.Lock()
        with stage("model_loading", device=self.device, precision=str(dtype)):
            self.model: Any = ColPali.from_pretrained(
                model_name, torch_dtype=dtype, device_map=self.device
            ).eval()
            self.processor: Any = ColPaliProcessor.from_pretrained(model_name)

    def _encode_batch(self, items: list[Any], images: bool) -> list[Any]:
        import torch

        with stage("inference_queue"):
            self._lock.acquire()
        try:
            with torch.inference_mode(), stage("model_inference", items=len(items)):
                return self._infer(items, images)
        finally:
            self._lock.release()

    def _infer(self, items: list[Any], images: bool) -> list[Any]:
        batch = None
        embeddings = None
        try:
            batch = (
                self.processor.process_images(items)
                if images
                else self.processor.process_queries(items)
            ).to(self.device)
            embeddings = self.model(**batch)
            # Preserve the historical pooled index until versioned reindexing.
            return cast(list[Any], embeddings.mean(dim=1).cpu().tolist())
        finally:
            del embeddings, batch

    def _encode(self, items: list[Any], images: bool) -> list[Any]:
        import torch

        result: list[Any] = []
        for start in range(0, len(items), self.batch_size):
            chunk = items[start : start + self.batch_size]
            try:
                result.extend(self._encode_batch(chunk, images))
            except torch.OutOfMemoryError:
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                if len(chunk) == 1:
                    raise RuntimeError(
                        "A single page exceeds accelerator memory. Choose a smaller "
                        "model or use EMBEDDING_DEVICE=cpu."
                    ) from None
                # Retry every page; never silently omit an out-of-memory batch.
                for item in chunk:
                    result.extend(self._encode([item], images))
        return result

    def encode_images(self, images: list[Image.Image]) -> list[Any]:
        return self._encode(images, True)

    def encode_queries(self, queries: list[str]) -> list[Any]:
        return self._encode(queries, False)

    def close(self) -> None:
        import torch

        with self._lock:
            self.model = None
            self.processor = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
