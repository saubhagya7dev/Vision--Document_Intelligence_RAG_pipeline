"""Compare real pooled ColPali ingestion with selective and native-only paths.

Uses generated PDFs, isolated disk stores, cached model weights, no provider calls.
Run: python scripts/benchmark_phase3.py --output Docs/phase3-benchmark.json
"""

import argparse
import io
import json
import os
import platform
import tempfile
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--allow-downloads", action="store_true")
    args = parser.parse_args()
    if not args.allow_downloads:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from phase3_fixtures import create_pdf

    from vision_rag.config import settings
    from vision_rag.ingest.document_loader import DocumentLoader
    from vision_rag.ingest.pipeline import IngestionPipeline
    from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel
    from vision_rag.retrieval.retriever import Retriever
    from vision_rag.runtime import device_diagnostics
    from vision_rag.storage.library import DocumentLibrary
    from vision_rag.vector_stores.qdrant_store import QdrantVectorStore

    report = {
        "hardware": device_diagnostics(),
        "platform": platform.platform(),
        "dpi": args.dpi,
        "batch_size": 1,
        "provider_calls": 0,
        "ocr": "disabled in all cases",
        "corpus": "six generated pages: prose, mixed prose/table, vector "
        "table, scan, empty, prose/logo",
        "quality_scope": "synthetic evidence discovery only; not held-out answer "
        "quality",
        "cases": {},
    }
    encoder = None
    try:
        started = perf_counter()
        encoder = ColPaliEmbeddingModel(
            settings.embedding_model_name,
            device="cuda",
            precision=settings.embedding_precision,
            batch_size=1,
        )
        report["model"] = settings.embedding_model_name
        report["model_load_seconds"] = perf_counter() - started
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        with tempfile.TemporaryDirectory(prefix="vision-phase3-bench-") as folder:
            root = Path(folder)
            source = create_pdf(
                root / "fixture.pdf",
                ("text", "mixed", "table", "scan", "empty", "logo"),
            )
            for name in ("all_visual", "selective", "all_text"):
                case_root = root / name
                loader = DocumentLoader(dpi=args.dpi, cache_dir=case_root / "artifacts")
                store = QdrantVectorStore(path=case_root / "qdrant")
                pipeline = IngestionPipeline(loader, encoder, store, 1)
                lib = DocumentLibrary(
                    case_root,
                    loader,
                    store,
                    lambda: pipeline,
                    "benchmark",
                    hybrid=name != "all_visual",
                )
                try:
                    if name == "all_text":
                        page = lib.hybrid.page

                        def native_only(
                            path, number, base, mode, progress, control, record
                        ):
                            return page(
                                path, number, base, "text", progress, control, record
                            )

                        lib.hybrid.page = native_only
                    started = perf_counter()
                    job = lib.upload(io.BytesIO(source.read_bytes()), "fixture.pdf")
                    lib.process_one()
                    seconds = perf_counter() - started
                    saved = lib.metadata.job(job["id"])
                    if saved["state"] != "ready":
                        raise RuntimeError(f"{name} failed: {saved['error']}")
                    retriever = Retriever(
                        encoder,
                        store,
                        lib.ready_builds,
                        lib.workspace,
                        lambda q, k: lib.processing.search(q, lib.profile, k),
                        lambda: lib.processing.hidden_points(lib.profile),
                        has_visual=lambda: store.count_build(job["build_id"]) > 0,
                    )
                    timings, checks = [], []
                    for question, gold in (
                        ("ALPHA42 revenue", {1, 2, 3, 6}),
                        ("SCAN42 scanned evidence", {4}),
                        ("table with rows and columns", {2, 3}),
                    ):
                        started = perf_counter()
                        hits = retriever.retrieve(question, 3)
                        timings.append(perf_counter() - started)
                        pages = [h["payload"]["page_number"] for h in hits]
                        checks.append(
                            {
                                "query": question,
                                "gold_pages": sorted(gold),
                                "retrieved_pages": pages,
                                "hit_at_3": bool(gold.intersection(pages)),
                            }
                        )
                    vector_count = store.count_build(job["build_id"])
                    store.client.close()
                    files = [p for p in case_root.rglob("*") if p.is_file()]
                    report["cases"][name] = {
                        "ingestion_seconds": seconds,
                        "pages_per_second": 6 / seconds,
                        "vectors": vector_count,
                        "chunks": lib.metadata.rows(
                            "SELECT COUNT(*) AS n FROM text_chunks"
                        )[0]["n"],
                        "storage_bytes": sum(p.stat().st_size for p in files),
                        "retrieval_seconds": timings,
                        "evidence_checks": checks,
                    }
                    print(name, json.dumps(report["cases"][name]), flush=True)
                finally:
                    lib.close()
                    store.client.close()
        report["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated()
        report["peak_cuda_reserved_bytes"] = torch.cuda.max_memory_reserved()
        report["status"] = "completed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if encoder is not None:
            encoder.close()
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
