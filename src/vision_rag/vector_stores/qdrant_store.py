from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchAny,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from vision_rag.core.vector_store import BaseVectorStore


class QdrantVectorStore(BaseVectorStore):
    """Implementation of BaseVectorStore using Qdrant.

    This baseline uses pooled vectors. A later phase adds versioned multivectors.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "vision_rag_docs",
        vector_size: int = 128,
        in_memory: bool = False,
        path: str | Path | None = None,
    ):
        """Initialize the Qdrant vector store.

        Args:
            host: Qdrant server host.
            port: Qdrant server port.
            collection_name: Name of the collection to use.
            vector_size: Dimensionality of the vectors (ColPali typically uses 128).
            in_memory: If True, use an in-process Qdrant instance (no Docker required).
                       Data is lost on restart. Ideal for development and testing.
        """
        self.collection_name = collection_name
        self.lock = RLock()

        if path is not None:
            self.client = QdrantClient(path=str(path))
        elif in_memory:
            # In-memory mode: no external server needed
            self.client = QdrantClient(":memory:")
            print(
                "Qdrant running in IN-MEMORY mode (data will not persist on restart)."
            )
        else:
            self.client = QdrantClient(host=host, port=port)
            print(f"Connecting to Qdrant at {host}:{port}...")

        # Ensure collection exists
        try:
            self._ensure_collection(vector_size)
        except BaseException:
            self.client.close()
            raise

    def _ensure_collection(self, vector_size: int) -> None:
        """Create the collection if it doesn't already exist."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            # Keep the historical pooled schema until the retrieval migration.
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            print(f"Created Qdrant collection '{self.collection_name}'.")
        else:
            config = self.client.get_collection(
                self.collection_name
            ).config.params.vectors
            if (
                not isinstance(config, VectorParams)
                or config.size != vector_size
                or config.distance != Distance.COSINE
                or config.multivector_config
            ):
                raise ValueError("Incompatible vector collection; use a new collection")

    def upsert(
        self,
        ids: List[str],
        vectors: List[Any],
        payloads: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Upsert vectors into Qdrant."""
        if payloads is None:
            payloads = [{} for _ in range(len(ids))]
        if not (len(ids) == len(vectors) == len(payloads)):
            raise ValueError("IDs, vectors, and payloads must have equal lengths")

        points = [
            PointStruct(id=id_, vector=vector, payload=payload)
            for id_, vector, payload in zip(ids, vectors, payloads)
        ]

        with self.lock:
            self.client.upsert(
                collection_name=self.collection_name, points=points, wait=True
            )

    def search(
        self,
        query_vector: Any,
        limit: int = 5,
        *,
        build_ids: list[str] | None = None,
        workspace: str | None = None,
        exclude_ids: list[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors in Qdrant."""
        if build_ids == []:
            return []
        conditions: list[Any] = []
        if build_ids is not None:
            conditions.append(
                FieldCondition(key="build_id", match=MatchAny(any=build_ids))
            )
        if workspace is not None:
            conditions.append(
                FieldCondition(key="workspace", match=MatchValue(value=workspace))
            )
        with self.lock:
            search_result = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                query_filter=Filter(
                    must=conditions,
                    must_not=[HasIdCondition(has_id=list(exclude_ids))]
                    if exclude_ids
                    else None,
                )
                if conditions or exclude_ids
                else None,
            )

        results = []
        for scored_point in search_result.points:
            results.append(
                {
                    "id": scored_point.id,
                    "score": scored_point.score,
                    "payload": scored_point.payload,
                }
            )

        return results

    def delete_ids(self, ids: list[str]) -> None:
        with self.lock:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=list(ids)),
                wait=True,
            )

    def get_collection_info(self) -> Dict[str, Any]:
        """Get collection statistics from Qdrant."""
        try:
            with self.lock:
                info = self.client.get_collection(collection_name=self.collection_name)
            return {
                "vectors_count": info.points_count,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception:
            return {"vectors_count": 0, "points_count": 0, "status": "unknown"}

    def delete_by_payload_filter(self, key: str, value: Any) -> None:
        """Delete all vectors matching a payload field condition in Qdrant."""
        with self.lock:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key=key, match=MatchValue(value=value))]
                ),
                wait=True,
            )

    def count_build(self, build_id: str) -> int:
        with self.lock:
            return self.client.count(
                collection_name=self.collection_name,
                exact=True,
                count_filter=Filter(
                    must=[
                        FieldCondition(key="build_id", match=MatchValue(value=build_id))
                    ]
                ),
            ).count
