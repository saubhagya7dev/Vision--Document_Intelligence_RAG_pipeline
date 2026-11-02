import os
from typing import Any, List

from google import genai
from PIL import Image

from vision_rag.core.generator import BaseVLMGenerator


class GeminiGenerator(BaseVLMGenerator):
    """Implementation of BaseVLMGenerator using Google's Gemini Models."""

    def close(self) -> None:
        self.client.close()

    def __init__(
        self, model_name: str = "gemini-3.6-flash", api_key: str | None = None
    ):
        """Initialize the Gemini Generator.

        Args:
            model_name: Provider model ID; availability must be checked separately.
            api_key: Google API key, or read GOOGLE_API_KEY from the environment.
        """
        self.model_name = model_name

        # Determine API key
        resolved_api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not resolved_api_key:
            raise ValueError("Provide a Google API key or set GOOGLE_API_KEY.")

        self.client = genai.Client(api_key=resolved_api_key)

    def generate(self, query: str, images: List[Image.Image]) -> str:
        """Generate a response from a question and retrieved page images."""

        # Prepare the prompt contents
        # Gemini API accepts a list of text and images
        contents: List[Any] = [
            "You are a helpful assistant. Answer the user's question based strictly "
            "on the provided document pages (images).",
            f"Question: {query}",
            "Document Pages:",
        ]

        # Append all PIL images directly to the contents list
        contents.extend(images)

        print(f"Sending query and {len(images)} images to {self.model_name}...")

        # Generate the response
        response = self.client.models.generate_content(
            model=self.model_name, contents=contents
        )

        return str(response.text)
