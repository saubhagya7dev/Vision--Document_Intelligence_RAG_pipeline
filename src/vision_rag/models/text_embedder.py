"""Pinned English BGE baseline: CLS pooling, normalized vectors, CPU by default."""

import threading
from typing import Any


class TextEmbeddingModel:
    def __init__(self, model: str, revision: str, max_tokens: int = 512) -> None:
        from transformers import AutoModel, AutoTokenizer

        self.tokenizer: Any = AutoTokenizer.from_pretrained(model, revision=revision)
        self.model: Any = (
            AutoModel.from_pretrained(model, revision=revision).to("cpu").eval()
        )
        self.dimensions = int(self.model.config.hidden_size)
        self.max_tokens = min(
            max_tokens, int(self.model.config.max_position_embeddings)
        )
        self.lock = threading.Lock()

    def encode(self, texts: list[str], query: bool = False) -> list[list[float]]:
        import torch

        output = []
        with self.lock, torch.inference_mode():
            for start in range(0, len(texts), 16):
                values = texts[start : start + 16]
                if query:
                    values = [
                        "Represent this sentence for searching relevant passages: " + t
                        for t in values
                    ]
                encoded = self.tokenizer(
                    values, padding=True, truncation=False, return_tensors=None
                )
                if any(len(ids) > self.max_tokens for ids in encoded["input_ids"]):
                    raise ValueError(
                        "Text exceeds encoder token budget; split before indexing"
                    )
                batch = self.tokenizer(
                    values, padding=True, return_tensors="pt", truncation=False
                )
                vectors = self.model(**batch).last_hidden_state[:, 0]
                vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
                output.extend(vectors.float().tolist())
        return output

    def split(self, text: str) -> list[str]:
        # Tokenize the whole extraction without truncation, then bounded windows.
        ids = self.tokenizer.encode(text, add_special_tokens=False)
        size = self.max_tokens - self.tokenizer.num_special_tokens_to_add(pair=False)
        if size < 16:
            raise ValueError("Encoder context window is too small")
        return [
            self.tokenizer.decode(ids[i : i + size], skip_special_tokens=True)
            for i in range(0, len(ids), max(1, size - 32))
        ] or [""]

    def close(self) -> None:
        self.model = None
