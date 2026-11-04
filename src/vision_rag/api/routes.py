"""Local document library, durable jobs and model lifecycle HTTP adapters."""

import io
import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import Request

from vision_rag.config import settings
from vision_rag.core.embeddings import BaseEmbeddingModel
from vision_rag.generate.events import Cancelled, Emit, checkpoint
from vision_rag.generate.grounding import GroundedSynthesizer
from vision_rag.generate.synthesizer import RAGSynthesizer
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.ocr import TesseractOCR
from vision_rag.ingest.pipeline import IngestionPipeline
from vision_rag.models.retrieval_models import RetrievalModels
from vision_rag.retrieval.engine import HybridRetriever
from vision_rag.retrieval.indexes import RetrievalIndexes
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
_retrieval_models: RetrievalModels | None = None


def get_retrieval_models() -> RetrievalModels:
    global _retrieval_models
    with _component_lock:
        if _retrieval_models is None:
            _retrieval_models = RetrievalModels(
                settings.embedding_device,
                settings.embedding_precision,
                settings.data_dir.resolve() / "artifacts/visual_tokens",
            )
        return _retrieval_models


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
                if settings.phase4_enabled:
                    library.retrieval = RetrievalIndexes(
                        library,
                        get_retrieval_models(),
                        settings.retrieval_specification,
                    )
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

                embedder: BaseEmbeddingModel
                if settings.phase4_enabled:
                    from vision_rag.models.pooled_adapter import PooledAdapter

                    embedder = PooledAdapter(
                        get_retrieval_models(), settings.retrieval_specification
                    )
                else:
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
                timeout_ms=settings.provider_timeout_ms,
                attempts=settings.provider_attempts,
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


def warmup_components() -> None:
    get_pipeline()
    if settings.phase4_enabled:
        models = get_retrieval_models()
        models.encode_text(settings.retrieval_specification, ["warmup"], True)
        models.encode_visual(settings.retrieval_specification, ["warmup"], False)


def shutdown_components() -> None:
    global _pipeline, _synthesizer, _vdb, _loader, _library, _model_state
    global _retrieval_models
    from vision_rag.api.workspace import stop_turns

    stop_turns()
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
        if _retrieval_models is not None:
            _retrieval_models.close()
            _retrieval_models = None


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=3, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None, max_length=6)
    page_start: int = Field(default=1, ge=1)
    page_end: int = Field(default=100000, ge=1)
    previous_question: str | None = Field(default=None, max_length=2000)
    tier: Literal["auto", "text", "visual", "hybrid", "rerank"] = "auto"
    evidence_only: bool = False


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    claims: list[dict[str, Any]] = Field(default_factory=list)
    grounding_status: str = "legacy"
    original_query: str | None = None
    retrieval_query: str | None = None
    retrieval: dict[str, Any] = Field(default_factory=dict)
    provider_calls: int = 0
    support_validation: str | None = None
    provider_usage: list[dict[str, Any]] = Field(default_factory=list)


class ReindexRequest(BaseModel):
    activate_when_ready: bool = True


def index_manager() -> RetrievalIndexes:
    manager: RetrievalIndexes | None = get_library().retrieval
    if manager is None:
        raise HTTPException(409, "Enable PHASE4_ENABLED to use retrieval indexes")
    return manager


@router.get("/indexes")
def retrieval_indexes() -> dict[str, Any]:
    manager = index_manager()
    snapshot = manager.snapshot()
    return {
        "active": manager.meta.setting("retrieval_active"),
        "previous": manager.meta.setting("retrieval_previous"),
        "indexes": [
            {
                **row,
                "can_activate": row["state"] == "ready" and row["snapshot"] == snapshot,
            }
            for row in manager.revisions()
        ],
    }


@router.post("/indexes", status_code=202)
def reindex(request: ReindexRequest) -> dict[str, Any]:
    try:
        with get_library().access:
            return index_manager().queue(request.activate_when_ready)
    except Conflict as error:
        raise HTTPException(409, str(error)) from None


@router.post("/indexes/{index_id}/{action}")
def change_index(
    index_id: str, action: Literal["activate", "cancel"]
) -> dict[str, Any]:
    manager = index_manager()
    try:
        with get_library().access:
            if action == "activate":
                manager.activate(index_id)
            else:
                manager.cancel(index_id)
            return manager.row(index_id)
    except KeyError:
        raise HTTPException(404, "Index not found") from None
    except Conflict as error:
        raise HTTPException(409, str(error)) from None


