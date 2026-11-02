import io
from unittest.mock import MagicMock

import pypdfium2 as pdfium
import pytest

from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.storage.library import DocumentLibrary
from vision_rag.storage.metadata import Conflict
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore


def pdf_bytes(tmp_path, pages=3):
    path = tmp_path / "fixture-source.pdf"
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=100, height=200)
            page.close()
        pdf.save(str(path))
    return path.read_bytes()


def open_library(root):
    loader = DocumentLoader(dpi=72, cache_dir=root / "artifacts")
    store = QdrantVectorStore(path=root / "qdrant", vector_size=2)
    embedder = MagicMock()
    embedder.encode_images.side_effect = lambda images: [[1.0, 0.0] for _ in images]
    pipeline = IngestionPipeline(loader, embedder, store, batch_size=1)
    lib = DocumentLibrary(root, loader, store, lambda: pipeline, "profile")
    return lib, store, embedder


def close(lib, store):
    lib.close()
    store.client.close()


def test_upload_job_survives_restart_and_publishes_only_on_completion(tmp_path):
    data = pdf_bytes(tmp_path)
    root = tmp_path / "library"
    lib, store, _ = open_library(root)
    job = lib.upload(io.BytesIO(data), "report.pdf")
    assert lib.ready_builds() == []
    assert lib.metadata.job(job["id"])["state"] == "uploaded"
    close(lib, store)
    lib, store, _ = open_library(root)
    try:
        lib.start(worker_enabled=False, import_legacy=False)
        assert lib.process_one()
        assert lib.ready_builds() == [job["build_id"]]
        assert store.count_build(job["build_id"]) == 3
        pages = lib.metadata.rows("SELECT * FROM pages")
        assert len(pages) == 3
        assert all(lib.path(page["image_key"]).exists() for page in pages)
        same = lib.upload(io.BytesIO(data), "another.pdf")
        assert same["deduplicated"] and same["id"] == job["id"]
    finally:
        close(lib, store)


def test_mid_batch_failure_retry_has_no_duplicates(tmp_path):
    lib, store, encoder = open_library(tmp_path / "library")
    try:
        data = pdf_bytes(tmp_path)
        job = lib.upload(io.BytesIO(data), "report.pdf")
        encoder.encode_images.side_effect = [[[1.0, 0.0]], RuntimeError("failure")]
        lib.process_one()
        assert lib.metadata.job(job["id"])["state"] == "failed"
        assert store.count_build(job["build_id"]) == 1
        assert lib.ready_builds() == []
        lib.metadata.retry(job["id"])
        encoder.encode_images.side_effect = lambda images: [[1.0, 0.0] for _ in images]
        lib.process_one()
        assert store.count_build(job["build_id"]) == 3
        assert lib.metadata.job(job["id"])["attempts"] == 2
    finally:
        close(lib, store)


def test_cancel_during_embedding_removes_partial_vectors(tmp_path):
    lib, store, encoder = open_library(tmp_path / "library")
    try:
        job = lib.upload(io.BytesIO(pdf_bytes(tmp_path)), "report.pdf")

        def cancel(images):
            lib.metadata.cancel(job["id"])
            return [[1.0, 0.0]]

        encoder.encode_images.side_effect = cancel
        lib.process_one()
        assert lib.metadata.job(job["id"])["state"] == "cancelled"
        assert store.count_build(job["build_id"]) == 0
        assert lib.source(job["version_id"])[1].exists()
    finally:
        close(lib, store)


def test_delete_hides_immediately_and_cleanup_can_retry(tmp_path, monkeypatch):
    lib, store, _ = open_library(tmp_path / "library")
    try:
        job = lib.upload(io.BytesIO(pdf_bytes(tmp_path)), "report.pdf")
        lib.process_one()
        deletion = lib.delete(job["document_id"])
        assert lib.ready_builds() == []
        assert lib.documents() == []
        with pytest.raises(KeyError):
            lib.source(job["version_id"])
        original_delete = store.delete_by_payload_filter
        monkeypatch.setattr(
            store, "delete_by_payload_filter", MagicMock(side_effect=RuntimeError)
        )
        lib.process_one()
        assert lib.metadata.job(deletion["id"])["state"] == "failed"
        monkeypatch.setattr(store, "delete_by_payload_filter", original_delete)
        lib.metadata.retry(deletion["id"])
        lib.process_one()
        assert store.count_build(job["build_id"]) == 0
        assert not lib.path(
            lib.metadata.version(job["version_id"])["storage_key"]
        ).exists()
        assert lib.metadata.job(deletion["id"])["state"] == "ready"
    finally:
        close(lib, store)


def test_shutdown_interruption_requeues_and_legacy_deletion_does_not_resurrect(
    tmp_path,
):
    root = tmp_path / "library"
    root.mkdir()
    legacy = root / "legacy.pdf"
    legacy.write_bytes(pdf_bytes(tmp_path))
    lib, store, encoder = open_library(root)
    lib.start(worker_enabled=False)
    job = lib.documents()[0]

    def stop(images):
        lib.stop_event.set()
        return [[1.0, 0.0]]

    encoder.encode_images.side_effect = stop
    lib.process_one()
    assert lib.metadata.job(job["job_id"])["state"] == "uploaded"
    close(lib, store)
    lib, store, _ = open_library(root)
    try:
        lib.start(worker_enabled=False)
        lib.process_one()
        lib.delete(job["id"])
        lib.process_one()
        assert legacy.exists()
    finally:
        close(lib, store)
    lib, store, _ = open_library(root)
    try:
        lib.start(worker_enabled=False)
        assert lib.documents() == []
    finally:
        close(lib, store)


def test_missing_or_corrupt_source_and_lost_index_never_remain_ready(tmp_path):
    lib, store, _ = open_library(tmp_path / "library")
    try:
        job = lib.upload(io.BytesIO(pdf_bytes(tmp_path)), "report.pdf")
        lib.process_one()
        store.delete_by_payload_filter("build_id", job["build_id"])
        lib.reconcile()
        assert lib.ready_builds() == []
        assert lib.metadata.job(job["id"])["state"] == "failed"
        version = lib.metadata.version(job["version_id"])
        lib.path(version["storage_key"]).write_bytes(b"changed source")
        with pytest.raises(Conflict):
            lib.source(job["version_id"])
    finally:
        close(lib, store)
