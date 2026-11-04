"""Retrieve each explicitly selected version and validate every table cell."""

from typing import Any

from vision_rag.analysis.contracts import ComparisonRequest, validate_table
from vision_rag.retrieval.engine import HybridRetriever
from vision_rag.storage.metadata import Conflict, now


class ComparisonEngine:
    def __init__(
        self, library: Any, generator: Any, candidates: int = 30, budget: int = 14000
    ) -> None:
        self.library, self.generator = library, generator
        self.candidates, self.budget = candidates, budget

    def run(self, request: ComparisonRequest) -> dict[str, Any]:
        library, manager = self.library, self.library.retrieval
        if manager is None:
            raise Conflict("Enable Phase 4 retrieval before creating comparisons")
        library.check_available()
        versions = [library.source(key)[0] for key in request.version_ids]
        sources, evidence, images, retrieval = [], [], [], []
        query = request.question + "\nFields: " + "; ".join(request.fields)
        pages = min(2, 6 // len(versions))
        try:
            for version in versions:
                hits: list[dict[str, Any]] = []
                for index in manager.revisions():
                    if index["state"] != "ready":
                        continue
                    eligible = manager.eligible(index, versions=[version["id"]])
                    if not any(eligible.values()):
                        continue
                    hits, details = HybridRetriever(
                        manager, self.candidates, self.budget // len(versions)
                    ).retrieve(
                        query, pages, version_ids=[version["id"]], index_id=index["id"]
                    )
                    retrieval.append({"version_id": version["id"], **details})
                    break
                if not hits:
                    retrieval.append(
                        {
                            "version_id": version["id"],
                            "state": "missing",
                            "reason": "No eligible evidence in a retained ready index",
                        }
                    )
                for hit in hits:
                    payload = hit["payload"]
                    if payload["version_id"] != version["id"]:
                        raise ValueError(
                            "Retrieval crossed the selected version boundary"
                        )
                    page = payload["page_number"]
                    _, path = library.source(version["id"])
                    images.append(library.loader.load_page(path, page))
                    source = {
                        "evidence_id": hit["evidence_id"],
                        "source": version["filename"],
                        "document_id": version["document_id"],
                        "version_id": version["id"],
                        "page": page,
                        "build_id": payload["build_id"],
                        "excerpt": payload.get("text", ""),
                    }
                    sources.append(source)
                    evidence.append({"id": source["evidence_id"], **source})
            if evidence:
                raw = self.generator.generate_comparison(
                    request.model_dump(), evidence, images
                )
            else:
                raw = {
                    "cells": [
                        {"version_id": v, "field": f, "status": "missing"}
                        for v in request.version_ids
                        for f in request.fields
                    ]
                }
            table = validate_table(raw, request, sources)
            cited = {c for cell in table.cells for c in cell.citations}
            missing = sum(cell.status == "missing" for cell in table.cells)
            comparability = []
            for field in request.fields:
                cells = [
                    c for c in table.cells if c.field == field and c.status != "missing"
                ]
                dimensions = ("unit", "currency", "period", "scope")
                comparability.append(
                    {
                        "field": field,
                        "different_reported_context": [
                            k
                            for k in dimensions
                            if len(
                                {
                                    getattr(c, k)
                                    for c in cells
                                    if getattr(c, k) is not None
                                }
                            )
                            > 1
                        ],
                        "unstated_context": [
                            k
                            for k in dimensions
                            if any(getattr(c, k) is None for c in cells)
                        ],
                    }
                )
            return {
                "schema_version": 1,
                "question": request.question,
                "answer": f"Compared {len(request.fields)} fields across "
                f"{len(versions)} versions. {missing} cells lack supported values "
                "in retrieved evidence.",
                "fields": request.fields,
                "comparability": comparability,
                "versions": [
                    {
                        k: v[k]
                        for k in (
                            "id",
                            "document_id",
                            "filename",
                            "ordinal",
                            "content_hash",
                            "page_count",
                        )
                    }
                    for v in versions
                ],
                "table": table.model_dump(),
                "sources": [s for s in sources if s["evidence_id"] in cited],
                "retrieval": retrieval,
                "created_at": now(),
                "verification": {
                    "references": "validated",
                    "semantic_support": "unverified",
                },
                "provider_usage": getattr(self.generator, "last_usage", {}),
            }
        finally:
            for image in images:
                image.close()
