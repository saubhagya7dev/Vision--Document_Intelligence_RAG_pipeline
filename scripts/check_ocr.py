"""Verify local OCR on generated scan evidence; optionally use real ColPali.

No user PDFs, persistent library changes, or generation-provider calls.
"""

import argparse
import io
import json
import os
import tempfile
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--allow-downloads", action="store_true")
    args = parser.parse_args()
    if not args.allow_downloads:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from phase3_fixtures import create_pdf

    from vision_rag.config import settings
    from vision_rag.ingest.document_loader import DocumentLoader
    from vision_rag.ingest.ocr import TesseractOCR
    from vision_rag.ingest.pipeline import IngestionPipeline
    from vision_rag.storage.library import DocumentLibrary
    from vision_rag.vector_stores.qdrant_store import QdrantVectorStore

    ocr = TesseractOCR(
        settings.tesseract_executable,
        settings.ocr_language,
        settings.ocr_timeout_seconds,
    )
    report = {
        "language": settings.ocr_language,
        "dpi": 150,
        "fixture": "generated image-only PDF, SCAN42 and revenue 120 units",
        "provider_calls": 0,
        "checks": {},
    }
    model = None
    try:
        with tempfile.TemporaryDirectory(prefix="vision-ocr-check-") as temporary:
            root = Path(temporary).resolve()
            source = create_pdf(root / "scan.pdf", ("scan",))
            loader = DocumentLoader(dpi=150, cache_dir=root / "library/artifacts")
            with loader.load_page(source, 1) as image:
                started = perf_counter()
                blocks = ocr.extract(image, 600, 800)
                report["recognition_seconds"] = perf_counter() - started
            text = "\n".join(block.text for block in blocks)
            report["recognized_text"] = text
            if "SCAN42" not in text or "120" not in text:
                raise RuntimeError("Expected synthetic identifiers were not recognized")
            report["checks"]["real_ocr_recognition"] = "passed"
            if args.model:
                from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel

                started = perf_counter()
                model = ColPaliEmbeddingModel(
                    settings.embedding_model_name,
                    settings.embedding_device,
                    settings.embedding_precision,
                    1,
                )
                report["model_load_seconds"] = perf_counter() - started
                report["model"] = settings.embedding_model_name
                report["device"] = model.device
                store = QdrantVectorStore(path=root / "library/qdrant")
                pipeline = IngestionPipeline(loader, model, store, 1)
                lib = DocumentLibrary(
                    root / "library",
                    loader,
                    store,
                    lambda: pipeline,
                    settings.index_profile,
                    hybrid=True,
                    ocr=ocr,
                )
                try:
                    started = perf_counter()
                    job = lib.upload(io.BytesIO(source.read_bytes()), "scan.pdf")
                    lib.process_one()
                    report["ingestion_seconds"] = perf_counter() - started
                    saved = lib.metadata.job(job["id"])
                    pages = lib.processing.pages(job["build_id"])
                    if saved["state"] != "ready":
                        raise RuntimeError("Scan ingestion did not complete")
                    if not lib.processing.search("SCAN42", settings.index_profile, 3):
                        raise RuntimeError("Recognized text was not searchable")
                    if store.count_build(job["build_id"]) != 1:
                        raise RuntimeError("Visual fallback embedding is missing")
                    warnings = pages[0]["data"]["warnings"]
                    if warnings:
                        raise RuntimeError(f"Unexpected scan warnings: {warnings}")
                    report["chunks"] = pages[0]["data"]["chunk_count"]
                    report["checks"]["real_ocr_visual_ingestion"] = "passed"
                    report["checks"]["ocr_text_search"] = "passed"
                finally:
                    lib.close()
                    store.client.close()
            report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if model is not None:
            model.close()
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
