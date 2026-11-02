import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pytest
from test_hybrid import close, open_hybrid

from scripts.phase3_fixtures import create_pdf
from vision_rag.storage.metadata import Conflict


def test_cache_clear_preserves_originals_indexes_and_text(tmp_path):
    path = create_pdf(tmp_path / "fixture.pdf", ("table",))
    lib, store, _, _ = open_hybrid(tmp_path / "library")
    try:
        job = lib.upload(io.BytesIO(path.read_bytes()), "report.pdf")
        lib.process_one()
        assert list(lib.path("artifacts").rglob("*.png"))
        lib.clear_page_cache()
        assert not lib.path("artifacts").exists()
        assert lib.ready_builds() == [job["build_id"]]
        assert store.count_build(job["build_id"]) == 1
        assert lib.processing.search("ALPHA42", "profile", 3)
        _, original = lib.source(job["version_id"])
        with lib.loader.load_page(original, 1) as preview:
            assert preview.width > 0
        assert list(lib.path("artifacts").rglob("*.png"))
    finally:
        close(lib, store)


def test_reset_removes_library_and_legacy_data_without_resurrection(tmp_path):
    root = tmp_path / "library"
    path = create_pdf(tmp_path / "fixture.pdf", ("table",))
    lib, store, _, _ = open_hybrid(root)
    lib.upload(io.BytesIO(path.read_bytes()), "report.pdf")
    lib.process_one()
    (root / "legacy.pdf").write_bytes(path.read_bytes())
    (root / "old.partial.upload").write_bytes(b"partial")
    (root / "unrelated.txt").write_text("preserve unknown files")
    lib.reset()
    assert lib.documents() == [] and lib.ready_builds() == []
    assert not lib.reset_pending()
    for table in (
        "jobs",
        "versions",
        "pages",
        "page_tasks",
        "text_chunks",
        "chunk_search",
    ):
        assert lib.metadata.rows("SELECT * FROM " + table) == []
    assert store.get_collection_info()["points_count"] == 0
    assert not (root / "legacy.pdf").exists()
    assert not (root / "old.partial.upload").exists()
    assert (root / "unrelated.txt").exists()
    close(lib, store)
    lib, store, _, _ = open_hybrid(root)
    try:
        lib.start(False, True)
        assert lib.documents() == []
        job = lib.upload(io.BytesIO(path.read_bytes()), "report.pdf")
        lib.process_one()
        assert lib.metadata.job(job["id"])["state"] == "ready"
    finally:
        close(lib, store)


def test_failed_reset_stays_hidden_and_recovers_on_restart(tmp_path):
    root = tmp_path / "library"
    source = create_pdf(tmp_path / "fixture.pdf", ("table",))
    lib, store, _, _ = open_hybrid(root)
    job = lib.upload(io.BytesIO(source.read_bytes()), "report.pdf")
    lib.process_one()
    clear = store.clear_collection

    def fail_after_vector_cleanup():
        clear()
        raise OSError("Simulated interruption")

    store.clear_collection = fail_after_vector_cleanup
    with pytest.raises(OSError):
        lib.reset()
    assert lib.reset_pending() and lib.ready_builds() == []
    with pytest.raises(Conflict):
        lib.source(job["version_id"])
    with pytest.raises(Conflict):
        lib.upload(io.BytesIO(source.read_bytes()), "another.pdf")
    close(lib, store)
    lib, store, _, _ = open_hybrid(root)
    try:
        lib.start(False, True)
        assert not lib.reset_pending() and lib.documents() == []
        assert store.get_collection_info()["points_count"] == 0
    finally:
        close(lib, store)


def test_reset_waits_for_running_inference_without_deadlock(tmp_path):
    path = create_pdf(tmp_path / "fixture.pdf", ("table",))
    lib, store, encoder, _ = open_hybrid(tmp_path / "library")
    started, finish = Event(), Event()

    def encode(images):
        started.set()
        assert finish.wait(5)
        return [[1.0, 0.0]]

    encoder.encode_images.side_effect = encode
    try:
        lib.upload(io.BytesIO(path.read_bytes()), "report.pdf")
        with ThreadPoolExecutor(2) as pool:
            ingestion = pool.submit(lib.process_one)
            assert started.wait(5)
            reset = pool.submit(lib.reset)
            assert lib.maintenance_requested.wait(5)
            finish.set()
            assert ingestion.result(timeout=5)
            reset.result(timeout=5)
        assert (
            lib.documents() == [] and store.get_collection_info()["points_count"] == 0
        )
    finally:
        finish.set()
        close(lib, store)


def test_reset_rejects_other_workspaces_before_changes(tmp_path):
    lib, store, _, _ = open_hybrid(tmp_path / "library")
    try:
        with lib.metadata.connection(True) as db:
            db.execute(
                "INSERT INTO documents(id,workspace,filename,name_key,created_at) "
                "VALUES ('other','other','x.pdf','x.pdf','now')"
            )
        lib.store.clear_collection = MagicMock(side_effect=AssertionError)
        with pytest.raises(Conflict, match="one workspace"):
            lib.reset()
        assert not lib.reset_pending()
        lib.store.clear_collection.assert_not_called()
    finally:
        close(lib, store)
