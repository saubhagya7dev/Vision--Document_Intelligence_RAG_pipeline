from typing import Any, Callable, Dict, List

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.core.vector_store import BaseVectorStore
from vision_rag.telemetry import stage


class Retriever:
    """Handles the retrieval of relevant document pages for a given query."""

    def __init__(
        self,
        embedder: BaseEmbeddingModel | None,
        vector_store: BaseVectorStore,
        ready_builds: Callable[[], list[str]] | None = None,
        workspace: str | None = None,
        lexical_search: Callable[[str, int], list[dict[str, Any]]] | None = None,
        hidden_points: Callable[[], list[str]] | None = None,
        embedding_factory: Callable[[], BaseEmbeddingModel] | None = None,
        has_visual: Callable[[], bool] | None = None,
    ):
        """Initialize the retriever.

        Args:
            embedder: Component to encode text queries into embeddings.
            vector_store: Component to search for similar embeddings.
        """
        self.embedder = embedder
        self.vector_store = vector_store
        self.ready_builds = ready_builds
        self.workspace = workspace
        self.lexical_search, self.hidden_points = lexical_search, hidden_points
        self.embedding_factory, self.has_visual = embedding_factory, has_visual

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the most relevant document pages for a query.

        Args:
            query: The user's text query.
            top_k: Number of results to retrieve.

        Returns:
            List of dictionaries containing matched documents (id, score, payload).
        """

        builds = self.ready_builds() if self.ready_builds else None
        if builds == []:
            return []
        lexical = self.lexical_search(query, top_k) if self.lexical_search else []
        if self.has_visual is not None and not self.has_visual():
            return lexical
        # Encode the text query into a vector (or multi-vector)
        with stage("query_embedding"):
            embedder = self.embedder
            if embedder is None and self.embedding_factory is not None:
                embedder = self.embedding_factory()
            if embedder is None:
                raise RuntimeError("Visual query encoder is unavailable")
            query_embeddings = embedder.encode_queries([query])
        if not query_embeddings:
            return []

        # The encode_queries returns a list of embeddings (one per query).
        # We only passed one query, so we take the first element.
        query_vector = query_embeddings[0]

        # Search the vector store
        with stage("candidate_retrieval"):
            if self.ready_builds is not None:
                kwargs: dict[str, Any] = {}
                if self.hidden_points is not None:
                    kwargs["exclude_ids"] = self.hidden_points()
                results = self.vector_store.search(
                    query_vector=query_vector,
                    limit=top_k,
                    build_ids=builds,
                    workspace=self.workspace,
                    **kwargs,
                )
            else:
                results = self.vector_store.search(
                    query_vector=query_vector, limit=top_k
                )

        if not lexical:
            return results
        # Transitional discovery bridge: alternate ranks, never compare scores
        # across channels. Evaluated fusion and dense text retrieval are Phase 4.
        combined: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for index in range(max(len(lexical), len(results))):
            for channel in (lexical, results):
                if index < len(channel):
                    hit = channel[index]
                    payload = hit.get("payload", {})
                    key = (
                        payload.get("version_id", hit["id"]),
                        payload.get("page_number"),
                    )
                    if key not in seen:
                        combined.append(hit)
                        seen.add(key)
        return combined[:top_k]
