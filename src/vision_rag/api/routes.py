"""HTTP adapters. Blocking work runs in FastAPI's worker thread pool."""

import io
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from vision_rag.config import settings
from vision_rag.generate.synthesizer import RAGSynthesizer
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.retrieval.retriever import Retriever
from vision_rag.telemetry import stage
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore

router = APIRouter()
logger = logging.getLogger(__name__)
_pipeline: IngestionPipeline | None = None
_synthesizer: RAGSynthesizer | None = None
_vdb: QdrantVectorStore | None = None
_loader: DocumentLoader | None = None
_component_lock = threading.RLock()
_loader_lock = threading.RLock()
_store_lock = threading.RLock()
_model_state = "not_loaded"


def get_loader() -> DocumentLoader:
    global _loader
    with _loader_lock:
        if _loader is None:
            _loader = DocumentLoader(
                dpi=settings.render_dpi,
                cache_dir=settings.data_dir / "artifacts",
                max_render_pixels=settings.max_render_pixels,
            )
        return _loader


def get_store() -> QdrantVectorStore:
    global _vdb
    with _store_lock:
        if _vdb is None:
            _vdb = QdrantVectorStore(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                collection_name=settings.qdrant_collection_name,
                in_memory=settings.qdrant_in_memory,
            )
        return _vdb


def get_components() -> tuple[IngestionPipeline, RAGSynthesizer]:
    global _pipeline, _synthesizer, _model_state
    with _component_lock:
        if _pipeline is None or _synthesizer is None:
            _model_state = "loading"
            embedder = None
            generator = None
            try:
                from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel
                from vision_rag.models.gemini_generator import GeminiGenerator

                loader = get_loader()
                store = get_store()
                generator = GeminiGenerator(
                    model_name=settings.generation_model_name,
                    api_key=settings.google_api_key,
                )
                embedder = ColPaliEmbeddingModel(
                    model_name=settings.embedding_model_name,
                    device=settings.embedding_device,
                    precision=settings.embedding_precision,
                    batch_size=settings.ingestion_batch_size,
                )
                pipeline = IngestionPipeline(
                    loader, embedder, store, settings.ingestion_batch_size
                )
                synthesizer = RAGSynthesizer(
                    Retriever(embedder, store), generator, loader
                )
                _pipeline, _synthesizer = pipeline, synthesizer
                _model_state = "ready"
            except Exception:
                _model_state = "failed"
                if embedder is not None:
                    embedder.close()
                if generator is not None:
                    generator.close()
                raise
        assert _pipeline is not None and _synthesizer is not None
        return _pipeline, _synthesizer


def shutdown_components() -> None:
    global _pipeline, _synthesizer, _vdb, _loader, _model_state
    with _component_lock:
        if _vdb is not None:
            _vdb.client.close()
        if _pipeline is not None:
            _pipeline.embedder.close()
        if _synthesizer is not None:
            _synthesizer.generator.close()
        _pipeline = _synthesizer = _vdb = _loader = None
        _model_state = "not_loaded"


def document_path(filename: str) -> Path:
    root = settings.data_dir.resolve()
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or ":" in filename
        or filename in {".", ".."}
    ):
        raise HTTPException(400, "Invalid document filename")
    path = (root / filename).resolve()
    if path.parent != root or path.suffix.lower() != ".pdf":
        raise HTTPException(400, "Invalid document filename")
    return path


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=3, ge=1, le=20)


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


