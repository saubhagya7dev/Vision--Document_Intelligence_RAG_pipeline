"""Hardware selection and bounded inference, without model weights."""

import threading
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from unittest.mock import MagicMock

import pytest
import torch

from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel
from vision_rag.runtime import select_device


def bare_encoder(batch_size=2):
    encoder = ColPaliEmbeddingModel.__new__(ColPaliEmbeddingModel)
    encoder.batch_size = batch_size
    encoder.device = "cpu"
    encoder._lock = threading.Lock()
    return encoder


def test_explicit_cpu_and_unavailable_cuda(monkeypatch):
    assert select_device("cpu") == ("cpu", torch.float32)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA requested"):
        select_device("cuda")
    with pytest.raises(ValueError, match="CPU profile"):
        select_device("cpu", "float16")


def test_encoder_bounds_batches_and_retries_all_items():
    encoder = bare_encoder()
    calls = []

    def encode(items, images):
        calls.append(list(items))
        if len(items) > 1:
            raise torch.OutOfMemoryError("test")
        return [[items[0]]]

    encoder._encode_batch = encode
    assert encoder.encode_images([1, 2, 3]) == [[1], [2], [3]]
    assert calls == [[1, 2], [1], [2], [3]]


def test_single_item_oom_is_actionable():
    encoder = bare_encoder()
    encoder._encode_batch = MagicMock(side_effect=torch.OutOfMemoryError("test"))
    with pytest.raises(RuntimeError, match="single page"):
        encoder.encode_images([1])


def test_inference_is_serialized_and_pooling_is_unchanged():
    encoder = bare_encoder()
    active = 0
    maximum = 0

    def model(**kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        sleep(0.01)
        active -= 1
        return torch.tensor([[[1.0, 0.0], [0.0, 1.0]]])

    encoder.model = model
    encoder.processor = MagicMock()
    encoder.processor.process_queries.return_value.to.return_value = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: encoder.encode_queries(["test"]), range(4)))
    assert results == [[[0.5, 0.5]]] * 4
    assert maximum == 1


@pytest.mark.parametrize("device", ["cuda", "cpu"])
def test_loading_releases_cuda_staging_cache_only_on_cuda(monkeypatch, device):
    from colpali_engine import models

    from vision_rag.models import colpali_embedder

    monkeypatch.setattr(
        colpali_embedder, "select_device", lambda *_: (device, torch.float32)
    )
    monkeypatch.setattr(models.ColPali, "from_pretrained", MagicMock())
    monkeypatch.setattr(models.ColPaliProcessor, "from_pretrained", MagicMock())
    release = MagicMock()
    monkeypatch.setattr(torch.cuda, "empty_cache", release)
    ColPaliEmbeddingModel(device=device)
    assert release.call_count == (1 if device == "cuda" else 0)
