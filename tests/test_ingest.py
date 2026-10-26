import pytest
from pathlib import Path
from PIL import Image
import pypdfium2 as pdfium

from vision_rag.ingest.document_loader import DocumentLoader


@pytest.fixture
def real_pdf_path(tmp_path: Path) -> Path:
    """Fixture to create a real 2-page PDF file using pypdfium2."""
    pdf_file = tmp_path / "test_doc.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(width=100, height=100)
    doc.new_page(width=100, height=100)
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


def test_document_loader_success(real_pdf_path: Path):
    loader = DocumentLoader(dpi=144)
    images = loader.load_pdf(real_pdf_path)

    assert len(images) == 2
    for img in images:
        assert isinstance(img, Image.Image)
        assert img.mode == "RGB"
        # 100 pt at 144 dpi -> 100 * (144 / 72) = 200 px
        assert img.size == (200, 200)


def test_document_loader_file_not_found():
    loader = DocumentLoader()
    with pytest.raises(FileNotFoundError):
        loader.load_pdf("non_existent_file.pdf")

