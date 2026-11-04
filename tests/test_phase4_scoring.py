import numpy as np
import pytest

from vision_rag.retrieval.scoring import centroid, fuse, maxsim
from vision_rag.storage.metadata import identity
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore
from vision_rag.vector_stores.retrieval_store import RetrievalStore


def test_exact_maxsim_preserves_negative_maxima_and_dimensions():
    assert maxsim([[1, 0], [0, 1]], [[-1, -2], [-3, -1]]) == -2
    with pytest.raises(ValueError):
        maxsim([[1, 0]], [[1, 0, 1]])
    with pytest.raises(ValueError):
        maxsim([[float("nan"), 0]], [[1, 0]])
    assert np.linalg.norm(centroid([[1, 0], [0, 1]])) == pytest.approx(1)


def test_fusion_uses_ranks_and_deduplicates_channels():
    a = {"id": "a", "score": 1000}
    b = {"id": "b", "score": -1000}
    assert fuse([[a, b], [b]], "rrf")[0]["id"] == "b"
    assert len(fuse([[a, a], [a]], "borda")) == 1


def test_qdrant_maxsim_matches_exact_reference_and_survives_restart(tmp_path):
    base = QdrantVectorStore(path=tmp_path / "qdrant", vector_size=2)
    store = RetrievalStore(base, "revision-one", 3, 2)
    store.create()
    docs = [[[1.0, 0.0], [0.0, 1.0]], [[-1.0, 0.0], [0.0, -1.0]]]
    ids = [identity("first"), identity("second")]
    query = [[1.0, 0.0], [0.0, 1.0]]
    for key, doc in zip(ids, docs):
        store.put_visual(key, doc, {"document_id": key})
    found = store.search(query, ids, 2, "visual")
    assert [f["score"] for f in found] == pytest.approx(
        [maxsim(query, d) for d in docs]
    )
    assert len(store.search(query, [ids[1]], 2, "visual")) == 1
    assert store.search(query, [], 2, "visual") == []
    reranked = store.search(query, ids, 2, "visual", True, 2)
    assert [f["id"] for f in reranked] == [f["id"] for f in found]
    base.client.close()
    base = QdrantVectorStore(path=tmp_path / "qdrant", vector_size=2)
    try:
        store = RetrievalStore(base, "revision-one", 3, 2)
        assert store.count("visual") == 2
        records = base.client.retrieve(store.visual, [ids[0]], with_vectors=True)
        assert maxsim(query, records[0].vector["tokens"]) == pytest.approx(2)
    finally:
        base.client.close()
