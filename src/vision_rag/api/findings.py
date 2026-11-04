"""Server-owned comparisons, saved findings and source-checked exports."""

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from vision_rag.analysis.comparison import ComparisonEngine
from vision_rag.analysis.contracts import ComparisonRequest
from vision_rag.analysis.exports import export_finding
from vision_rag.api import routes
from vision_rag.config import settings
from vision_rag.storage.conversations import Conversations
from vision_rag.storage.findings import Findings
from vision_rag.storage.metadata import Conflict

router = APIRouter()
logger = logging.getLogger(__name__)


class FindingSummary(BaseModel):
    id: str
    title: str
    kind: Literal["comparison", "answer"]
    state: Literal["draft", "saved"]
    reviewed: bool
    content_hash: str
    created_at: str
    updated_at: str


class Finding(FindingSummary):
    content: dict[str, Any]


class FindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=160)
    reviewed: bool | None = None


class LazyGenerator:
    def __init__(self) -> None:
        self.generator: Any = None

    @property
    def last_usage(self) -> dict[str, Any]:
        value = getattr(self.generator, "last_usage", {})
        return value if isinstance(value, dict) else {}

    def generate_comparison(self, *args: Any) -> dict[str, Any]:
        self.generator = routes.get_components()[1].generator
        result: dict[str, Any] = self.generator.generate_comparison(*args)
        return result


def repository() -> Findings:
    return Findings(routes.get_library().metadata)


def source_access(content: dict[str, Any]) -> None:
    library = routes.get_library()
    try:
        library.check_available()
    except Conflict as error:
        raise HTTPException(409, str(error)) from None
    selected = {v["id"] for v in content.get("versions", [])}
    selected.update(s["version_id"] for s in content.get("sources", []))
    try:
        versions = {key: library.source(key)[0] for key in selected}
        for source in content.get("sources", []):
            version = versions[source["version_id"]]
            if (
                source["document_id"] != version["document_id"]
                or not 1 <= source["page"] <= version["page_count"]
            ):
                raise KeyError("Source mismatch")
    except (KeyError, Conflict):
        raise HTTPException(
            409,
            "A finding source is unavailable in this workspace; "
            "restoring access is required to view or export it",
        ) from None


def load(key: str) -> dict[str, Any]:
    try:
        return repository().get(key)
    except KeyError:
        raise HTTPException(404, "Finding not found") from None


@router.post("/comparisons", response_model=Finding, status_code=201)
def compare(body: ComparisonRequest) -> dict[str, Any]:
    library = routes.get_library()
    try:
        with library.access:
            result = ComparisonEngine(
                library,
                LazyGenerator(),
                settings.retrieval_candidates,
                settings.evidence_char_budget,
            ).run(body)
            return repository().create(body.question[:160], "comparison", result)
    except Conflict as error:
        raise HTTPException(409, str(error)) from None
    except KeyError:
        raise HTTPException(404, "A selected version is unavailable") from None
    except ValueError:
        raise HTTPException(
            422,
            "Comparison evidence or structured cells could not be "
            "validated; no finding was saved",
        ) from None
    except Exception as error:
        if getattr(error, "code", None) == 429:
            raise HTTPException(
                429,
                "Provider quota exhausted; saved findings remain "
                "available. Retry the comparison after quota resets",
            ) from None
        logger.exception("Comparison failed")
        raise HTTPException(
            503, "Comparison service unavailable; no finding was saved"
        ) from None


@router.get("/findings", response_model=list[FindingSummary])
def list_findings() -> list[dict[str, Any]]:
    return repository().all()


@router.get("/findings/{key}", response_model=Finding)
def get_finding(key: str) -> dict[str, Any]:
    with routes.get_library().access:
        finding = load(key)
        source_access(finding["content"])
        return finding


@router.post("/findings/{key}/save", response_model=Finding)
def save_finding(key: str) -> dict[str, Any]:
    with routes.get_library().access:
        finding = load(key)
        source_access(finding["content"])
        return repository().update(key, save=True)


@router.patch("/findings/{key}", response_model=Finding)
def update_finding(key: str, body: FindingUpdate) -> dict[str, Any]:
    with routes.get_library().access:
        finding = load(key)
        source_access(finding["content"])
        return repository().update(key, body.title, body.reviewed)


@router.delete("/findings/{key}")
def delete_finding(key: str) -> dict[str, str]:
    load(key)
    repository().delete(key)
    return {"status": "deleted"}


@router.post("/findings/from-message/{key}", response_model=Finding, status_code=201)
def save_message(key: str) -> dict[str, Any]:
    library = routes.get_library()
    with library.access:
        try:
            turn = Conversations(library.metadata).message(key)
        except KeyError:
            raise HTTPException(404, "Saved question not found") from None
        if turn["state"] != "completed" or not turn["result"]:
            raise HTTPException(
                409, "Wait for a completed answer before saving a finding"
            )
        result = turn["result"]
        if result["grounding_status"] == "legacy":
            raise HTTPException(
                409, "Ask again with versioned grounded retrieval first"
            )
        content = {
            **result,
            "question": turn["question"],
            "message_id": key,
            "request": turn["request"],
            "verification": {
                "references": "validated",
                "semantic_support": "unverified",
            },
        }
        source_access(content)
        return repository().create(
            turn["question"][:160], "answer", content, saved=True
        )


@router.get("/findings/{key}/export")
def export(
    key: str, request: Request, format: Literal["json", "csv", "md"] = "json"
) -> Response:
    with routes.get_library().access:
        finding = load(key)
        source_access(finding["content"])
        if finding["state"] != "saved":
            raise HTTPException(409, "Save the finding before exporting")
        value, media_type = export_finding(finding, format, str(request.base_url))
        return Response(
            value,
            media_type=media_type,
            headers={
                "Content-Disposition": "attachment; "
                f'filename="finding-{finding["id"]}.{format}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
