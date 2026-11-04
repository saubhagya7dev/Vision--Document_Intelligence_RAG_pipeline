import io
from unittest.mock import MagicMock

import pytest
from test_hybrid import close, open_hybrid

from scripts.phase3_fixtures import create_pdf
from vision_rag.generate.grounding import (
    GroundedSynthesizer,
    followup_query,
    validate_answer,
)
from vision_rag.retrieval.engine import HybridRetriever
from vision_rag.retrieval.indexes import RetrievalIndexes
from vision_rag.storage.metadata import Conflict


class FakeModels:
    def __init__(self):
        self.fail = False

    def split_text(self, spec, text):
        return [text]

    def encode_text(self, spec, texts, query=False):
        if self.fail:
            raise RuntimeError("Simulated encoding failure")
        output = []
        for text in texts:
            vector = [0.0] * spec["text_dimensions"]
            vector[0 if "ALPHA42" in text else 1] = 1.0
            output.append(vector)
        return output

    def encode_visual(self, spec, items, images, multivector=True):
        vector = [0.0] * spec["visual_dimensions"]
        vector[0] = 1.0
        return [[vector] if multivector else vector for _ in items]


def prepare(tmp_path):
    lib, store, _, _ = open_hybrid(tmp_path / "library")
    path = create_pdf(tmp_path / "fixture.pdf", ("text", "table"))
    job = lib.upload(io.BytesIO(path.read_bytes()), "report.pdf")
    lib.process_one()
    spec = {
        "text_dimensions": 3,
        "visual_dimensions": 2,
        "text_model": "fake",
        "text_revision": "one",
    }
    models = FakeModels()
    manager = RetrievalIndexes(lib, models, spec)
    lib.retrieval = manager
    return lib, store, manager, models, job


def test_staged_index_activation_rollback_and_failure_keep_active(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        first = manager.queue()
        lib.process_one()
        assert manager.active()["id"] == first["id"]
        assert manager.store(manager.row(first["id"])).count("text") == 2
        second = manager.queue(False)
        lib.process_one()
        assert manager.row(second["id"])["state"] == "ready"
        assert manager.active()["id"] == first["id"]
        manager.activate(second["id"])
        manager.activate(first["id"])
        assert manager.active()["id"] == first["id"]
        models.fail = True
        third = manager.queue()
        lib.process_one()
        assert manager.row(third["id"])["state"] == "failed"
        assert manager.active()["id"] == first["id"]
        assert manager.eligible(manager.active())["text"]
    finally:
        close(lib, store)


def test_overrides_hide_stale_page_items_and_delete_removes_all_indexes(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        manager.queue()
        lib.process_one()
        old = manager.active()
        assert len(manager.eligible(old)["text"]) == 2
        task = lib.processing.enqueue(job["build_id"], 1, "text")
        assert len(manager.eligible(old)["text"]) == 1
        lib.process_one()
        assert lib.processing.task(task["id"])["state"] == "ready"
        assert len(manager.eligible(old)["text"]) == 1
        with pytest.raises(Conflict):
            manager.activate(old["id"])
        lib.process_one()
        assert len(manager.eligible(manager.active())["text"]) == 2
        lib.delete(job["document_id"])
        assert manager.eligible(manager.active()) == {"text": [], "visual": []}
        lib.process_one()
        for row in manager.revisions():
            if row["state"] == "ready":
                assert manager.store(row).count("text") == 0
        assert lib.metadata.rows("SELECT * FROM retrieval_search") == []
    finally:
        close(lib, store)


def test_restart_rebuilds_partial_index_and_reset_cleans_every_collection(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    queued = manager.queue()
    with lib.metadata.connection(True) as db:
        db.execute(
            "UPDATE retrieval_indexes SET state='building' WHERE id=?", (queued["id"],)
        )
    close(lib, store)
    lib, store, _, _ = open_hybrid(tmp_path / "library")
    manager = RetrievalIndexes(
        lib,
        models,
        {
            "text_dimensions": 3,
            "visual_dimensions": 2,
            "text_model": "fake",
            "text_revision": "one",
        },
    )
    lib.retrieval = manager
    try:
        lib.start(False, False)
        lib.process_one()
        assert manager.active()["id"] == queued["id"]
        lib.reset()
        assert manager.active() is None and manager.revisions() == []
        assert lib.metadata.rows("SELECT * FROM retrieval_items") == []
        assert lib.metadata.rows("SELECT * FROM retrieval_search") == []
    finally:
        close(lib, store)


def test_scoped_hybrid_results_budget_and_grounding_reject_unknown_ids(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        manager.queue()
        lib.process_one()
        retriever = HybridRetriever(manager, char_budget=80)
        hits, info = retriever.retrieve("ALPHA42", 2, [job["document_id"]])
        assert len(hits) == 2
        assert sum(len(h["payload"]["text"]) for h in hits) <= 80
        assert len({h["evidence_id"] for h in hits}) == 2
        assert retriever.retrieve("ALPHA42", 2, [])[0] == []
        assert (
            retriever.retrieve("ALPHA42", 2, [job["document_id"]], (2, 2))[0][0][
                "payload"
            ]["page_number"]
            == 2
        )
        provider = MagicMock()
        provider.generate_grounded.return_value = {
            "status": "supported",
            "claims": [{"text": "Invented", "citations": ["unknown"]}],
        }
        synth = GroundedSynthesizer(retriever, provider, lib.loader, lib.source)
        result = synth.query("ALPHA42", tier="hybrid")
        assert result["grounding_status"] == "insufficient" and result["sources"] == []
        provider.generate_grounded.side_effect = lambda q, evidence, images: {
            "status": "supported",
            "claims": [
                {"text": "Revenue is 120 units.", "citations": [evidence[0]["id"]]}
            ],
        }
        result = synth.query("ALPHA42", tier="hybrid")
        assert result["grounding_status"] == "supported"
        assert result["claims"][0]["citations"] == [result["sources"][0]["evidence_id"]]
    finally:
        close(lib, store)


def test_reference_contract_and_followup_preserve_questions():
    assert (
        followup_query("What about the annex?", "What is revenue?")
        != "What about the annex?"
    )
    assert followup_query("What is revenue?", None) == "What is revenue?"
    with pytest.raises(ValueError):
        validate_answer({"status": "supported", "claims": []}, {"E1"})
    with pytest.raises(ValueError):
        validate_answer(
            {"status": "supported", "claims": [{"text": "x", "citations": ["E2"]}]},
            {"E1"},
        )


def test_model_profile_migration_and_rollback_keep_source_versions(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        manager.queue()
        lib.process_one()
        old = manager.active()
        lib.profile = "changed-baseline-profile"
        new = RetrievalIndexes(lib, models, {**manager.spec, "text_revision": "two"})
        lib.retrieval = new
        assert new.source_builds() == [job["build_id"]]
        new.queue()
        lib.process_one()
        assert new.active()["profile"] != old["profile"]
        new.activate(old["id"])
        assert new.active()["profile"] == old["profile"]
        assert HybridRetriever(new).retrieve("ALPHA42")[0]
        source = lib.source(job["version_id"])[1]
        duplicate = lib.upload(io.BytesIO(source.read_bytes()), "same.pdf")
        assert (
            duplicate["deduplicated"] and duplicate["version_id"] == job["version_id"]
        )
        assert lib.documents()[0]["page_count"] == 2
    finally:
        close(lib, store)
