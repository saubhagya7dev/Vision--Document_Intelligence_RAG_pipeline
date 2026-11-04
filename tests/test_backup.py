import json
import zipfile

import pytest
from test_hybrid import close, open_hybrid
from test_phase4_indexes import prepare

from vision_rag.backup import create, restore, signature
from vision_rag.retrieval.engine import HybridRetriever
from vision_rag.retrieval.indexes import RetrievalIndexes
from vision_rag.storage.conversations import Conversations
from vision_rag.storage.findings import Findings

KEY = bytes(range(32))  # Disposable fixture key, never a real archive key.


def test_signed_backup_restores_search_conversations_findings_and_originals(tmp_path):
    lib, vectors, manager, models, job = prepare(tmp_path)
    root = lib.root
    manager.queue()
    lib.process_one()
    c = Conversations(lib.metadata).create("Saved review", [job["document_id"]])
    finding = Findings(lib.metadata).create(
        "Saved finding", "answer", {"answer": "sample"}, saved=True
    )
    (root / ".env").write_text("must-not-be-backed-up")
    archive = tmp_path / "library.zip"
    with pytest.raises(RuntimeError):
        create(root, archive, KEY)
    close(lib, vectors)
    manifest = create(root, archive, KEY)
    assert ".env" not in manifest["entries"]
    assert not any(n.startswith("artifacts/") for n in manifest["entries"])
    target = tmp_path / "restored"
    with pytest.raises(ValueError):
        restore(archive, target, b"x" * 32)
    assert not target.exists()
    restore(archive, target, KEY)
    restored, store, _, _ = open_hybrid(target)
    try:
        restored.retrieval = RetrievalIndexes(restored, models, manager.spec)
        restored.start(False, False)
        hits, _ = HybridRetriever(restored.retrieval).retrieve("ALPHA42")
        assert hits and hits[0]["payload"]["version_id"] == job["version_id"]
        assert restored.source(job["version_id"])[1].is_file()
        assert Conversations(restored.metadata).get(c["id"])["title"] == "Saved review"
        assert (
            Findings(restored.metadata).get(finding["id"])["content_hash"]
            == finding["content_hash"]
        )
    finally:
        close(restored, store)
    with pytest.raises(ValueError):
        restore(archive, target, KEY)


def test_backup_authentication_paths_checksums_and_expansion_are_checked(tmp_path):
    lib, vectors, _, _, _ = prepare(tmp_path)
    root = lib.root
    close(lib, vectors)
    valid = tmp_path / "valid.zip"
    manifest = create(root, valid, KEY)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(valid) as src, zipfile.ZipFile(bad, "w") as dest:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "metadata.sqlite3":
                data = bytes([data[0] ^ 1]) + data[1:]
            dest.writestr(item, data)
    with pytest.raises(ValueError, match="checksum"):
        restore(bad, tmp_path / "bad-target", KEY)
    assert not (tmp_path / "bad-target").exists()
    with pytest.raises(ValueError, match="extraction limits"):
        restore(valid, tmp_path / "limited", KEY, max_bytes=1)
    manifest["entries"]["../escaped"] = {"bytes": 1, "sha256": "0" * 64}
    manifest["signature"] = signature(manifest, KEY)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(valid) as src, zipfile.ZipFile(evil, "w") as dest:
        for item in src.infolist():
            if item.filename != "manifest.json":
                dest.writestr(item, src.read(item))
        dest.writestr("../escaped", b"x")
        dest.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsafe"):
        restore(evil, tmp_path / "unsafe-target", KEY)
    assert not (tmp_path / "escaped").exists()
