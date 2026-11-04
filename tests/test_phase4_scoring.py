import numpy as np
import pytest

from vision_rag.retrieval.scoring import centroid, fuse, maxsim


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
