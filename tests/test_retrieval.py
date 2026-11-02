from unittest.mock import MagicMock

from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.core.vector_store import BaseVectorStore
from vision_rag.retrieval.retriever import Retriever


def test_retriever():
    # Mock the embedder
    mock_embedder = MagicMock(spec=BaseEmbeddingModel)
    # encode_queries returns a list of embeddings. For one query, a list with one item.
    mock_embedder.encode_queries.return_value = [[0.1, 0.2, 0.3]]

    # Mock the vector store
    mock_vector_store = MagicMock(spec=BaseVectorStore)
    expected_results = [
        {"id": "doc1", "score": 0.95, "payload": {"page_number": 1}},
        {"id": "doc2", "score": 0.82, "payload": {"page_number": 2}},
    ]
    mock_vector_store.search.return_value = expected_results

    # Initialize the Retriever
    retriever = Retriever(embedder=mock_embedder, vector_store=mock_vector_store)

    # Perform retrieval
    query = "Find the revenue table"
    results = retriever.retrieve(query, top_k=2)

    # Assertions
    mock_embedder.encode_queries.assert_called_once_with([query])
    mock_vector_store.search.assert_called_once_with(
        query_vector=[0.1, 0.2, 0.3], limit=2
    )
    assert results == expected_results


def test_retriever_empty_query():
    mock_embedder = MagicMock(spec=BaseEmbeddingModel)
    mock_embedder.encode_queries.return_value = []

    mock_vector_store = MagicMock(spec=BaseVectorStore)

    retriever = Retriever(embedder=mock_embedder, vector_store=mock_vector_store)

    results = retriever.retrieve("", top_k=5)

    mock_embedder.encode_queries.assert_called_once_with([""])
    mock_vector_store.search.assert_not_called()
    assert results == []
