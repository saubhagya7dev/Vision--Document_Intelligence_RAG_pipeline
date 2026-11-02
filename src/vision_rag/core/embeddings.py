from abc import ABC, abstractmethod
from typing import Any, List

from PIL import Image


class BaseEmbeddingModel(ABC):
    """Abstract base class for vision embedding models."""

    def close(self) -> None:
        """Release owned resources, when required by an implementation."""

    @abstractmethod
    def encode_images(self, images: List[Image.Image]) -> List[Any]:
        """Encode a list of PIL Images into embeddings.

        Args:
            images: List of PIL Images.

        Returns:
            List of embeddings (can be single vectors or multi-vectors).
        """
        pass

    @abstractmethod
    def encode_queries(self, queries: List[str]) -> List[Any]:
        """Encode a list of text queries into embeddings.

        Args:
            queries: List of text queries.

        Returns:
            List of embeddings.
        """
        pass
