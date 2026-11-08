"""Typed local workspace API and replayable SSE over persisted turn events."""

import asyncio
import json
import logging
from threading import Lock, Thread
from typing import Any, AsyncIterator

import anyio
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from vision_rag.api import routes
from vision_rag.generate.events import QuestionCancelled, checkpoint
from vision_rag.storage.conversations import TERMINAL, Conversations
from vision_rag.storage.metadata import Conflict

router = APIRouter()
logger = logging.getLogger(__name__)
_lock = Lock()
_workers: dict[str, tuple[Thread, Conversations]] = {}


class Viewer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str | None = None
    page: int = Field(default=1, ge=1)
    zoom: float = Field(default=1, ge=0.25, le=3)
    scroll_top: float = Field(default=0, ge=0, le=1000000)
    scroll_left: float = Field(default=0, ge=0, le=1000000)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=160)
    document_ids: list[str] | None = Field(default=None, max_length=6)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    document_ids: list[str] | None = Field(default=None, max_length=6)
    viewer: Viewer | None = None


class Turn(BaseModel):
    id: str
    conversation_id: str
    question: str
    request: routes.QueryRequest
    state: str
    result: routes.QueryResponse | None = None
    error: str | None = None
    cancel_requested: bool
    created_at: str
    updated_at: str


class Conversation(BaseModel):
    id: str
    title: str
    document_ids: list[str] | None
    viewer: dict[str, Any]
    created_at: str
    updated_at: str
    messages: list[Turn] = Field(default_factory=list)


class StreamEvent(BaseModel):
    sequence: int
    type: str
    data: dict[str, Any]


def store() -> Conversations:
    return Conversations(routes.get_library().metadata)


@router.get("/workspace/readiness")
def workspace_readiness() -> dict[str, Any]:
    """Report selected-version search eligibility without loading a model."""
    library = routes.get_library()
    with library.access:
        manager = library.retrieval
        active = manager.active() if manager else None
        builds = {}
        if manager:
            for key in manager.source_builds():
                row = library.metadata.rows(
                    "SELECT id,version_id FROM builds WHERE id=?", (key,)
                )[0]
                builds[row["version_id"]] = key
        allowed = manager.eligible(active) if manager and active else {}
        points = [point for values in allowed.values() for point in values]
        indexed = (
            library.metadata.rows(
                "SELECT DISTINCT document_id,page_number FROM retrieval_items "
                "WHERE index_id=? AND id IN (SELECT value FROM json_each(?))",
                (active["id"], json.dumps(points)),
            )
            if active
            else []
        )
        documents = []
        for document in library.documents():
            pages = {
                row["page_number"]
                for row in indexed
                if row["document_id"] == document["id"]
            }
            build = builds.get(document.get("version_id"))
            records = (
                library.metadata.rows(
                    "SELECT p.page_number,p.state,p.visual,EXISTS(SELECT 1 FROM "
                    "text_chunks t WHERE t.build_id=p.build_id AND "
                    "t.page_number=p.page_number) AS has_text FROM page_processing p "
                    "WHERE p.build_id=?",
                    (build,),
                )
                if build
                else []
            )
            expected = (
                {
                    row["page_number"]
                    for row in records
                    if row["visual"] or row["has_text"]
                }
                if records
                else set(range(1, document["page_count"] + 1))
            )
            ready = bool(
                manager
                and active
                and build
                and expected
                and document["state"] == "ready"
                and expected.issubset(pages)
                and all(row["state"] == "ready" for row in records)
            )
            state = (
                "ready"
                if ready
                else (
                    "failed"
                    if document["state"] in ("failed", "cancelled")
                    else "reading"
                    if document["state"] != "ready"
                    else "empty"
                    if build and not expected
                    else "preparing"
                )
            )
            documents.append(
                {**document, "search_state": state, "searchable_pages": len(pages)}
            )
        revisions = manager.revisions() if manager else []
        return {
            "documents": documents,
            "search_enabled": manager is not None,
            "index": revisions[0] if revisions else None,
            "active_index": active["id"] if active else None,
        }


def scoped_documents(documents: list[str] | None) -> None:
    if documents is not None:
        for key in documents:
            try:
                routes.get_library().metadata.document(key)
            except KeyError:
                raise HTTPException(404, "Selected document is unavailable") from None


def conversation(key: str) -> dict[str, Any]:
    try:
        return store().get(key)
    except KeyError:
        raise HTTPException(404, "Conversation not found") from None


@router.get("/conversations", response_model=list[Conversation])
def list_conversations() -> list[dict[str, Any]]:
    return store().all()


@router.post("/conversations", response_model=Conversation, status_code=201)
def create_conversation(body: ConversationCreate) -> dict[str, Any]:
    scoped_documents(body.document_ids)
    return store().create(body.title, body.document_ids)