@router.post("/ingest")
def ingest_document(file: UploadFile = File(...)) -> dict[str, str]:
    filename = file.filename or ""
    save_path = document_path(filename)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite evidence belonging to a previously indexed upload.
    if save_path.exists():
        raise HTTPException(409, "Document already exists; delete it before replacing")
    temporary = save_path.with_suffix(f".{uuid4().hex}.upload")
    published = False
    try:
        with stage("upload_handling"):
            size = 0
            with temporary.open("xb") as stream:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, "Upload exceeds configured size limit")
                    stream.write(chunk)
            with temporary.open("rb") as stream:
                if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                    raise HTTPException(400, "Invalid PDF header")
            try:
                count = get_loader().page_count(temporary)
            except Exception:
                raise HTTPException(400, "PDF cannot be read") from None
            if count < 1 or count > settings.max_document_pages:
                raise HTTPException(
                    413, "PDF exceeds configured page limit or is empty"
                )
            # Exclusive creation also handles simultaneous uploads of the same name.
            try:
                with save_path.open("xb") as target, temporary.open("rb") as source:
                    published = True
                    import shutil

                    shutil.copyfileobj(source, target)
            except FileExistsError:
                raise HTTPException(409, "Document already exists") from None
        pipeline, _ = get_components()
        pipeline.ingest_document(
            str(save_path), metadata={"original_filename": filename}
        )
        return {"status": "success", "message": f"Successfully ingested {filename}"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Document ingestion failed")
        # Compensate partial batch writes before removing the source.
        if published:
            try:
                get_store().delete_by_payload_filter("source", str(save_path))
                save_path.unlink(missing_ok=True)
            except Exception:
                logger.exception("Ingestion cleanup failed; source retained")
        raise HTTPException(500, "Ingestion failed; see server logs") from None
    finally:
        temporary.unlink(missing_ok=True)
        file.file.close()


@router.post("/query", response_model=QueryResponse)
def query_pipeline(request: QueryRequest) -> QueryResponse:
    if not request.query.strip():
        raise HTTPException(422, "Question must not be blank")
    try:
        _, synthesizer = get_components()
        answer, sources = synthesizer.query(
            user_query=request.query, top_k=request.top_k
        )
        return QueryResponse(answer=answer, sources=sources)
    except Exception:
        logger.exception("Query failed")
        raise HTTPException(
            503, "Answer service unavailable; inspect diagnostics"
        ) from None


@router.get("/documents")
def list_documents() -> list[dict[str, Any]]:
    documents = []
    for path in sorted(settings.data_dir.glob("*.pdf")):
        stat = path.stat()
        try:
            count = get_loader().page_count(path)
        except Exception:
            count = 0
        documents.append(
            {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "page_count": count,
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return documents


@router.get("/documents/{filename}/pages/{page_num}")
def get_page_image(
    filename: str, page_num: int, thumbnail: bool = False
) -> StreamingResponse:
    path = document_path(filename)
    if not path.is_file():
        raise HTTPException(404, "Document not found")
    try:
        with get_loader().load_page(path, page_num, thumbnail=thumbnail) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="image/jpeg")
    except IndexError:
        raise HTTPException(404, "Page not found") from None


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    try:
        info = get_store().get_collection_info()
    except Exception:
        info = {"status": "unavailable", "points_count": None}
    return {
        "total_documents": len(list(settings.data_dir.glob("*.pdf"))),
        "total_vectors": info.get("points_count"),
        "collection_status": info.get("status"),
    }


@router.get("/diagnostics")
def diagnostics() -> dict[str, Any]:
    from vision_rag.runtime import device_diagnostics

    return {
        **device_diagnostics(),
        "model_state": _model_state,
        "configured_device": settings.embedding_device,
        "configured_precision": settings.embedding_precision,
        "embedding_model": settings.embedding_model_name,
        "batch_size": settings.ingestion_batch_size,
        "render_dpi": settings.render_dpi,
    }


@router.get("/ready")
def readiness() -> dict[str, str]:
    if _model_state != "ready":
        raise HTTPException(503, {"model_state": _model_state})
    return {"model_state": _model_state}


@router.delete("/documents/{filename}")
def delete_document(filename: str) -> dict[str, str]:
    path = document_path(filename)
    if not path.is_file():
        raise HTTPException(404, "Document not found")
    # Initialize storage independently of the embedding model and provider.
    store = get_store()
    store.delete_by_payload_filter("source", str(path))
    store.delete_by_payload_filter("source", str(Path("data") / filename))
    path.unlink()
    return {"status": "success", "message": f"Deleted {filename} and its vectors."}