class PageOverride(BaseModel):
    mode: Literal["auto", "text", "visual", "ocr", "skip"] = "auto"


class MaintenanceRequest(BaseModel):
    action: Literal["history", "cache", "reset"]
    confirmation: Literal["CLEAR", "DELETE"]


@router.get("/maintenance")
def maintenance_status() -> dict[str, Any]:
    library = get_library()
    return {
        "reset_pending": library.reset_pending(),
        "running": library.maintenance_requested.is_set(),
        "reset_supported": library.store.local,
        "documents": len(library.documents()),
    }


@router.post("/maintenance")
def maintain_library(request: MaintenanceRequest, http: Request) -> dict[str, str]:
    if request.action == "reset" and request.confirmation != "DELETE":
        raise HTTPException(422, "Confirm permanent deletion with DELETE")
    origin = http.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (
        http.url.scheme,
        http.url.netloc,
    ):
        raise HTTPException(403, "Data controls require a same-origin request")
    if http.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Data controls require a same-origin request")
    library = get_library()
    try:
        if request.action == "history":
            library.clear_history()
        elif request.action == "cache":
            library.clear_page_cache()
        else:
            library.reset()
            if library.thread is None:
                library.start(settings.ingestion_worker_enabled, False)
        return {"status": "cleared", "action": request.action}
    except Conflict as error:
        raise HTTPException(409, str(error)) from None
    except Exception:
        logger.exception("Library maintenance failed")
        raise HTTPException(
            503,
            "Cleanup incomplete. Retry the same action; "
            "inspect server logs if it repeats.",
        ) from None


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


