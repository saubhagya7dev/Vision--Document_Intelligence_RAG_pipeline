from typing import Any, Callable, Dict, List

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.core.vector_store import BaseVectorStore
from vision_rag.telemetry import stage


class Retriever:
    """Handles the retrieval of relevant document pages for a given query."""

    def __init__(
        self,
        embedder: BaseEmbeddingModel,
        vector_store: BaseVectorStore,
        ready_builds: Callable[[], list[str]] | None = None,
        workspace: str | None = None,
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
        # Encode the text query into a vector (or multi-vector)
        with stage("query_embedding"):
            query_embeddings = self.embedder.encode_queries([query])
        if not query_embeddings:
            return []

        # The encode_queries returns a list of embeddings (one per query).
        # We only passed one query, so we take the first element.
        query_vector = query_embeddings[0]

        # Search the vector store
        with stage("candidate_retrieval"):
            if self.ready_builds is not None:
                results = self.vector_store.search(
                    query_vector=query_vector,
                    limit=top_k,
                    build_ids=builds,
                    workspace=self.workspace,
                )
            else:
                results = self.vector_store.search(
                    query_vector=query_vector, limit=top_k
                )

        return results
