import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.core.vector_store import BaseVectorStore
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.telemetry import stage


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
        self, file_path: str | Path, metadata: dict[str, Any] | None = None
    ) -> None:
        path = str(file_path)
        with closing(self.loader.iter_batches(path, self.batch_size)) as batches:
            for start, images in batches:
                with stage("embedding", pages=len(images)):
                    embeddings = self.embedder.encode_images(images)
                if len(embeddings) != len(images):
                    raise ValueError("Encoder returned an incomplete page batch")
                ids = [str(uuid.uuid4()) for _ in images]
                payloads = [
                    {**(metadata or {}), "source": path, "page_number": start + i}
                    for i in range(len(images))
                ]
                with stage("database_upsert", pages=len(images)):
                    self.vector_store.upsert(
                        ids=ids, vectors=embeddings, payloads=payloads
                    )
