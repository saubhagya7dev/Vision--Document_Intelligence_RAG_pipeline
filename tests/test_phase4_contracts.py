import io
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from test_hybrid import close
from test_phase4_indexes import prepare

from scripts.phase4_corpus import FAMILIES
from vision_rag.generate.grounding import GroundedSynthesizer
from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel
from vision_rag.retrieval.engine import HybridRetriever
from vision_rag.retrieval.router import CostRouter, features


def test_multivectors_remove_padding_not_valid_augmentation_tokens():
    import torch

    class Batch(dict):
        def to(self, device):
            return self

    batch = Batch(
        input_ids=torch.tensor([[2, 9, 0, 0]]),
        attention_mask=torch.tensor([[1, 1, 1, 0]]),
    )
    encoder = object.__new__(ColPaliEmbeddingModel)
    encoder.device = "cpu"
    encoder._lock = threading.Lock()
    encoder.processor = SimpleNamespace(process_queries=lambda _: batch)
    encoder.model = lambda **kw: torch.tensor(
        [[[1.0, 0.0], [0.0, 0.0], [0.0, 1.0], [0.5, 0.5]]]
    )
    assert encoder.encode_multivectors(["question"], False) == [
        [[1.0, 0.0], [0.0, 1.0]]
    ]


def test_router_coefficients_roundtrip_and_disjoint_families(tmp_path):
    train = {f[1] for f in FAMILIES if f[0] == "train"}
    test = {f[1] for f in FAMILIES if f[0] == "test"}
    assert not train.intersection(test)
    samples = [
        {"query": "Read scanned registration", "documents": 1, "label": 1}
        for _ in range(10)
    ]
    samples += [
        {"query": "What is revenue?", "documents": 1, "label": 0} for _ in range(10)
    ]
    router = CostRouter.train(samples, "profile")
    assert router.choose("Read scanned registration", 1) == "visual"
    path = tmp_path / "router.json"
    router.save(path)
    loaded = CostRouter.load(path)
    assert (
        loaded.profile == "profile" and loaded.choose("What is revenue?", 1) == "text"
    )
    assert len(features("Compare AX42 with VX31", 2)) == 8
    with pytest.raises(ValueError):
        CostRouter(np.full((8, 4), np.nan))


def test_missing_vectors_trigger_recovery_rebuild(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        manager.queue()
        lib.process_one()
        old = manager.active()
        manager.store(old).remove_document(job["document_id"])
        manager.recover()
        assert manager.row(old["id"])["state"] == "failed"
        lib.process_one()
        assert manager.active()["id"] != old["id"]
        assert manager.eligible(manager.active())["text"]
    finally:
        close(lib, store)


def test_comparison_coverage_and_verifier_escalation(tmp_path):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        original = lib.source(job["version_id"])[1]
        other = lib.upload(
            io.BytesIO(original.read_bytes() + b"\n% annex"), "annex.pdf"
        )
        lib.process_one()
        manager.queue()
        lib.process_one()
        retriever = HybridRetriever(manager, char_budget=120)
        documents = [job["document_id"], other["document_id"]]
        hits, info = retriever.retrieve("ALPHA42", 2, documents)
        assert {h["payload"]["document_id"] for h in hits} == set(documents)
        assert all(h["payload"]["text"] for h in hits)
        provider = MagicMock()
        provider.generate_grounded.side_effect = lambda q, evidence, images: {
            "status": "supported",
            "claims": [{"text": "120 units", "citations": [evidence[0]["id"]]}],
        }
        synth = GroundedSynthesizer(retriever, provider, lib.loader, lib.source)
        assert (
            synth.query("Compare reports", 2, documents)["grounding_status"]
            == "insufficient"
        )
        provider.generate_grounded.side_effect = [
            ValueError("malformed JSON"),
            {
                "status": "supported",
                "claims": [
                    {
                        "text": "Revenue is 120 units.",
                        "citations": [hits[0]["evidence_id"]],
                    }
                ],
            },
        ]
        # An invalid provider response is rejected; a subsequent tier can recover.
        result = synth.query("ALPHA42", 2)
        assert result["provider_calls"] == 2
    finally:
        close(lib, store)


def test_failed_model_switch_can_reload_previous_profile(monkeypatch):
    from vision_rag.models import retrieval_models

    class Text:
        dimensions = 3

        def __init__(self, name, revision):
            if revision == "bad":
                raise RuntimeError("Missing model")
            self.closed = False

        def close(self):
            self.closed = True

        def encode(self, texts, query):
            assert not self.closed
            return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(retrieval_models, "TextEmbeddingModel", Text)
    models = retrieval_models.RetrievalModels()
    good = {"text_model": "fake", "text_revision": "good", "text_dimensions": 3}
    assert models.encode_text(good, ["text"])
    with pytest.raises(RuntimeError):
        models.encode_text({**good, "text_revision": "bad"}, ["text"])
    assert models.encode_text(good, ["text"])
    models.close()


@pytest.mark.parametrize("action", ["delete", "reset"])
def test_cleanup_removes_phase4_data_when_feature_disabled(tmp_path, action):
    lib, store, manager, models, job = prepare(tmp_path)
    try:
        manager.queue()
        lib.process_one()
        active = manager.active()
        vectors = manager.store(active)
        assert vectors.count("text") > 0
        lib.retrieval = None
        if action == "delete":
            lib.delete(job["document_id"])
            lib.process_one()
            assert vectors.count("text") == vectors.count("visual") == 0
        else:
            lib.reset()
            collections = {c.name for c in store.client.get_collections().collections}
            assert vectors.text not in collections and vectors.visual not in collections
        assert lib.metadata.rows("SELECT * FROM retrieval_items") == []
        assert lib.metadata.rows("SELECT * FROM retrieval_search") == []
    finally:
        close(lib, store)
