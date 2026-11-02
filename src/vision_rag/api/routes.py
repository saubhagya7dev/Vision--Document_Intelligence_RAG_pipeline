"""Local document library, durable jobs and model lifecycle HTTP adapters."""

import io
import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from vision_rag.config import settings
from vision_rag.generate.synthesizer import RAGSynthesizer
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.ocr import TesseractOCR
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.retrieval.retriever import Retriever
from vision_rag.storage.library import DocumentLibrary, ResourceLimit
from vision_rag.storage.metadata import Conflict
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore

router = APIRouter()
logger = logging.getLogger(__name__)
_pipeline: IngestionPipeline | None = None
_synthesizer: RAGSynthesizer | None = None
_vdb: QdrantVectorStore | None = None
_loader: DocumentLoader | None = None
_library: DocumentLibrary | None = None
_component_lock = threading.RLock()
_loader_lock = threading.RLock()
_store_lock = threading.RLock()
_library_lock = threading.RLock()
_model_state = "not_loaded"


def get_loader() -> DocumentLoader:
    global _loader
    with _loader_lock:
        if _loader is None:
            _loader = DocumentLoader(
                dpi=settings.render_dpi,
                cache_dir=settings.data_dir.resolve() / "artifacts",
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
                collection_name=settings.qdrant_collection_name + "_pooled_v1",
                in_memory=settings.qdrant_mode == "memory",
                path=settings.data_dir.resolve() / "qdrant"
                if settings.qdrant_mode == "local"
                else None,
            )
        return _vdb


def get_library() -> DocumentLibrary:
    global _library
    with _library_lock:
        if _library is None:
            library = DocumentLibrary(
                settings.data_dir,
                get_loader(),
                get_store(),
                get_pipeline,
                settings.index_profile,
                settings.workspace_id,
                settings.max_upload_mb * 1024 * 1024,
                settings.max_document_pages,
                hybrid=settings.hybrid_ingestion,
                chunk_limit=settings.text_chunk_limit,
                chunk_overlap=settings.text_chunk_overlap,
                ocr=TesseractOCR(
                    settings.tesseract_executable,
                    settings.ocr_language,
                    settings.ocr_timeout_seconds,
                )
                if settings.ocr_enabled
                else None,
            )
            _library = library
            try:
                library.start(
                    settings.ingestion_worker_enabled, settings.import_legacy_pdfs
                )
            except BaseException:
                library.close()
                _library = None
                raise
        return _library


def get_pipeline() -> IngestionPipeline:
    global _pipeline, _model_state
    with _component_lock:
        if _pipeline is None:
            _model_state = "loading"
            try:
                from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel

                embedder = ColPaliEmbeddingModel(
                    model_name=settings.embedding_model_name,
                    device=settings.embedding_device,
                    precision=settings.embedding_precision,
                    batch_size=settings.ingestion_batch_size,
                )
                _pipeline = IngestionPipeline(
                    get_loader(), embedder, get_store(), settings.ingestion_batch_size
                )
                _model_state = "ready"
            except Exception:
                _model_state = "failed"
                raise
        return _pipeline


def get_components() -> tuple[IngestionPipeline | None, RAGSynthesizer]:
    global _synthesizer
    # A text-only library must not load a multi-GB visual model just to answer.
    library = get_library()

    def has_visual() -> bool:
        hidden = library.processing.hidden_points(library.profile)
        return any(
            get_store().count_build(build, hidden) > 0
            for build in library.ready_builds()
        )

    pipeline = get_pipeline() if not settings.hybrid_ingestion or has_visual() else None
    with _component_lock:
        if _synthesizer is None:
            from vision_rag.models.gemini_generator import GeminiGenerator

            generator = GeminiGenerator(
                model_name=settings.generation_model_name,
                api_key=settings.google_api_key,
            )
            _synthesizer = RAGSynthesizer(
                Retriever(
                    pipeline.embedder if pipeline is not None else None,
                    get_store(),
                    library.ready_builds,
                    settings.workspace_id,
                    lexical_search=lambda query, limit: library.processing.search(
                        query, library.profile, limit
                    ),
                    hidden_points=lambda: library.processing.hidden_points(
                        library.profile
                    ),
                    embedding_factory=lambda: get_pipeline().embedder,
                    has_visual=has_visual,
                ),
                generator,
                get_loader(),
                library.source,
            )
        return pipeline, _synthesizer


