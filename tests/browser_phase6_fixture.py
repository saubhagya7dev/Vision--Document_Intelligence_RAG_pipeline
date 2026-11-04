"""Disposable comparison workflow fixture: real storage/PDFs, simulated inference."""

import io
import tempfile
from pathlib import Path

import uvicorn
from test_phase4_indexes import FakeModels

from scripts.phase4_corpus import pdf
from vision_rag.api import routes
from vision_rag.config import settings
from vision_rag.models import gemini_generator

REPORTS = {}


class Provider:
    last_usage = {"fixture": "simulated provider"}

    def close(self):
        pass

    def generate_comparison(self, request, evidence, images):
        cells = []
        for version in request["version_ids"]:
            value, currency, period, scope = REPORTS[version]
            citations = [e["id"] for e in evidence if e["version_id"] == version]
            for field in request["fields"]:
                if field.casefold() == "revenue" and citations:
                    cells.append(
                        {
                            "version_id": version,
                            "field": field,
                            "status": "reported",
                            "value": value,
                            "unit": "million",
                            "currency": currency,
                            "period": period,
                            "scope": scope,
                            "citations": citations[:1],
                        }
                    )
                else:
                    cells.append(
                        {"version_id": version, "field": field, "status": "missing"}
                    )
        return {"cells": cells}


def main():
    with tempfile.TemporaryDirectory(prefix="vision-phase6-ui-") as folder:
        root = Path(folder)
        settings.data_dir = root / "library"
        settings.qdrant_mode = "local"
        settings.ingestion_worker_enabled = False
        settings.import_legacy_pdfs = False
        settings.model_warmup = False
        settings.phase4_enabled = True
        settings.hybrid_ingestion = True
        settings.render_dpi = 72
        models = FakeModels()
        routes.get_retrieval_models = lambda: models
        gemini_generator.GeminiGenerator = lambda **_: Provider()
        library = routes.get_library()

        def upload(name, value, currency, period, scope, replace=None):
            path = root / "fixture.pdf"
            lines = [
                name,
                f"Revenue: {value} million {currency}",
                f"Reporting period: {period}",
                f"Scope: {scope}",
                "Operating margin is not disclosed.",
            ]
            pdf(path, [lines, [name + " detail", *lines[1:]]])
            job = library.upload(
                io.BytesIO(path.read_bytes()), name + ".pdf", replace_document=replace
            )
            library.process_one()
            REPORTS[job["version_id"]] = (value, currency, period, scope)
            return job

        first = upload(
            "Fictional Alpha's report", "120", "EUR", "FY2024", "Consolidated"
        )
        library.retrieval.queue()
        library.process_one()
        upload(
            "Fictional Alpha's report",
            "130",
            "EUR",
            "FY2025",
            "Consolidated",
            first["document_id"],
        )
        upload("Fictional Beta report", "150", "USD", "FY2025", "Parent company")
        library.retrieval.queue()
        library.process_one()
        library.start(True, False)
        from vision_rag.api.main import app

        uvicorn.run(app, host="127.0.0.1", port=18006)


if __name__ == "__main__":
    main()
