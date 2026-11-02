from uuid import uuid4

import pytest

from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore


def test_disk_vectors_reopen_and_prefilter_ready_scope(tmp_path):
    path = tmp_path / "qdrant"
    store = QdrantVectorStore(path=path, vector_size=2)
    store.upsert(
        [str(uuid4()) for _ in range(3)],
        [[1.0, 0.0]] * 3,
        [
            {"build_id": "ready", "workspace": "one"},
            {"build_id": "partial", "workspace": "one"},
            {"build_id": "ready", "workspace": "two"},
        ],
    )
    store.client.close()
    reopened = QdrantVectorStore(path=path, vector_size=2)
    try:
        assert reopened.count_build("ready") == 2
        assert reopened.search([1.0, 0.0], build_ids=[]) == []
        hits = reopened.search([1.0, 0.0], build_ids=["ready"], workspace="one")
        assert len(hits) == 1
        reopened.delete_by_payload_filter("build_id", "partial")
        assert reopened.count_build("partial") == 0
    finally:
        reopened.client.close()
    with pytest.raises(ValueError, match="Incompatible"):
        QdrantVectorStore(path=path, vector_size=3)


def test_retry_reuses_point_ids_and_progress_is_real(tmp_path):
    from unittest.mock import MagicMock

    import pypdfium2 as pdfium

    path = tmp_path / "fixture.pdf"
    with pdfium.PdfDocument.new() as pdf:
        page = pdf.new_page(width=100, height=100)
        page.close()
        pdf.save(str(path))
    store = QdrantVectorStore(in_memory=True, vector_size=2)
    embedder = MagicMock()
    embedder.encode_images.return_value = [[1.0, 0.0]]
    pipeline = IngestionPipeline(DocumentLoader(dpi=72), embedder, store)
    progress = []
    try:
        for _ in range(2):
            pipeline.ingest_document(
                path,
                {"build_id": "fixed"},
                progress=lambda state, done: progress.append((state, done)),
            )
        assert store.count_build("fixed") == 1
        assert ("embedding", 0) in progress
        assert progress[-1] == ("rendering", 1)
    finally:
        store.client.close()