def shutdown_components() -> None:
    global _pipeline, _synthesizer, _vdb, _loader, _library, _model_state
    # The worker may need the component lock to finish model initialization.
    if _library is not None:
        _library.close()
        _library = None
    with _component_lock:
        if _pipeline is not None:
            _pipeline.embedder.close()
        if _synthesizer is not None:
            _synthesizer.generator.close()
        if _vdb is not None:
            _vdb.client.close()
        _pipeline = _synthesizer = _vdb = _loader = None
        _model_state = "not_loaded"


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=3, ge=1, le=20)


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


class PageOverride(BaseModel):
    mode: Literal["auto", "text", "visual", "ocr", "skip"] = "auto"


class PageTaskResponse(BaseModel):
    id: str
    build_id: str
    version_id: str
    document_id: str
    page_number: int
    mode: Literal["auto", "text", "visual", "ocr", "skip"]
    state: Literal["uploaded", "running", "ready", "failed", "cancelled"]
    attempts: int
    error: str | None
    created_at: str
    updated_at: str


def processing_build(version_id: str) -> str:
    library = get_library()
    source_version(version_id)
    builds = library.metadata.rows(
        "SELECT id FROM builds WHERE version_id=? AND profile=?",
        (version_id, library.profile),
    )
    if not builds:
        raise HTTPException(409, "Version needs a compatible index build")
    return str(builds[0]["id"])


