from pathlib import Path
from typing import List
from PIL import Image
import pypdfium2 as pdfium


class DocumentLoader:
    """Handles the ingestion and conversion of documents (PDFs) into images."""

    def __init__(self, dpi: int = 300, fmt: str = "jpeg"):
        """Initialize the document loader.

        Args:
            dpi: Resolution for PDF to image conversion. Higher is better for VLMs.
            fmt: Output image format (retained for API compatibility).
        """
        self.dpi = dpi
        self.fmt = fmt

    def load_pdf(self, file_path: str | Path) -> List[Image.Image]:
        """Convert a PDF document into a list of PIL Images (one per page).

        Uses pypdfium2 which bundles PDFium binaries, eliminating external
        system dependencies like Poppler.

        Args:
            file_path: Path to the PDF file.

        Returns:
            List of PIL Image objects in RGB mode.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found at: {path}")

        # PDF point size is 1/72 inch; calculate scale factor for requested DPI
        scale = self.dpi / 72.0
        with pdfium.PdfDocument(str(path)) as pdf:
            images = [
                page.render(scale=scale).to_pil().convert("RGB")
                for page in pdf
            ]

        return images

