"""Isolated synthetic UI workflow with real storage and fake inference."""

import io
import tempfile
from pathlib import Path

import uvicorn
from phase3_fixtures import create_pdf

from vision_rag.api import routes
from vision_rag.config import settings
from vision_rag.ingest.pipeline import IngestionPipeline


class FixtureEncoder:
    def encode_images(self, images):
        return [[1.0] * 128 for _ in images]

    def close(self):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="vision-phase3-browser-") as temporary:
        settings.data_dir = Path(temporary) / "library"
        settings.qdrant_mode = "local"
        settings.ingestion_worker_enabled = False
        settings.import_legacy_pdfs = False
        settings.model_warmup = False
        settings.hybrid_ingestion = True
        settings.render_dpi = 72
        encoder = FixtureEncoder()
        routes.get_pipeline = lambda: IngestionPipeline(
            routes.get_loader(), encoder, routes.get_store(), 1
        )
        library = routes.get_library()
        path = create_pdf(Path(temporary) / "fixture.pdf", ("text", "table", "scan"))
        library.upload(io.BytesIO(path.read_bytes()), "Synthetic hybrid report.pdf")
        library.process_one()
        library.start(True, False)
        from vision_rag.api.main import app

        uvicorn.run(app, host="127.0.0.1", port=18003)


if __name__ == "__main__":
    main()
