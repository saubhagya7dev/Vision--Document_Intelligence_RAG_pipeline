from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseVectorStore(ABC):
    """Abstract base class for vector stores."""

    @abstractmethod
    def upsert(
        self,
        ids: List[str],
        vectors: List[Any],
        payloads: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Upsert vectors and their metadata into the store.

        Args:
            ids: List of unique identifiers.
            vectors: List of embeddings.
            payloads: Optional list of metadata dictionaries.
        """
        pass

    @abstractmethod
    def search(
        self,
        query_vector: Any,
        limit: int = 5,
        *,
        build_ids: list[str] | None = None,
        workspace: str | None = None,
        exclude_ids: list[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Search for the most similar vectors.

        Args:
            query_vector: The query embedding.
            limit: Number of results to return.

        Returns:
            List of dictionaries containing matching documents (id, score, payload).
        """
        pass

    @abstractmethod
    def get_collection_info(self) -> Dict[str, Any]:
        """Get collection statistics.

        Returns:
            Dictionary containing collection metadata (e.g., vector count, status).
        """
        pass

    @abstractmethod
    def delete_by_payload_filter(self, key: str, value: Any) -> None:
        """Delete all vectors matching a payload field condition.

        Args:
            key: The payload field name to filter on.
            value: The value to match against.
        """
        pass