@router.get("/conversations/{key}", response_model=Conversation)
def get_conversation(key: str) -> dict[str, Any]:
    return conversation(key)


@router.patch("/conversations/{key}", response_model=Conversation)
def update_conversation(key: str, body: ConversationUpdate) -> dict[str, Any]:
    conversation(key)
    values = body.model_dump(exclude_unset=True)
    if "title" in values and values["title"] is None:
        raise HTTPException(422, "Title cannot be null")
    if "document_ids" in values:
        scoped_documents(body.document_ids)
    if body.viewer and body.viewer.version_id:
        version, _ = routes.source_version(body.viewer.version_id)
        if body.viewer.page > version["page_count"]:
            raise HTTPException(422, "Page is outside the document")
    if values.get("viewer") is None:
        values.pop("viewer", None)
    return store().update(key, values)


@router.delete("/conversations/{key}")
def delete_conversation(key: str) -> dict[str, str]:
    conversation(key)
    store().delete(key)
    return {"status": "deleted"}


def run_turn(messages: Conversations, key: str) -> None:
    try:
        checkpoint(lambda: messages.cancelled(key))
        turn = messages.message(key)
        with messages.meta.connection(True) as db:
            db.execute("UPDATE messages SET state='running' WHERE id=?", (key,))
        result = routes.execute_query(
            routes.QueryRequest.model_validate(turn["request"]),
            lambda kind, data: messages.event(key, kind, data),
            lambda: messages.cancelled(key),
        )
        messages.finish(key, "completed", result.model_dump())
    except QuestionCancelled:
        messages.finish(key, "cancelled", error="Question cancelled")
    except HTTPException as error:
        messages.finish(key, "failed", error=str(error.detail))
    except Exception:
        logger.exception("Conversation question failed")
        messages.finish(
            key, "failed", error="Question failed; retry or inspect diagnostics"
        )
    finally:
        with _lock:
            _workers.pop(key, None)


@router.post("/conversations/{key}/messages", response_model=Turn, status_code=202)
def ask(key: str, body: routes.QueryRequest) -> dict[str, Any]:
    current = conversation(key)
    scoped_documents(current["document_ids"])
    if not body.query.strip():
        raise HTTPException(422, "Question must not be blank")
    if body.page_start > body.page_end:
        raise HTTPException(422, "Page range is reversed")
    messages = store()
    try:
        with _lock:
            if len(_workers) >= 4:
                raise HTTPException(
                    429, "The local answer queue is full; try again shortly"
                )
            turn = messages.start(key, body.model_dump())
            worker = Thread(target=run_turn, args=(messages, turn["id"]), daemon=True)
            _workers[turn["id"]] = (worker, messages)
            worker.start()
        return turn
    except Conflict as error:
        raise HTTPException(409, str(error)) from None


@router.get("/messages/{key}", response_model=Turn)
def get_message(key: str) -> dict[str, Any]:
    try:
        return store().message(key)
    except KeyError:
        raise HTTPException(404, "Question not found") from None


@router.post("/messages/{key}/cancel", response_model=Turn)
def cancel_message(key: str) -> dict[str, Any]:
    get_message(key)
    return store().cancel(key)


@router.get("/messages/{key}/events")
async def events(
    key: str, request: Request, after: int = Query(default=0, ge=0)
) -> StreamingResponse:
    messages = store()
    await run_in_threadpool(get_message, key)

    async def stream() -> AsyncIterator[str]:
        cursor = after
        completed = False
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    batch = await run_in_threadpool(messages.events, key, cursor)
                    for item in batch:
                        event = StreamEvent.model_validate(item)
                        cursor = event.sequence
                        yield (
                            f"id: {cursor}\nevent: {event.type}\n"
                            f"data: {json.dumps(event.data)}\n\n"
                        )
                    turn = await run_in_threadpool(messages.message, key)
                except KeyError:
                    yield (
                        'event: error\ndata: {"message":"Conversation was cleared"}\n\n'
                    )
                    completed = True
                    break
                if turn["state"] in TERMINAL:
                    if not batch:
                        completed = True
                        break
                    continue
                yield ": keepalive\n\n"
                await asyncio.sleep(0.15)
        finally:
            if not completed:
                with anyio.CancelScope(shield=True):
                    try:
                        await run_in_threadpool(messages.cancel, key)
                    except KeyError:
                        pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def stop_turns() -> None:
    with _lock:
        workers = list(_workers.items())
    for key, (_, messages) in workers:
        try:
            messages.cancel(key)
        except KeyError:
            pass
    for _, (worker, _) in workers:
        worker.join()


@router.get("/versions/{key}/info")
def version_info(key: str) -> dict[str, Any]:
    version, _ = routes.source_version(key)
    return {k: version[k] for k in ("id", "document_id", "filename", "page_count")}
