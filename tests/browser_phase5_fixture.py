"""Local UI fixture: generated PDFs, real storage, fake inference and generation."""

import io
import tempfile
from pathlib import Path
from time import sleep

import uvicorn
from test_phase4_indexes import FakeModels

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes
from vision_rag.config import settings
from vision_rag.generate.events import checkpoint
from vision_rag.models import gemini_generator


class Provider:
    def close(self):
        pass

    def generate_grounded_stream(self, query, evidence, images, delta, cancelled):
        if "failure" in query.lower():
            raise RuntimeError("Simulated provider failure")
        for word in "The fictional report lists revenue of 120 units.".split():
            checkpoint(cancelled)
            delta(word + " ")
            sleep(0.4 if "slow" in query.lower() else 0.08)
        return self.generate_grounded(query, evidence, images)

    def generate_grounded(self, query, evidence, images):
        return {
            "status": "supported",
            "claims": [
                {
                    "text": "The fictional report lists revenue of 120 units.",
                    "citations": [evidence[0]["id"]],
                }
            ],
        }


def main():
    with tempfile.TemporaryDirectory(prefix="vision-phase5-ui-") as folder:
        root = Path(folder).resolve()
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
        gemini_generator.GeminiGenerator = lambda **kw: Provider()
        library = routes.get_library()
        source = create_pdf(root / "fixture.pdf", ("text", "table"))
        library.upload(io.BytesIO(source.read_bytes()), "Fictional report.pdf")
        library.process_one()
        library.retrieval.queue()
        library.process_one()
        library.retrieval.queue(False)
        library.process_one()
        library.start(True, False)
        from vision_rag.api.main import app

        uvicorn.run(app, host="127.0.0.1", port=18005)


if __name__ == "__main__":
    main()
