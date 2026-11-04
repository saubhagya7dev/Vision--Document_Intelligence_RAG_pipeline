"""Isolated dense text and original visual-token collections per index revision."""

from typing import Any

from qdrant_client import models as qm

from vision_rag.retrieval.scoring import centroid
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore


class RetrievalStore:
    def __init__(
        self,
        base: QdrantVectorStore,
        index: str,
        text_dimensions: int,
        visual_dimensions: int,
    ) -> None:
        self.base = base
        prefix = "p4_" + index.replace("-", "")
        self.text, self.visual = prefix + "_text", prefix + "_visual"
        self.text_dimensions, self.visual_dimensions = (
            text_dimensions,
            visual_dimensions,
        )

    def create(self) -> None:
        with self.base.lock:
            if not self.base.client.collection_exists(self.text):
                self.base.client.create_collection(
                    self.text,
                    vectors_config=qm.VectorParams(
                        size=self.text_dimensions, distance=qm.Distance.COSINE
                    ),
                )
            if not self.base.client.collection_exists(self.visual):
                self.base.client.create_collection(
                    self.visual,
                    vectors_config={
                        "coarse": qm.VectorParams(
                            size=self.visual_dimensions, distance=qm.Distance.COSINE
                        ),
                        "tokens": qm.VectorParams(
                            size=self.visual_dimensions,
                            distance=qm.Distance.DOT,
                            multivector_config=qm.MultiVectorConfig(
                                comparator=qm.MultiVectorComparator.MAX_SIM
                            ),
                            hnsw_config=qm.HnswConfigDiff(m=0),
                        ),
                    },
                )

    def put_text(
        self, ids: list[str], vectors: list[Any], payloads: list[dict[str, Any]]
    ) -> None:
        if not len(ids) == len(vectors) == len(payloads):
            raise ValueError("Incomplete dense embedding batch")
        if not ids:
            return
        with self.base.lock:
            self.base.client.upsert(
                self.text,
                points=[
                    qm.PointStruct(id=key, vector=vector, payload=payload)
                    for key, vector, payload in zip(ids, vectors, payloads)
                ],
                wait=True,
            )

    def put_visual(self, key: str, tokens: Any, payload: dict[str, Any]) -> None:
        with self.base.lock:
            self.base.client.upsert(
                self.visual,
                points=[
                    qm.PointStruct(
                        id=key,
                        vector={"tokens": tokens, "coarse": centroid(tokens)},
                        payload=payload,
                    )
                ],
                wait=True,
            )

    def search(
        self,
        query: Any,
        ids: list[str],
        limit: int,
        channel: str,
        rerank: bool = False,
        pool: int = 30,
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        collection = self.text if channel == "text" else self.visual
        with self.base.lock:
            allowed: Any = qm.Filter(must=[qm.HasIdCondition(has_id=list(ids))])
            if channel == "visual" and rerank:
                candidates = self.base.client.query_points(
                    collection,
                    query=centroid(query),
                    using="coarse",
                    query_filter=allowed,
                    limit=pool,
                ).points
                if not candidates:
                    return []
                allowed = qm.Filter(
                    must=[qm.HasIdCondition(has_id=[p.id for p in candidates])]
                )
            results = self.base.client.query_points(
                collection,
                query=query,
                using="tokens" if channel == "visual" else None,
                query_filter=allowed,
                limit=limit,
                search_params=None if self.base.local else qm.SearchParams(exact=True),
            ).points
        return [
            {
                "id": str(p.id),
                "score": p.score,
                "payload": {**(p.payload or {}), "channel": channel},
                "score_kind": "maxsim" if channel == "visual" else "dense_cosine",
            }
            for p in results
        ]

    def count(self, channel: str) -> int:
        with self.base.lock:
            return self.base.client.count(
                self.text if channel == "text" else self.visual, exact=True
            ).count

    def remove_document(self, document: str) -> None:
        with self.base.lock:
            for collection in (self.text, self.visual):
                if self.base.client.collection_exists(collection):
                    self.base.client.delete(
                        collection,
                        points_selector=qm.Filter(
                            must=[
                                qm.FieldCondition(
                                    key="document_id",
                                    match=qm.MatchValue(value=document),
                                )
                            ]
                        ),
                        wait=True,
                    )

    def drop(self) -> None:
        with self.base.lock:
            for collection in (self.text, self.visual):
                if self.base.client.collection_exists(collection):
                    self.base.client.delete_collection(collection)
