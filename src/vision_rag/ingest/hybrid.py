"""Selective text/vision ingestion; model loading occurs only on visual pages."""

from pathlib import Path
from threading import RLock
from typing import Any, Callable

from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.ocr import TesseractOCR
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.ingest.text import (
    PROCESSING_VERSION,
    Block,
    chunks,
    inspect_page,
    quality,
)
from vision_rag.storage.metadata import identity
from vision_rag.storage.processing import ProcessingMetadata
from vision_rag.telemetry import stage
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore


class HybridProcessor:
    def __init__(
        self,
        loader: DocumentLoader,
        store: QdrantVectorStore,
        pipeline: Callable[[], IngestionPipeline],
        metadata: ProcessingMetadata,
        access: RLock,
        chunk_limit: int = 1200,
        overlap: int = 120,
        ocr: TesseractOCR | None = None,
    ) -> None:
        self.loader, self.store, self.pipeline = loader, store, pipeline
        self.metadata, self.access = metadata, access
        self.chunk_limit, self.overlap, self.ocr = chunk_limit, overlap, ocr

    def page(
        self,
        path: Path,
        number: int,
        base: dict[str, Any],
        mode: str,
        progress: Callable[[str, int], None],
        control: Callable[[], None],
        record: Callable[[int, tuple[int, int]], None],
    ) -> None:
        control()
        progress("extracting", number - 1)
        info = inspect_page(path, number)
        if mode != "auto":
            info.reasons.append("user_override:" + mode)
            info.visual = mode in ("visual", "ocr")
            info.ocr = mode == "ocr"
            if mode in ("text", "skip"):
                info.warnings.append("forced_mode_may_exclude_evidence")
        text_chunks: list[dict[str, Any]] = []
        native_blocks = info.blocks or [
            Block(info.native_text, (0, 0, info.width, info.height))
        ]
        if mode != "skip" and info.quality in ("usable", "uncertain"):
            text_chunks = [
                {**c, "extraction": "native"}
                for c in chunks(native_blocks, self.chunk_limit, self.overlap)
            ]
        image = None
        try:
            if info.visual or info.ocr:
                control()
                progress("rendering", number - 1)
                image = self.loader.load_page(path, number)
                artifact = self.loader._artifact(path, number, True)
                if artifact is not None:
                    with image.copy() as thumb:
                        thumb.thumbnail((240, 320))
                        self.loader._save_artifact(thumb, artifact)
                record(number, image.size)
            if info.ocr:
                control()
                progress("ocr", number - 1)
                if self.ocr is None:
                    info.warnings.append("ocr_disabled_visual_fallback")
                else:
                    try:
                        assert image is not None
                        with stage("ocr", page=number):
                            blocks = self.ocr.extract(image, info.width, info.height)
                        extracted = "\n".join(b.text for b in blocks)
                        info.features["ocr_text"] = extracted
                        info.features["ocr_quality"] = quality(extracted)[0]
                        if info.rotation:
                            info.warnings.append("ocr_boxes_use_rendered_orientation")
                        if quality(extracted)[0] in ("usable", "uncertain"):
                            text_chunks.extend(
                                {**c, "extraction": "ocr"}
                                for c in chunks(blocks, self.chunk_limit, self.overlap)
                            )
                        else:
                            info.warnings.append("ocr_text_unusable_visual_fallback")
                    except Exception as error:
                        # Explicitly preserve the native layer and visual fallback.
                        info.warnings.append(
                            "ocr_failed_visual_fallback:" + type(error).__name__
                        )
            control()
            point = identity(f"{base['build_id']}:point:{number}")
            if info.visual:
                progress("loading_model", number - 1)
                pipeline = self.pipeline()
                control()
                progress("embedding", number - 1)
                assert image is not None
                with stage("embedding", pages=1):
                    vectors = pipeline.embedder.encode_images([image])
                if len(vectors) != 1:
                    raise ValueError("Encoder returned an incomplete page")
            else:
                vectors = []
            control()
            # Queries hold this same lock, so they cannot see a vector update
            # without its corresponding committed extraction record.
            with self.access:
                control()
                progress("indexing", number - 1)
                if vectors:
                    self.store.upsert(
                        [point],
                        vectors,
                        [{**base, "source": str(path), "page_number": number}],
                    )
                else:
                    self.store.delete_ids([point])
                data = {
                    **info.data(),
                    "processing_version": PROCESSING_VERSION,
                    "chunk_limit": self.chunk_limit,
                    "chunk_overlap": self.overlap,
                    "token_unit": "utf8-byte-budget",
                    "chunk_count": len(text_chunks),
                }
                self.metadata.publish(base["build_id"], number, mode, data, text_chunks)
            progress("extracting", number)
        finally:
            if image is not None:
                image.close()

    def ingest(
        self,
        path: Path,
        base: dict[str, Any],
        count: int,
        progress: Callable[[str, int], None],
        control: Callable[[], None],
        record: Callable[[int, tuple[int, int]], None],
    ) -> None:
        self.metadata.clear(base["build_id"])
        for number in range(1, count + 1):
            self.page(path, number, base, "auto", progress, control, record)
