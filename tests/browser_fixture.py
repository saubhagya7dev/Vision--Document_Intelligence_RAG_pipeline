"""Manual browser fixture: synthetic PDFs, fake inference, isolated disk library.

Run with .venv Python. Serves only 127.0.0.1:18002; never opens user documents.
"""

import io
import tempfile
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import uvicorn

from vision_rag.api import routes
from vision_rag.config import settings
from vision_rag.ingest.pipeline import IngestionPipeline


class FixtureEncoder:
    fail_next = False

    def encode_images(self, images: list[Any]) -> list[list[float]]:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Intentional synthetic fixture failure")
        return [[1.0] * 128 for _ in images]

    def close(self) -> None:
        pass


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-phase2-browser-") as temporary:
        settings.data_dir = Path(temporary)
        settings.qdrant_mode = "local"
        settings.ingestion_worker_enabled = False
        settings.import_legacy_pdfs = False
        settings.model_warmup = False
        settings.hybrid_ingestion = False
        settings.render_dpi = 72
        encoder = FixtureEncoder()

        def pipeline() -> IngestionPipeline:
            # Fixture deliberately substitutes inference, not storage or job state.
            return IngestionPipeline(routes.get_loader(), encoder, routes.get_store())  # type: ignore[arg-type]

        routes.get_pipeline = pipeline
        library = routes.get_library()
        source = Path(temporary) / "synthetic-fixture.pdf"
        with pdfium.PdfDocument.new() as pdf:
            page = pdf.new_page(width=100, height=200)
            page.close()
            pdf.save(str(source))
        data = source.read_bytes()
        library.upload(io.BytesIO(data), "Synthetic ready report.pdf")
        library.process_one()
        library.upload(
            io.BytesIO(data + b"\n% retry fixture"), "Synthetic retry report.pdf"
        )
        encoder.fail_next = True
        library.process_one()
        library.start(worker_enabled=True, import_legacy=False)
        from vision_rag.api.main import app

        print(
            "Isolated synthetic browser fixture on http://127.0.0.1:18002", flush=True
        )
        uvicorn.run(app, host="127.0.0.1", port=18002)


if __name__ == "__main__":
    main()
