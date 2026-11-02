"""Real PDF/storage regression checks; no model downloads or paid services."""

from unittest.mock import MagicMock, patch

import pypdfium2 as pdfium
import pytest

from vision_rag.generate.synthesizer import RAGSynthesizer
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "report.pdf"
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(5):
            page = pdf.new_page(width=100, height=200)
            page.close()
        pdf.save(str(path))
    return path


def test_page_count_never_renders(pdf_path):
    with patch.object(pdfium.PdfPage, "render", side_effect=AssertionError):
        assert DocumentLoader().page_count(pdf_path) == 5


def test_single_page_cache_and_thumbnail(pdf_path, tmp_path):
    loader = DocumentLoader(dpi=144, cache_dir=tmp_path / "cache")
    with patch.object(
        pdfium.PdfPage, "render", autospec=True, wraps=pdfium.PdfPage.render
    ) as render:
        # Use a spy without changing native return values.
        render.side_effect = lambda page, **kw: original_render(page, **kw)
        with loader.load_page(pdf_path, 3) as image:
            assert image.size == (200, 400)
        with loader.load_page(pdf_path, 3) as image:
            assert image.size == (200, 400)
        assert render.call_count == 1
    with loader.load_page(pdf_path, 3, thumbnail=True) as image:
        assert image.width <= 240 and image.height <= 320
    with pytest.raises(IndexError):
        loader.load_page(pdf_path, 0)
    with pytest.raises(IndexError):
        loader.load_page(pdf_path, 6)


original_render = pdfium.PdfPage.render


def test_cache_changes_when_document_is_replaced(pdf_path, tmp_path):
    loader = DocumentLoader(cache_dir=tmp_path / "cache")
    first = loader.content_hash(pdf_path)
    with pdf_path.open("ab") as stream:
        stream.write(b"\n% revision")
    assert first != loader.content_hash(pdf_path)


def test_ingest_is_bounded_and_keeps_page_numbers(pdf_path):
    embedder, store = MagicMock(), MagicMock()
    sizes = []

    def encode(images):
        sizes.append(len(images))
        return [[1.0, 0.0] for _ in images]

    embedder.encode_images.side_effect = encode
    IngestionPipeline(
        DocumentLoader(dpi=72), embedder, store, batch_size=2
    ).ingest_document(pdf_path)
    assert sizes == [2, 2, 1]
    assert [
        p["page_number"]
        for call in store.upsert.call_args_list
        for p in call.kwargs["payloads"]
    ] == [1, 2, 3, 4, 5]


def test_incomplete_encoder_batch_is_rejected(pdf_path):
    embedder, store = MagicMock(), MagicMock()
    embedder.encode_images.return_value = []
    with pytest.raises(ValueError, match="incomplete"):
        IngestionPipeline(DocumentLoader(dpi=72), embedder, store).ingest_document(
            pdf_path
        )
    store.upsert.assert_not_called()


def test_synthesis_only_loads_selected_pages(pdf_path):
    loader = DocumentLoader(dpi=72)
    retriever, generator = MagicMock(), MagicMock()
    retriever.retrieve.return_value = [
        {"payload": {"source": str(pdf_path), "page_number": 4}}
    ]
    generator.generate.return_value = "answer"
    with patch.object(loader, "load_pdf", side_effect=AssertionError):
        answer, sources = RAGSynthesizer(retriever, generator, loader).query("test")
    assert answer == "answer"
    assert sources[0]["page"] == 4


def test_real_qdrant_statistics_and_length_validation():
    store = QdrantVectorStore(in_memory=True, vector_size=2)
    try:
        store.upsert(
            ["00000000-0000-0000-0000-000000000001"], [[1.0, 0.0]], [{"source": "test"}]
        )
        assert store.get_collection_info()["points_count"] == 1
        with pytest.raises(ValueError):
            store.upsert(["one", "two"], [[1.0, 0.0]])
        store.delete_by_payload_filter("source", "test")
        assert store.get_collection_info()["points_count"] == 0
    finally:
        store.client.close()


def test_ingestion_closes_images_on_failure(pdf_path):
    images_seen = []
    embedder = MagicMock()

    def fail(images):
        images_seen.extend(images)
        raise RuntimeError("encoder failed")

    embedder.encode_images.side_effect = fail
    with pytest.raises(RuntimeError):
        IngestionPipeline(
            DocumentLoader(dpi=72), embedder, MagicMock()
        ).ingest_document(pdf_path)
    for image in images_seen:
        with pytest.raises(ValueError):
            image.getpixel((0, 0))


def test_ingest_caches_thumbnails_without_a_second_render(pdf_path, tmp_path):
    loader = DocumentLoader(dpi=72, cache_dir=tmp_path / "cache")
    with patch.object(pdfium.PdfPage, "render", autospec=True) as render:
        render.side_effect = lambda page, **kw: original_render(page, **kw)
        for _, _images in loader.iter_batches(pdf_path, 2):
            pass
        assert render.call_count == 5
        with loader.load_page(pdf_path, 2, thumbnail=True) as image:
            assert image.width <= 240
        assert render.call_count == 5


def test_corrupt_cache_is_regenerated_and_oversized_page_is_rejected(
    pdf_path, tmp_path
):
    loader = DocumentLoader(dpi=72, cache_dir=tmp_path / "cache")
    loader.load_page(pdf_path, 1).close()
    artifact = loader._artifact(pdf_path, 1)
    artifact.write_bytes(b"corrupt artifact")
    with loader.load_page(pdf_path, 1) as image:
        assert image.size == (100, 200)
    with pytest.raises(ValueError, match="MAX_RENDER_PIXELS"):
        DocumentLoader(max_render_pixels=10).load_page(pdf_path, 1)
