import io
from unittest.mock import MagicMock

import pytest

from scripts.phase3_fixtures import create_pdf
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.ingest.text import Block, chunks, inspect_page, quality
from vision_rag.retrieval.retriever import Retriever
from vision_rag.storage.library import DocumentLibrary
from vision_rag.storage.metadata import Conflict, identity
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore


def open_hybrid(root, ocr=None):
    loader = DocumentLoader(dpi=72, cache_dir=root / "artifacts")
    store = QdrantVectorStore(path=root / "qdrant", vector_size=2)
    encoder = MagicMock()
    encoder.encode_images.side_effect = lambda images: [[1.0, 0.0] for _ in images]
    encoder.encode_queries.return_value = [[1.0, 0.0]]
    factory = MagicMock(return_value=IngestionPipeline(loader, encoder, store, 1))
    library = DocumentLibrary(
        root, loader, store, factory, "profile", hybrid=True, ocr=ocr
    )
    return library, store, encoder, factory


def close(library, store):
    library.close()
    store.client.close()


def test_native_routes_include_vectors_and_ignore_logo(tmp_path):
    path = create_pdf(tmp_path / "fixture.pdf")
    pages = [inspect_page(path, n) for n in range(1, 10)]
    assert [p.visual for p in pages] == [
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
    ]
    assert pages[0].quality == "usable"
    assert pages[0].blocks[0].heading == "Quarterly report"
    assert "vector_graphics_or_table_rules" in pages[2].reasons
    assert pages[3].ocr and pages[3].native_text == ""
    assert pages[4].reasons == ["empty_page"]
    assert pages[6].features["multiple_columns"]
    assert pages[7].rotation == 90
    assert pages[8].quality == "poor"
    assert "ALPHA42" in pages[1].native_text


@pytest.mark.parametrize(
    "value,state",
    [
        ("", "missing"),
        ("short", "uncertain"),
        ("\ufffd" * 80, "poor"),
        ("a" * 80, "poor"),
        ("Revenue for fiscal period was 120 units. " * 8, "usable"),
    ],
)
def test_text_quality(value, state):
    assert quality(value)[0] == state


def test_chunk_bounds_unicode_overlap_and_headings():
    text = "收入利润" * 300 + "LONG_IDENTIFIER_" * 40
    result = chunks([Block(text, (0, 0, 50, 100), heading="Revenue")], 100, 20)
    assert all(0 < c["units"] <= 100 for c in result)
    for before, after in zip(result, result[1:]):
        overlap_chars = before["section_end"] - after["section_start"]
        assert before["text"][-overlap_chars:] == after["text"][:overlap_chars]
    assert result[-1]["section_end"] == len(text)
    assert all(c["heading"] == "Revenue" and c["boxes"] for c in result)
    with pytest.raises(ValueError):
        chunks([], 100, 100)


def test_hybrid_persists_chunks_restarts_and_deduplicates(tmp_path):
    path = create_pdf(
        tmp_path / "fixture.pdf", ("text", "mixed", "table", "scan", "empty", "logo")
    )
    root = tmp_path / "library"
    lib, store, encoder, _ = open_hybrid(root)
    job = lib.upload(io.BytesIO(path.read_bytes()), "report.pdf")
    lib.process_one()
    assert lib.metadata.job(job["id"])["state"] == "ready"
    assert store.count_build(job["build_id"]) == 3
    assert encoder.encode_images.call_count == 3
    pages = lib.processing.pages(job["build_id"])
    assert len(pages) == 6 and pages[1]["data"]["native_text"]
    assert "ocr_disabled_visual_fallback" in pages[3]["data"]["warnings"]
    result = lib.processing.search("ALPHA42", "profile", 10)
    assert {r["payload"]["page_number"] for r in result} == {1, 2, 3, 6}
    close(lib, store)
    lib, store, _, _ = open_hybrid(root)
    try:
        lib.start(False, False)
        assert lib.ready_builds() == [job["build_id"]]
        same = lib.upload(io.BytesIO(path.read_bytes()), "same.pdf")
        assert same["deduplicated"]
        assert lib.processing.search("ALPHA42", "profile", 10)
        lib.delete(job["document_id"])
        assert lib.processing.search("ALPHA42", "profile", 10) == []
        lib.process_one()
        assert not lib.processing.pages(job["build_id"])
        assert not lib.metadata.rows("SELECT * FROM chunk_search")
    finally:
        close(lib, store)


