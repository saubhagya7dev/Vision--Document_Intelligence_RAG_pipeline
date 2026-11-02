from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from vision_rag.storage.metadata import Conflict, Metadata


def register(repo, name="report.pdf", digest="hash-a", replace=None):
    version = str(uuid4())
    return repo.register(
        filename=name,
        content_hash=digest,
        storage_key=f"originals/{version}.pdf",
        size=100,
        pages=2,
        profile="pooled-v1",
        version_id=version,
        replace_document=replace,
    )


def publish(repo, job):
    repo.progress(job["id"], "indexing", 2)
    repo.finish(job["id"], "ready")


def test_metadata_survives_reopen_and_deduplicates(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    job, duplicate = register(Metadata(path))
    assert not duplicate
    reopened = Metadata(path)
    same, duplicate = register(reopened, "renamed.pdf")
    assert duplicate and same["id"] == job["id"]
    assert reopened.version(job["version_id"])["page_count"] == 2


def test_concurrent_identical_uploads_have_one_job(tmp_path):
    repo = Metadata(tmp_path / "metadata.sqlite3")
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: register(repo), range(8)))
    assert len({job[0]["id"] for job in jobs}) == 1
    assert sum(not duplicate for _, duplicate in jobs) == 1


def test_filename_conflict_requires_explicit_version(tmp_path):
    repo = Metadata(tmp_path / "metadata.sqlite3")
    first, _ = register(repo)
    publish(repo, first)
    with pytest.raises(Conflict):
        register(repo, digest="changed")
    replacement, _ = register(repo, digest="changed", replace=first["document_id"])
    assert repo.ready_builds("pooled-v1") == [first["build_id"]]
    repo.finish(replacement["id"], "failed", "test failure")
    assert (
        repo.document(first["document_id"])["active_version_id"] == first["version_id"]
    )
    repo.retry(replacement["id"])
    publish(repo, replacement)
    assert repo.ready_builds("pooled-v1") == [replacement["build_id"]]


def test_partial_cancelled_and_deleted_builds_are_hidden(tmp_path):
    repo = Metadata(tmp_path / "metadata.sqlite3")
    job, _ = register(repo)
    assert repo.ready_builds("pooled-v1") == []
    with pytest.raises(Conflict, match="incomplete"):
        repo.finish(job["id"], "ready")
    repo.cancel(job["id"])
    repo.progress(job["id"], "indexing", 2)
    with pytest.raises(Conflict, match="cancelled"):
        repo.finish(job["id"], "ready")
    repo.finish(job["id"], "cancelled")
    repo.retry(job["id"])
    publish(repo, job)
    deletion = repo.tombstone(job["document_id"])
    assert deletion["kind"] == "delete"
    assert repo.ready_builds("pooled-v1") == []


def test_workspace_boundaries_and_restart_recovery(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    repo = Metadata(path, "one")
    job, _ = register(repo)
    repo.claim()
    repo.progress(job["id"], "embedding", 0)
    Metadata(path, "two").recover()
    assert repo.job(job["id"])["state"] == "embedding"
    repo.recover()
    assert repo.job(job["id"])["state"] == "uploaded"
    with pytest.raises(KeyError):
        Metadata(path, "two").job(job["id"])


def test_older_retry_does_not_roll_back_a_newer_active_version(tmp_path):
    repo = Metadata(tmp_path / "metadata.sqlite3")
    first, _ = register(repo)
    repo.finish(first["id"], "failed")
    newer, _ = register(repo, digest="new", replace=first["document_id"])
    publish(repo, newer)
    repo.retry(first["id"])
    publish(repo, first)
    assert repo.ready_builds("pooled-v1") == [newer["build_id"]]
