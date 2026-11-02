from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.core.vector_store import BaseVectorStore
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.storage.metadata import identity
from vision_rag.telemetry import stage


class IngestionCancelled(Exception):
    pass


class IngestionPipeline:
    def __init__(
        self,
        loader: DocumentLoader,
        embedder: BaseEmbeddingModel,
        vector_store: BaseVectorStore,
        batch_size: int = 2,
    ):
        self.loader = loader
        self.embedder = embedder
        self.vector_store = vector_store
        self.batch_size = batch_size

    def ingest_document(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
        progress: Callable[[str, int], None] | None = None,
        check_control: Callable[[], None] | None = None,
        page_record: Callable[[int, tuple[int, int]], None] | None = None,
    ) -> None:
        path = str(file_path)
        base = metadata or {}
        build = base.get("build_id") or self.loader.content_hash(path)
        if progress:
            progress("rendering", 0)
        with closing(self.loader.iter_batches(path, self.batch_size)) as batches:
            for start, images in batches:
                if check_control:
                    check_control()
                if page_record:
                    for offset, image in enumerate(images):
                        page_record(start + offset, image.size)
                if progress:
                    progress("embedding", start - 1)
                with stage("embedding", pages=len(images)):
                    embeddings = self.embedder.encode_images(images)
                if len(embeddings) != len(images):
                    raise ValueError("Encoder returned an incomplete page batch")
                if check_control:
                    check_control()
                ids = [
                    identity(f"{build}:point:{start + i}") for i in range(len(images))
                ]
                payloads = [
                    {**(metadata or {}), "source": path, "page_number": start + i}
                    for i in range(len(images))
                ]
                if progress:
                    progress("indexing", start - 1)
                with stage("database_upsert", pages=len(images)):
                    self.vector_store.upsert(
                        ids=ids, vectors=embeddings, payloads=payloads
                    )
                if progress:
                    progress("rendering", start + len(images) - 1)
                if check_control:
                    check_control()
