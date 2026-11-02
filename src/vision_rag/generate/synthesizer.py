from typing import Any

from vision_rag.core.generator import BaseVLMGenerator
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.retrieval.retriever import Retriever
from vision_rag.telemetry import stage


class RAGSynthesizer:
    """Retrieve and render only the evidence pages needed for generation."""

    def __init__(
        self,
        retriever: Retriever,
        generator: BaseVLMGenerator,
        document_loader: DocumentLoader,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.document_loader = document_loader

    def query(
        self, user_query: str, top_k: int = 3
    ) -> tuple[str, list[dict[str, Any]]]:
        retrieved = self.retriever.retrieve(query=user_query, top_k=top_k)
        if not retrieved:
            return "No relevant documents found.", []
        images, sources = [], []
        try:
            with stage("evidence_preparation"):
                seen = set()
                for result in retrieved:
                    payload = result.get("payload", {})
                    source, page = payload.get("source"), payload.get("page_number")
                    if not source or not isinstance(page, int):
                        continue
                    if (source, page) in seen:
                        continue
                    seen.add((source, page))
                    images.append(self.document_loader.load_page(source, page))
                    sources.append(
                        {"score": result.get("score"), "source": source, "page": page}
                    )
            if not images:
                return "Could not load the images for the retrieved documents.", sources
            with stage("provider_generation", pages=len(images)):
                answer = self.generator.generate(query=user_query, images=images)
            return answer, sources
        finally:
            for image in images:
                image.close()
