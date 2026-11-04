"""Reference validation is distinct from semantic claim support."""

from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vision_rag.generate.events import Cancelled, Emit, checkpoint
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.retrieval.engine import TIERS, HybridRetriever


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(min_length=1, max_length=12)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["supported", "insufficient", "conflicting"]
    claims: list[Claim] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def check_claims(self) -> "GroundedAnswer":
        if self.status != "insufficient" and not self.claims:
            raise ValueError("A factual answer requires cited claims")
        if self.status == "insufficient" and self.claims:
            raise ValueError("An insufficient answer must abstain")
        return self


def validate_answer(value: Any, supplied: set[str]) -> GroundedAnswer:
    result = GroundedAnswer.model_validate(value)
    if any(
        citation not in supplied
        for claim in result.claims
        for citation in claim.citations
    ):
        raise ValueError("Provider returned an unknown evidence ID")
    if (
        result.status == "conflicting"
        and len({c for claim in result.claims for c in claim.citations}) < 2
    ):
        raise ValueError(
            "A conflict requires at least two supplied evidence references"
        )
    return result


def followup_query(query: str, previous: str | None) -> str:
    if previous and query.lower().startswith(
        ("what about", "and ", "how about", "why", "which of", "compare it")
    ):
        return "Previous question: " + previous + "\nFollow-up question: " + query
    return query


class GroundedSynthesizer:
    def __init__(
        self,
        retriever: HybridRetriever,
        generator: Any,
        loader: DocumentLoader,
        source: Callable[[str], tuple[dict[str, Any], Path]],
        router: Any = None,
        max_provider_calls: int = 2,
    ) -> None:
        self.retriever, self.generator, self.loader, self.source = (
            retriever,
            generator,
            loader,
            source,
        )
        self.router, self.max_provider_calls = router, max_provider_calls

    def query(
        self,
        query: str,
        top_k: int = 3,
        documents: list[str] | None = None,
        previous: str | None = None,
        tier: str = "auto",
        page_range: tuple[int, int] | None = None,
        emit: Emit | None = None,
        cancelled: Cancelled | None = None,
    ) -> dict[str, Any]:
        rewritten = followup_query(query, previous)
        start = (
            tier
            if tier != "auto"
            else (
                self.router.choose(rewritten, len(documents or []))
                if self.router
                else "hybrid"
            )
        )
        route = list(TIERS[TIERS.index(start) :]) if tier == "auto" else [tier]
        # The verifier can escalate; routing never permanently gates a channel.
        calls = 0
        usage: list[dict[str, Any]] = []
        details: dict[str, Any] = {}
        for current in route:
            checkpoint(cancelled)
            if emit:
                emit("progress", {"stage": "retrieving", "tier": current})
            hits, details = self.retriever.retrieve(
                rewritten, top_k, documents, page_range, current
            )
            if not hits or details["missing_documents"]:
                continue
            images, evidence, sources = [], [], []
            try:
                for hit in hits:
                    checkpoint(cancelled)
                    payload = hit["payload"]
                    version, path = self.source(payload["version_id"])
                    page = payload["page_number"]
                    if (
                        version["document_id"] != payload["document_id"]
                        or not 1 <= page <= version["page_count"]
                    ):
                        raise ValueError("Evidence source/version mismatch")
                    images.append(self.loader.load_page(path, page))
                    evidence.append(
                        {
                            "id": hit["evidence_id"],
                            "document": version["filename"],
                            "version_id": version["id"],
                            "page": page,
                            "text": payload.get("text", ""),
                        }
                    )
                    sources.append(
                        {
                            "evidence_id": hit["evidence_id"],
                            "source": version["filename"],
                            "document_id": version["document_id"],
                            "version_id": version["id"],
                            "page": page,
                            "build_id": payload["build_id"],
                            "score": hit["score"],
                            "score_kind": hit.get("score_kind"),
                            "channels": payload.get("channels", []),
                        }
                    )
                calls += 1
                try:
                    checkpoint(cancelled)
                    if emit:
                        emit("progress", {"stage": "generating", "tier": current})
                        emit(
                            "answer-delta",
                            {"text": "", "reset": True, "provisional": True},
                        )
                    if emit and callable(
                        getattr(type(self.generator), "generate_grounded_stream", None)
                    ):
                        raw = self.generator.generate_grounded_stream(
                            rewritten,
                            evidence,
                            images,
                            lambda text: emit(
                                "answer-delta", {"text": text, "provisional": True}
                            ),
                            cancelled,
                        )
                    else:
                        raw = self.generator.generate_grounded(
                            rewritten, evidence, images
                        )
                    checkpoint(cancelled)
                    if emit:
                        emit("progress", {"stage": "validating"})
                    latest = getattr(self.generator, "last_usage", None)
                    if isinstance(latest, dict):
                        usage.append(latest)
                    result = validate_answer(raw, {e["id"] for e in evidence})
                    cited = {c for claim in result.claims for c in claim.citations}
                    cited_documents = {
                        s["document_id"] for s in sources if s["evidence_id"] in cited
                    }
                    if documents and not set(documents).issubset(cited_documents):
                        result = GroundedAnswer(status="insufficient")
                except (ValueError, TypeError):
                    result = GroundedAnswer(status="insufficient")
                if result.status != "insufficient":
                    cited = {c for claim in result.claims for c in claim.citations}
                    return {
                        "answer": "\n\n".join(
                            claim.text
                            + " "
                            + " ".join(f"[{c}]" for c in claim.citations)
                            for claim in result.claims
                        ),
                        "sources": [s for s in sources if s["evidence_id"] in cited],
                        "claims": [c.model_dump() for c in result.claims],
                        "grounding_status": result.status,
                        "original_query": query,
                        "retrieval_query": rewritten,
                        "retrieval": details,
                        "provider_calls": calls,
                        "provider_usage": usage,
                        "support_validation": "reference IDs checked; semantic support "
                        "unverified",
                    }
            finally:
                for image in images:
                    image.close()
            if calls >= self.max_provider_calls:
                break
        return {
            "answer": "The available evidence is insufficient to answer this "
            "question reliably.",
            "sources": [],
            "claims": [],
            "grounding_status": "insufficient",
            "original_query": query,
            "retrieval_query": rewritten,
            "retrieval": details,
            "provider_calls": calls,
            "provider_usage": usage,
            "support_validation": "no factual answer published",
        }
