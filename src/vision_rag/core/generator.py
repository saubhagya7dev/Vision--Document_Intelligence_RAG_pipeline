from abc import ABC, abstractmethod
from typing import List

from PIL import Image


class BaseVLMGenerator(ABC):
    """Abstract base class for Vision-Language Model generators."""

    def close(self) -> None:
        """Release provider resources, when required by an implementation."""

    @abstractmethod
    def generate(self, query: str, images: List[Image.Image]) -> str:
        """Generate a response using a text query and a list of images.

        Args:
            query: The user's text query.
            images: List of retrieved PIL Images to use as context.

        Returns:
            Generated text response.
        """
        pass
