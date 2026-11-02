from pathlib import Path
from typing import Any, Callable

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
        resolve_source: Callable[[str], tuple[dict[str, Any], Path]] | None = None,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.document_loader = document_loader
        self.resolve_source = resolve_source

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
                    display = payload.get("original_filename", source)
                    if self.resolve_source is not None:
                        version, path = self.resolve_source(payload["version_id"])
                        if (
                            payload.get("document_id") != version["document_id"]
                            or not isinstance(page, int)
                            or not 1 <= page <= version["page_count"]
                        ):
                            raise ValueError(
                                "Evidence does not match its document version"
                            )
                        source, display = str(path), version["filename"]
                    if not source or not isinstance(page, int):
                        continue
                    if (source, page) in seen:
                        continue
                    seen.add((source, page))
                    images.append(self.document_loader.load_page(source, page))
                    sources.append(
                        {
                            "score": result.get("score"),
                            "source": display,
                            "page": page,
                            "channel": payload.get("channel", "visual"),
                            **{
                                key: payload[key]
                                for key in ("version_id", "document_id", "build_id")
                                if key in payload
                            },
                        }
                    )
            if not images:
                return "Could not load the images for the retrieved documents.", sources
            with stage("provider_generation", pages=len(images)):
                answer = self.generator.generate(query=user_query, images=images)
            return answer, sources
        finally:
            for image in images:
                image.close()