@router.get("/versions/{version_id}/processing")
def page_processing(
    version_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    library = get_library()
    with library.access:
        build = processing_build(version_id)
        pages = library.processing.pages(build, limit=limit, offset=offset)
        for page in pages:
            page["data"].pop("native_text", None)
            page["data"].pop("blocks", None)
            page["data"].get("features", {}).pop("ocr_text", None)
        return {
            "build_id": build,
            "pages": pages,
            "offset": offset,
            "limit": limit,
            "tasks": library.metadata.rows(
                "SELECT * FROM page_tasks WHERE build_id=? ORDER BY "
                "created_at DESC LIMIT 100",
                (build,),
            ),
        }


@router.get("/versions/{version_id}/pages/{page_num}/text")
def page_text(version_id: str, page_num: int) -> dict[str, Any]:
    library = get_library()
    with library.access:
        build = processing_build(version_id)
        pages = library.processing.pages(build, number=page_num)
        if not pages:
            raise HTTPException(
                404, "Page extraction is unavailable; process this page first"
            )
        import json

        records = library.metadata.rows(
            "SELECT id,data FROM text_chunks WHERE build_id=? AND page_number=?",
            (build, page_num),
        )
        tasks = library.metadata.rows(
            "SELECT * FROM page_tasks WHERE build_id=? AND page_number=? "
            "ORDER BY created_at DESC LIMIT 1",
            (build, page_num),
        )
        return {
            **pages[0],
            "chunks": [{"id": r["id"], **json.loads(r["data"])} for r in records],
            "task": tasks[0] if tasks else None,
        }


@router.post(
    "/versions/{version_id}/pages/{page_num}/processing",
    status_code=202,
    response_model=PageTaskResponse,
)
def override_page(
    version_id: str, page_num: int, request: PageOverride
) -> dict[str, Any]:
    library = get_library()
    if library.hybrid is None:
        raise HTTPException(409, "Enable HYBRID_INGESTION to process pages")
    try:
        with library.access:
            task = library.processing.enqueue(
                processing_build(version_id), page_num, request.mode
            )
        library.wake_event.set()
        return task
    except (KeyError, IndexError):
        raise HTTPException(404, "Document page not found") from None
    except Conflict as error:
        raise HTTPException(409, str(error)) from None


@router.get("/page-tasks/{task_id}", response_model=PageTaskResponse)
def get_page_task(task_id: str) -> dict[str, Any]:
    try:
        return get_library().processing.task(task_id)
    except KeyError:
        raise HTTPException(404, "Page task not found") from None


class JobResponse(BaseModel):
    id: str
    document_id: str
    version_id: str | None = None
    build_id: str | None = None
    kind: str
    state: str
    pages_done: int
    total_pages: int
    cancel_requested: bool
    attempts: int
    error: str | None = None
    created_at: str
    updated_at: str
    filename: str | None = None
    deduplicated: bool = False
    document_deleted: bool = False


def upload_job(file: UploadFile, document_id: str | None = None) -> JobResponse:
    try:
        job = get_library().upload(
            file.file, file.filename or "", replace_document=document_id
        )
        return JobResponse(**job)
    except ResourceLimit as error:
        raise HTTPException(413, str(error)) from None
    except Conflict as error:
        raise HTTPException(409, str(error)) from None
    except KeyError:
        raise HTTPException(404, "Document not found") from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    finally:
        file.file.close()


@router.post("/ingest", response_model=JobResponse, status_code=202)
def ingest_document(file: UploadFile = File(...)) -> JobResponse:
    return upload_job(file)


@router.post(
    "/documents/{document_id}/versions", response_model=JobResponse, status_code=202
)
def upload_version(document_id: str, file: UploadFile = File(...)) -> JobResponse:
    return upload_job(file, document_id)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    library = get_library()
    return library.metadata.rows(
        "SELECT j.*,d.filename,CASE WHEN d.deleted_at IS NULL THEN 0 ELSE 1 END "
        "AS document_deleted FROM jobs j JOIN documents d ON d.id=j.document_id "
        "WHERE d.workspace=? ORDER BY j.created_at DESC LIMIT ?",
        (library.workspace, limit),
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return get_library().metadata.job(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None


@router.post("/jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry_job(job_id: str) -> dict[str, Any]:
    library = get_library()
    try:
        with library.access:
            previous = library.metadata.job(job_id)
            if previous["build_id"]:
                build = library.metadata.rows(
                    "SELECT profile FROM builds WHERE id=?", (previous["build_id"],)
                )[0]
                if build["profile"] != library.profile:
                    raise Conflict(
                        "Index profile changed; restore its configuration before retry"
                    )
            job = library.metadata.retry(job_id)
        library.wake_event.set()
        return job
    except KeyError:
        raise HTTPException(404, "Job or document not found") from None
    except Conflict as error:
        raise HTTPException(409, str(error)) from None


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, status_code=202)
def cancel_job(job_id: str) -> dict[str, Any]:
    library = get_library()
    try:
        with library.access:
            return library.metadata.cancel(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None
    except Conflict as error:
        raise HTTPException(409, str(error)) from None


@router.post("/query", response_model=QueryResponse)
def query_pipeline(request: QueryRequest) -> QueryResponse:
    if not request.query.strip():
        raise HTTPException(422, "Question must not be blank")
    library = get_library()
    try:
        # Deletion cannot remove source artifacts while a response uses them.
        with library.access:
            if not library.ready_builds():
                return QueryResponse(answer="No ready documents found.", sources=[])
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
    return get_library().documents()


@router.get("/documents/{reference}/versions")
def list_versions(reference: str) -> list[dict[str, Any]]:
    library = get_library()
    try:
        doc = library.metadata.document(reference)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
    return library.metadata.rows(
        "SELECT id,document_id,ordinal,content_hash,filename,size_bytes,page_count,"
        "created_at,state FROM versions WHERE document_id=? ORDER BY ordinal DESC",
        (doc["id"],),
    )


def source_version(version_id: str) -> tuple[dict[str, Any], Path]:
    try:
        return get_library().source(version_id)
    except KeyError:
        raise HTTPException(404, "Document version not found") from None
    except Conflict as error:
        raise HTTPException(503, str(error)) from None


@router.get("/versions/{version_id}/pages/{page_num}")
def get_version_page(
    version_id: str, page_num: int, thumbnail: bool = False
) -> StreamingResponse:
    library = get_library()
    with library.access:
        _, path = source_version(version_id)
        try:
            with get_loader().load_page(path, page_num, thumbnail=thumbnail) as image:
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            return StreamingResponse(buffer, media_type="image/jpeg")
        except IndexError:
            raise HTTPException(404, "Page not found") from None


@router.get("/versions/{version_id}/file")
def get_original(version_id: str) -> StreamingResponse:
    with get_library().access:
        version, path = source_version(version_id)
        stream = path.open("rb")

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(version["filename"], safe="")
        },
    )


@router.get("/documents/{reference}/pages/{page_num}")
def get_page_image(
    reference: str, page_num: int, thumbnail: bool = False
) -> StreamingResponse:
    library = get_library()
    try:
        doc = library.metadata.document(reference)
        versions = library.metadata.rows(
            "SELECT id FROM versions WHERE document_id=? ORDER BY ordinal DESC LIMIT 1",
            (doc["id"],),
        )
        version = doc["active_version_id"] or versions[0]["id"]
        return get_version_page(version, page_num, thumbnail)
    except KeyError:
        raise HTTPException(404, "Document not found") from None


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    library = get_library()
    documents = library.documents()
    try:
        hidden = library.processing.hidden_points(library.profile)
        count = sum(
            get_store().count_build(build, hidden) for build in library.ready_builds()
        )
        status = "ready"
    except Exception:
        logger.exception("Vector statistics unavailable")
        count = None
        status = "unavailable"
    pending = library.metadata.rows(
        "SELECT COUNT(*) AS count FROM jobs j JOIN documents d ON d.id=j.document_id "
        "WHERE d.workspace=? AND j.state NOT IN ('ready','failed','cancelled')",
        (library.workspace,),
    )[0]["count"]
    page_tasks = library.metadata.rows(
        "SELECT COUNT(*) AS count FROM page_tasks t JOIN builds b ON b.id=t.build_id "
        "JOIN versions v ON v.id=b.version_id JOIN documents d ON d.id=v.document_id "
        "WHERE d.workspace=? AND d.deleted_at IS NULL "
        "AND t.state IN ('uploaded','running')",
        (library.workspace,),
    )[0]["count"]
    return {
        "total_documents": len(documents),
        "total_vectors": count,
        "collection_status": status,
        "pending_jobs": pending,
        "pending_page_tasks": page_tasks,
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
        "qdrant_mode": settings.qdrant_mode,
        "workspace": settings.workspace_id,
        "worker_enabled": settings.ingestion_worker_enabled,
        "index_profile": settings.index_profile,
        "hybrid_ingestion": settings.hybrid_ingestion,
        "ocr_enabled": settings.ocr_enabled,
        "ocr_available": bool(shutil.which(settings.tesseract_executable)),
        "text_chunk_limit": settings.text_chunk_limit,
        "text_chunk_overlap": settings.text_chunk_overlap,
    }


@router.get("/ready")
def readiness() -> dict[str, str]:
    if _model_state != "ready":
        raise HTTPException(503, {"model_state": _model_state})
    return {"model_state": _model_state}


@router.delete("/documents/{reference}", response_model=JobResponse, status_code=202)
def delete_document(reference: str) -> dict[str, Any]:
    try:
        return get_library().delete(reference)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
