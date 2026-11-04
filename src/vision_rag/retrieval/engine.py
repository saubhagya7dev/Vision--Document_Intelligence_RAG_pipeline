"""Scoped dense/lexical/visual retrieval with bounded page evidence."""

import json
from typing import Any

from vision_rag.ingest.text import lexical_terms
from vision_rag.retrieval.indexes import RetrievalIndexes
from vision_rag.retrieval.scoring import fuse
from vision_rag.storage.metadata import Conflict, identity

TIERS = ("text", "visual", "hybrid", "rerank")


class HybridRetriever:
    def __init__(
        self,
        indexes: RetrievalIndexes,
        candidates: int = 30,
        char_budget: int = 14000,
        fusion: str = "borda",
    ) -> None:
        self.indexes, self.candidates = indexes, candidates
        self.char_budget, self.fusion = char_budget, fusion

    def lexical(
        self, row: dict[str, Any], allowed: list[str], query: str
    ) -> list[dict[str, Any]]:
        terms = lexical_terms(query)
        if not terms or not allowed:
            return []
        match = " OR ".join('"' + term + '"' for term in terms)
        records = self.indexes.meta.rows(
            "SELECT point_id,rank FROM retrieval_search WHERE retrieval_search MATCH ? "
            "AND index_id=? AND point_id IN (SELECT value FROM json_each(?)) "
            "ORDER BY rank LIMIT ?",
            (match, row["id"], json.dumps(allowed), self.candidates),
        )
        if not records:
            return []
        store = self.indexes.store(row)
        with store.base.lock:
            payloads = {
                str(p.id): p.payload or {}
                for p in store.base.client.retrieve(
                    store.text, [r["point_id"] for r in records], with_payload=True
                )
            }
        return [
            {
                "id": r["point_id"],
                "score": r["rank"],
                "score_kind": "lexical_bm25",
                "payload": {**payloads[r["point_id"]], "channel": "lexical"},
            }
            for r in records
            if r["point_id"] in payloads
        ]

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        documents: list[str] | None = None,
        page_range: tuple[int, int] | None = None,
        tier: str = "hybrid",
        fusion: str | None = None,
        version_ids: list[str] | None = None,
        index_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        row = self.indexes.row(index_id) if index_id else self.indexes.active()
        if row is None or row["state"] != "ready":
            raise Conflict("Retrieval index is preparing; inspect indexing progress")
        if tier not in TIERS:
            raise ValueError("Unknown retrieval tier")
        if documents is not None and len(documents) > min(top_k, 6):
            raise ValueError(
                "Select enough source pages to cover all requested documents"
            )
        spec = json.loads(row["specification"])
        allowed = self.indexes.eligible(row, documents, page_range, version_ids)
        channels: list[list[dict[str, Any]]] = []
        if tier in ("text", "hybrid", "rerank") and allowed["text"]:
            # Queries must respect the same tokenizer budget; never truncate silently.
            vector = self.indexes.models.encode_text(spec, [query], True)[0]
            dense = self.indexes.store(row).search(
                vector, allowed["text"], self.candidates, "text"
            )
            lexical = self.lexical(row, allowed["text"], query)
            channels.extend([dense, lexical])
        if tier in ("visual", "hybrid", "rerank") and allowed["visual"]:
            tokens = self.indexes.models.encode_visual(spec, [query], False)[0]
            visual = self.indexes.store(row).search(
                tokens,
                allowed["visual"],
                self.candidates,
                "visual",
                tier == "rerank",
                self.candidates,
            )
            channels.append(visual)
        # Separate per-document retrieval prevents a dominant report monopolizing
        # a comparison candidate pool. At most six explicitly selected documents.
        required = documents or []
        for document in required:
            if not any(
                h["payload"]["document_id"] == document for ch in channels for h in ch
            ):
                one = self.indexes.eligible(row, [document], page_range)
                if one["text"] and tier != "visual":
                    vector = self.indexes.models.encode_text(spec, [query], True)[0]
                    channels.append(
                        self.indexes.store(row).search(vector, one["text"], 2, "text")
                    )
                if one["visual"] and tier != "text":
                    tokens = self.indexes.models.encode_visual(spec, [query], False)[0]
                    channels.append(
                        self.indexes.store(row).search(
                            tokens, one["visual"], 2, "visual"
                        )
                    )
        ranked = fuse(
            channels, fusion or self.fusion, self.candidates * max(1, len(required))
        )
        selected = select_evidence(ranked, min(top_k, 6), required, self.char_budget)
        missing = [
            d
            for d in required
            if d not in {h["payload"]["document_id"] for h in selected}
        ]
        return selected, {
            "index_id": row["id"],
            "profile": row["profile"],
            "tier": tier,
            "fusion": fusion or self.fusion,
            "missing_documents": missing,
            "index_stale": row["snapshot"] != self.indexes.snapshot(),
        }


def select_evidence(
    ranked: list[dict[str, Any]], top_k: int, required: list[str], budget: int
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for hit in ranked:
        payload = hit["payload"]
        key = (payload["version_id"], payload["page_number"])
        if key not in grouped:
            grouped[key] = {
                **hit,
                "payload": {**payload, "text": "", "chunk_ids": [], "channels": []},
            }
        target = grouped[key]["payload"]
        channel = payload.get("channel", "visual")
        if channel not in target["channels"]:
            target["channels"].append(channel)
        chunk = payload.get("chunk_id")
        if chunk and chunk not in target["chunk_ids"] and len(target["chunk_ids"]) < 3:
            target["chunk_ids"].append(chunk)
            target["text"] += payload.get("text", "") + "\n"
    ordered = list(grouped.values())
    selected: list[dict[str, Any]] = []
    for doc in required:
        candidate = next(
            (h for h in ordered if h["payload"]["document_id"] == doc), None
        )
        if candidate is not None and candidate not in selected:
            selected.append(candidate)
    selected.extend(h for h in ordered if h not in selected)
    output: list[dict[str, Any]] = []
    remaining = budget
    for hit in selected[:top_k]:
        payload = hit["payload"]
        allocation = remaining // max(1, min(len(selected), top_k) - len(output))
        payload["text_truncated"] = len(payload["text"]) > allocation
        payload["text"] = payload["text"][: max(0, allocation)]
        remaining -= len(payload["text"])
        evidence = identity(
            f"{payload['version_id']}:{payload['page_number']}:"
            + ":".join(sorted(payload["chunk_ids"]))
        )
        hit["evidence_id"] = "E" + evidence.replace("-", "")[:16]
        output.append(hit)
    return output