def upload_job(
    file: UploadFile, document_id: str | None = None, generation: int | None = None
) -> JobResponse:
    try:
        job = get_library().upload(
            file.file,
            file.filename or "",
            replace_document=document_id,
            expected_generation=generation,
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
def ingest_document(request: Request, file: UploadFile = File(...)) -> JobResponse:
    return upload_job(file, generation=request.state.library_generation)


@router.post(
    "/documents/{document_id}/versions", response_model=JobResponse, status_code=202
)
def upload_version(
    document_id: str, request: Request, file: UploadFile = File(...)
) -> JobResponse:
    return upload_job(file, document_id, request.state.library_generation)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    library = get_library()
    if library.reset_pending():
        return []
    return library.metadata.rows(
        "SELECT j.*,d.filename,CASE WHEN d.deleted_at IS NULL THEN 0 ELSE 1 END "
        "AS document_deleted FROM jobs j JOIN documents d ON d.id=j.document_id "
        "WHERE d.workspace=? AND (j.state NOT IN ('ready','failed','cancelled') "
        "OR j.updated_at>?) ORDER BY j.created_at DESC LIMIT ?",
        (
            library.workspace,
            library.metadata.setting("history_cleared_at") or "",
            limit,
        ),
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
    return execute_query(request)


def execute_query(
    request: QueryRequest, emit: Emit | None = None, cancelled: Cancelled | None = None
) -> QueryResponse:
    checkpoint(cancelled)
    if not request.query.strip():
        raise HTTPException(422, "Question must not be blank")
    library = get_library()
    if library.retrieval is None and (
        request.evidence_only
        or request.document_ids is not None
        or request.tier != "auto"
        or request.page_start != 1
        or request.page_end != 100000
    ):
        raise HTTPException(
            409, "Enable PHASE4_ENABLED for scoped retrieval and Find pages"
        )
    try:
        # Deletion cannot remove source artifacts while a response uses them.
        with library.access:
            checkpoint(cancelled)
            if emit:
                emit("progress", {"stage": "retrieving"})
            if not library.ready_builds() and not (
                library.retrieval is not None and library.retrieval.source_builds()
            ):
                return QueryResponse(answer="No ready documents found.", sources=[])
            if library.retrieval is not None:
                manager = index_manager()
                active = manager.active()
                if active is None:
                    raise Conflict(
                        "Retrieval index is preparing; inspect indexing progress"
                    )
                documents = (
                    None
                    if request.document_ids is None
                    else list(
                        dict.fromkeys(
                            library.metadata.document(doc)["id"]
                            for doc in request.document_ids
                        )
                    )
                )
                if request.page_start > request.page_end:
                    raise ValueError("Page range is reversed")
                if request.evidence_only:
                    from vision_rag.generate.grounding import followup_query

                    rewritten = followup_query(request.query, request.previous_question)
                    hits, details = HybridRetriever(
                        manager,
                        settings.retrieval_candidates,
                        settings.evidence_char_budget,
                    ).retrieve(
                        rewritten,
                        max(request.top_k, len(documents or [])),
                        documents,
                        (request.page_start, request.page_end),
                        "hybrid" if request.tier == "auto" else request.tier,
                    )
                    sources = []
                    for hit in hits:
                        payload = hit["payload"]
                        version, _ = library.source(payload["version_id"])
                        sources.append(
                            {
                                "evidence_id": hit["evidence_id"],
                                "source": version["filename"],
                                "version_id": version["id"],
                                "document_id": version["document_id"],
                                "page": payload["page_number"],
                                "score": hit["score"],
                                "score_kind": hit["score_kind"],
                                "excerpt": payload.get("text", ""),
                            }
                        )
                    return QueryResponse(
                        answer=f"Found {len(sources)} source pages. "
                        "Inspect the evidence below.",
                        sources=sources,
                        grounding_status="evidence_only",
                        original_query=request.query,
                        retrieval_query=rewritten,
                        retrieval=details,
                        provider_calls=0,
                        support_validation="retrieval only; "
                        "no factual answer generated",
                    )
                _, legacy = get_components()
                learned = None
                if settings.router_path:
                    from vision_rag.retrieval.router import CostRouter

                    learned = CostRouter.load(settings.router_path)
                    if learned.profile != active["profile"]:
                        raise Conflict("Router was trained for another index profile")
                grounded = GroundedSynthesizer(
                    HybridRetriever(
                        manager,
                        settings.retrieval_candidates,
                        settings.evidence_char_budget,
                    ),
                    legacy.generator,
                    get_loader(),
                    library.source,
                    learned,
                )
                result = grounded.query(
                    request.query,
                    max(request.top_k, len(documents or [])),
                    documents,
                    request.previous_question,
                    request.tier,
                    (request.page_start, request.page_end),
                    emit,
                    cancelled,
                )
                return QueryResponse(**result)
            _, synthesizer = get_components()
            answer, sources = synthesizer.query(
                user_query=request.query, top_k=request.top_k
            )
            return QueryResponse(answer=answer, sources=sources)
    except Conflict as error:
        raise HTTPException(409, str(error)) from None
    except KeyError:
        raise HTTPException(404, "Requested document or index not found") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception as error:
        from vision_rag.generate.events import QuestionCancelled

        if isinstance(error, QuestionCancelled):
            raise
        if getattr(error, "code", None) == 429:
            raise HTTPException(
                429,
                "The answer provider quota is exhausted. Use Find pages for local "
                "retrieval, or retry after the provider quota resets.",
            ) from None
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
        "total_pages": library.metadata.rows(
            "SELECT COALESCE(SUM(v.page_count),0) AS count FROM documents d "
            "JOIN versions v ON v.id=d.active_version_id "
            "WHERE d.workspace=? AND d.deleted_at IS NULL",
            (library.workspace,),
        )[0]["count"],
        "completed_queries": library.metadata.rows(
            "SELECT COUNT(*) AS count FROM messages m JOIN conversations c "
            "ON c.id=m.conversation_id WHERE c.workspace=? AND m.state='completed'",
            (library.workspace,),
        )[0]["count"],
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
        "model_state": model_state(),
        "phase4_enabled": settings.phase4_enabled,
        "text_model_loaded": bool(
            _retrieval_models is not None and _retrieval_models.text is not None
        ),
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
    state = model_state()
    if state != "ready":
        raise HTTPException(503, {"model_state": state})
    return {"model_state": state}


def model_state() -> str:
    if settings.phase4_enabled:
        if _retrieval_models is not None and _retrieval_models.visual is not None:
            return "ready"
        return "not_loaded" if _model_state == "ready" else _model_state
    return _model_state


@router.delete("/documents/{reference}", response_model=JobResponse, status_code=202)
def delete_document(reference: str) -> dict[str, Any]:
    try:
        return get_library().delete(reference)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
