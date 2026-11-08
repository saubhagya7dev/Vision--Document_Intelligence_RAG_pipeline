"""Disposable redesign fixture: real storage and PDFs, simulated models/providers."""

import io
import tempfile
from pathlib import Path

import uvicorn
from browser_phase5_fixture import Provider as StreamProvider
from test_phase4_indexes import FakeModels

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes
from vision_rag.config import settings
from vision_rag.models import gemini_generator


class Provider(StreamProvider):
    last_usage = {"fixture": "simulated only"}

    def generate_comparison(self, request, evidence, images):
        cells = []
        for version in request["version_ids"]:
            citations = [e["id"] for e in evidence if e["version_id"] == version]
            for field in request["fields"]:
                cell = {"version_id": version, "field": field, "status": "missing"}
                if field.casefold() == "revenue" and citations:
                    cell.update(
                        status="reported",
                        value="120",
                        unit="units",
                        currency=None,
                        period="FY2025",
                        scope="Consolidated",
                        citations=citations[:1],
                    )
                cells.append(cell)
        return {"cells": cells}


def main():
    with tempfile.TemporaryDirectory(prefix="vision-ux-fixture-") as folder:
        root = Path(folder)
        settings.data_dir = root / "library"
        settings.qdrant_mode = "local"
        settings.ingestion_worker_enabled = False
        settings.import_legacy_pdfs = False
        settings.model_warmup = False
        settings.phase4_enabled = True
        settings.hybrid_ingestion = True
        settings.render_dpi = 72
        settings.access_token = None
        models = FakeModels()
        routes.get_retrieval_models = lambda: models
        gemini_generator.GeminiGenerator = lambda **_: Provider()
        library = routes.get_library()
        for name, kinds in (
            ("Fictional report.pdf", ("text", "table")),
            ("Fictional second report.pdf", ("text",)),
        ):
            source = create_pdf(root / name, kinds)
            library.upload(io.BytesIO(source.read_bytes()), name)
            library.process_one()
        library.retrieval.queue()
        library.process_one()
        library.start(True, False)
        from vision_rag.api.main import app

        uvicorn.run(app, host="127.0.0.1", port=18008)


if __name__ == "__main__":
    main()