def test_text_only_does_not_load_model_or_render(tmp_path, monkeypatch):
    path = create_pdf(tmp_path / "text.pdf", ("text",))
    lib, store, _, factory = open_hybrid(tmp_path / "library")
    try:
        monkeypatch.setattr(
            lib.loader, "load_page", MagicMock(side_effect=AssertionError)
        )
        job = lib.upload(io.BytesIO(path.read_bytes()), "text.pdf")
        lib.process_one()
        assert lib.metadata.job(job["id"])["state"] == "ready"
        factory.assert_not_called()
        assert store.count_build(job["build_id"]) == 0
    finally:
        close(lib, store)


def test_page_override_isolated_hidden_retry_and_restart(tmp_path):
    path = create_pdf(tmp_path / "text.pdf", ("text", "text"))
    root = tmp_path / "library"
    lib, store, _, _ = open_hybrid(root)
    job = lib.upload(io.BytesIO(path.read_bytes()), "text.pdf")
    lib.process_one()
    task = lib.processing.enqueue(job["build_id"], 1, "visual")
    assert len(lib.processing.search("ALPHA42", "profile", 10)) == 1
    with pytest.raises(Conflict):
        lib.processing.enqueue(job["build_id"], 1, "text")
    close(lib, store)
    lib, store, encoder, _ = open_hybrid(root)
    try:
        lib.start(False, False)
        encoder.encode_images.side_effect = RuntimeError("interrupted model")
        lib.process_one()
        assert lib.processing.task(task["id"])["state"] == "failed"
        assert len(lib.processing.search("ALPHA42", "profile", 10)) == 1
        replacement = lib.processing.enqueue(job["build_id"], 1, "visual")
        encoder.encode_images.side_effect = lambda images: [[1.0, 0.0]]
        lib.process_one()
        assert lib.processing.task(replacement["id"])["state"] == "ready"
        pages = lib.processing.pages(job["build_id"])
        assert pages[0]["revision"] == 2 and pages[1]["revision"] == 1
        assert pages[0]["mode"] == "visual"
        assert store.count_build(job["build_id"]) == 1
        assert len(lib.processing.search("ALPHA42", "profile", 10)) == 2
        lib.processing.enqueue(job["build_id"], 1, "text")
        hidden = lib.processing.hidden_points("profile")
        assert identity(f"{job['build_id']}:point:1") in hidden
        assert store.search([1.0, 0.0], exclude_ids=hidden) == []
        lib.process_one()
        assert store.count_build(job["build_id"]) == 0
    finally:
        close(lib, store)


def test_ocr_retains_native_and_falls_back_on_failure(tmp_path):
    path = create_pdf(tmp_path / "scan.pdf", ("scan",))
    ocr = MagicMock()
    ocr.language = "eng"
    ocr.extract.return_value = [
        Block("Scanned evidence SCAN42 revenue 120 units. " * 4, (0, 0, 100, 100))
    ]
    lib, store, _, _ = open_hybrid(tmp_path / "library", ocr)
    try:
        job = lib.upload(io.BytesIO(path.read_bytes()), "scan.pdf")
        lib.process_one()
        assert lib.processing.search("SCAN42", "profile", 3)
        assert store.count_build(job["build_id"]) == 1
        task = lib.processing.enqueue(job["build_id"], 1, "ocr")
        ocr.extract.side_effect = TimeoutError()
        lib.process_one()
        assert lib.processing.task(task["id"])["state"] == "ready"
        assert (
            "ocr_failed_visual_fallback:TimeoutError"
            in lib.processing.pages(job["build_id"])[0]["data"]["warnings"]
        )
        assert lib.source(job["version_id"])[1].exists()
    finally:
        close(lib, store)


