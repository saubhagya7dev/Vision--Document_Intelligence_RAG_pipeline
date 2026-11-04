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
        revision: str | None = None,
        base_revision: str | None = None,
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
            pinned = {"revision": revision} if revision else {}
            if base_revision:
                import json

                from huggingface_hub import hf_hub_download

                config_path = hf_hub_download(
                    model_name, "adapter_config.json", revision=revision
                )
                with open(config_path, encoding="utf-8") as stream:
                    base_name = json.load(stream)["base_model_name_or_path"]
                self.model: Any = ColPali.from_pretrained(
                    base_name,
                    revision=base_revision,
                    torch_dtype=dtype,
                    device_map=self.device,
                )
                from pathlib import Path

                adapter_path = hf_hub_download(
                    model_name, "adapter_model.safetensors", revision=revision
                )
                self.model.load_adapter(str(Path(adapter_path).parent))
                self.model.eval()
            else:
                self.model = ColPali.from_pretrained(
                    model_name, torch_dtype=dtype, device_map=self.device, **pinned
                ).eval()
            self.processor: Any = ColPaliProcessor.from_pretrained(model_name, **pinned)
            if self.device == "cuda":
                import torch

                # Release unused loading buffers before the first inference.
                torch.cuda.empty_cache()

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

    def encode_multivectors(self, items: list[Any], images: bool) -> list[Any]:
        import torch

        output = []
        # Single-item bounds avoid padding and keep the laptop memory profile.
        with self._lock, torch.inference_mode():
            for item in items:
                batch = embeddings = None
                try:
                    batch = (
                        self.processor.process_images([item])
                        if images
                        else self.processor.process_queries([item])
                    ).to(self.device)
                    if not images and batch["input_ids"].shape[1] > 256:
                        raise ValueError(
                            "Question exceeds the visual encoder token limit"
                        )
                    embeddings = self.model(**batch)[0].float()
                    mask = batch["attention_mask"][0].bool()
                    if mask.shape[0] != embeddings.shape[0]:
                        raise ValueError("Encoder attention mask shape mismatch")
                    mask &= embeddings.norm(dim=-1) > 0
                    tokens = embeddings[mask]
                    if not len(tokens) or not torch.isfinite(tokens).all():
                        raise ValueError("Invalid multivector output")
                    output.append(tokens.cpu().tolist())
                except torch.OutOfMemoryError:
                    raise RuntimeError(
                        "Visual page exceeds memory; select the CPU profile"
                    ) from None
                finally:
                    del embeddings, batch
        return output

    def close(self) -> None:
        import torch

        with self._lock:
            self.model = None
            self.processor = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
