"""Keep the Phase 3 baseline on the same bounded model pool as Phase 4."""

from typing import Any

from PIL import Image

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.models.retrieval_models import RetrievalModels


class PooledAdapter(BaseEmbeddingModel):
    def __init__(self, models: RetrievalModels, specification: dict[str, Any]) -> None:
        self.models, self.spec = models, specification

    def encode_images(self, images: list[Image.Image]) -> list[Any]:
        return self.models.encode_visual(self.spec, images, True, False)

    def encode_queries(self, queries: list[str]) -> list[Any]:
        return self.models.encode_visual(self.spec, queries, False, False)