def test_discovery_bridge_keeps_channels_and_deduplicates_pages(tmp_path):
    path = create_pdf(tmp_path / "mixed.pdf", ("text", "table"))
    lib, store, encoder, _ = open_hybrid(tmp_path / "library")
    try:
        lib.upload(io.BytesIO(path.read_bytes()), "mixed.pdf")
        lib.process_one()
        retriever = Retriever(
            encoder,
            store,
            lib.ready_builds,
            lib.workspace,
            lambda q, k: lib.processing.search(q, lib.profile, k),
            lambda: lib.processing.hidden_points(lib.profile),
        )
        results = retriever.retrieve("ALPHA42", 3)
        assert {r["payload"]["page_number"] for r in results} == {1, 2}
        assert results[0]["score"] is None
    finally:
        close(lib, store)


def test_legacy_page_override_keeps_unprocessed_vectors_after_restart(tmp_path):
    path = create_pdf(tmp_path / "legacy.pdf", ("text", "table", "text"))
    root = tmp_path / "library"
    lib, store, _, _ = open_hybrid(root)
    processor = lib.hybrid
    lib.hybrid = None
    job = lib.upload(io.BytesIO(path.read_bytes()), "legacy.pdf")
    lib.process_one()
    assert store.count_build(job["build_id"]) == 3
    lib.hybrid = processor
    lib.processing.enqueue(job["build_id"], 1, "text")
    lib.process_one()
    assert store.count_build(job["build_id"]) == 2
    close(lib, store)
    lib, store, _, _ = open_hybrid(root)
    try:
        lib.start(False, False)
        assert lib.ready_builds() == [job["build_id"]]
        assert lib.processing.expected_vectors(job["build_id"], 3) == 2
    finally:
        close(lib, store)


def test_running_page_task_recovers_and_respects_profile(tmp_path):
    path = create_pdf(tmp_path / "text.pdf", ("text",))
    root = tmp_path / "library"
    lib, store, _, _ = open_hybrid(root)
    job = lib.upload(io.BytesIO(path.read_bytes()), "text.pdf")
    lib.process_one()
    task = lib.processing.enqueue(job["build_id"], 1, "text")
    assert lib.processing.claim("wrong-profile") is None
    assert lib.processing.claim("profile")["id"] == task["id"]
    close(lib, store)
    lib, store, _, _ = open_hybrid(root)
    try:
        lib.start(False, False)
        assert lib.processing.task(task["id"])["state"] == "uploaded"
        lib.process_one()
        assert lib.processing.task(task["id"])["state"] == "ready"
        assert lib.processing.task(task["id"])["attempts"] == 2
    finally:
        close(lib, store)


def test_schema_one_upgrade_preserves_original_records(tmp_path):
    path = create_pdf(tmp_path / "text.pdf", ("text",))
    root = tmp_path / "library"
    lib, store, _, _ = open_hybrid(root)
    job = lib.upload(io.BytesIO(path.read_bytes()), "text.pdf")
    with lib.metadata.connection(True) as db:
        for table in ("page_tasks", "page_processing", "text_chunks", "chunk_search"):
            db.execute("DROP TABLE " + table)
        db.execute("PRAGMA user_version=1")
    close(lib, store)
    lib, store, _, _ = open_hybrid(root)
    try:
        assert lib.metadata.version(job["version_id"])["filename"] == "text.pdf"
        lib.start(False, False)
        lib.process_one()
        assert lib.metadata.job(job["id"])["state"] == "ready"
        assert lib.processing.search("ALPHA42", "profile", 3)
        from vision_rag.storage.metadata import Metadata
        from vision_rag.storage.processing import ProcessingMetadata

        other = ProcessingMetadata(Metadata(root / "metadata.sqlite3", "other"))
        assert other.search("ALPHA42", "profile", 3) == []
        with pytest.raises(KeyError):
            other.enqueue(job["build_id"], 1, "text")
    finally:
        close(lib, store)
