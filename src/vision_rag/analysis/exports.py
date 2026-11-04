"""Portable finding exports with immutable source IDs and explicit verification."""

import csv
import html
import io
import json
import re
import unicodedata
from typing import Any
from urllib.parse import quote, urlsplit


def source_links(content: dict[str, Any], origin: str) -> list[dict[str, Any]]:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", parsed.netloc)
    ):
        raise ValueError("Export source origin must be an HTTP host")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return [
        {
            **source,
            "preview_url": f"{origin}/api/v1/versions/"
            f"{quote(source['version_id'], safe='')}/pages/{source['page']}",
            "original_url": f"{origin}/api/v1/versions/"
            f"{quote(source['version_id'], safe='')}/file#page={source['page']}",
        }
        for source in content.get("sources", [])
    ]


def csv_text(value: Any) -> str:
    text = "" if value is None else str(value)
    # Protect human spreadsheet imports; JSON and value_json preserve exact values.
    first = unicodedata.normalize("NFKC", text.lstrip())[:1]
    if first in ("=", "+", "-", "@") or text[:1] in ("\t", "\r", "\n"):
        return "'" + text
    return text


def markdown_text(value: Any) -> str:
    text = "Not stated" if value is None else str(value)
    text = html.escape(text).replace("\r", " ").replace("\n", " / ")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>\-])", r"\\\1", text)


def export_finding(
    finding: dict[str, Any], format: str, origin: str
) -> tuple[str, str]:
    content = finding["content"]
    links = source_links(content, origin.rstrip("/"))
    refs = {s["evidence_id"]: s for s in links}
    if format == "json":
        return json.dumps(
            {"export_schema_version": 1, **finding, "source_links": links},
            ensure_ascii=False,
            indent=2,
        ), "application/json"
    versions = {v["id"]: v for v in content.get("versions", [])}
    cells = content.get("table", {}).get("cells")
    if cells is None:
        cells = [
            {
                "field": "Answer",
                "version_id": "",
                "status": content.get("grounding_status", "saved"),
                "value": c["text"],
                "citations": c["citations"],
            }
            for c in content.get("claims", [])
        ]
        if not cells:
            cells = [
                {
                    "field": "Answer",
                    "version_id": "",
                    "status": "insufficient",
                    "value": content.get("answer", ""),
                    "citations": [],
                }
            ]
    if format == "csv":
        output = io.StringIO(newline="")
        columns = [
            "finding_id",
            "title",
            "question",
            "field",
            "version_id",
            "document_id",
            "filename",
            "version_ordinal",
            "status",
            "value",
            "value_json",
            "unit",
            "currency",
            "period",
            "scope",
            "citation_ids",
            "source_links",
            "reference_validation",
            "semantic_support",
            "user_reviewed",
            "content_hash",
        ]
        writer = csv.DictWriter(output, columns, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for cell in cells:
            version = versions.get(cell["version_id"], {})
            citations = cell["citations"]
            row = {
                "finding_id": finding["id"],
                "title": finding["title"],
                "question": content.get("question", ""),
                **cell,
                "document_id": version.get("document_id", ""),
                "filename": version.get("filename", ""),
                "version_ordinal": version.get("ordinal", ""),
                "value_json": json.dumps(cell.get("value"), ensure_ascii=False),
                "citation_ids": json.dumps(citations),
                "source_links": json.dumps(
                    [refs[c] for c in citations], ensure_ascii=False
                ),
                "reference_validation": content["verification"]["references"],
                "semantic_support": content["verification"]["semantic_support"],
                "user_reviewed": finding["reviewed"],
                "content_hash": finding["content_hash"],
            }
            writer.writerow({key: csv_text(row.get(key)) for key in columns})
        return output.getvalue(), "text/csv"
    lines = [
        f"# {markdown_text(finding['title'])}",
        "",
        f"Finding: `{finding['id']}` · Content SHA256: `{finding['content_hash']}`",
        "",
        f"Question: {markdown_text(content.get('question', ''))}",
        "",
        f"{markdown_text(content.get('answer', ''))}",
        "",
        "Reference IDs validated; semantic support remains unverified. "
        f"User marked reviewed: {finding['reviewed']}.",
        "",
        "Values retain reported units, currency, period and scope. "
        "Missing means not found in retrieved evidence, not document-wide absence.",
        "",
        "| Field | Document version | Status | Value | Unit | Currency | "
        "Period | Scope | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in cells:
        v = versions.get(cell["version_id"], {})
        label = (
            f"{v.get('filename', '')} · v{v.get('ordinal', '')} ({cell['version_id']})"
        )
        citations = ", ".join(
            f"[{markdown_text(c)}]({refs[c]['original_url']})"
            for c in cell["citations"]
        )
        values = [
            cell["field"],
            label,
            cell["status"],
            cell.get("value"),
            cell.get("unit"),
            cell.get("currency"),
            cell.get("period"),
            cell.get("scope"),
        ]
        lines.append(
            "| " + " | ".join(markdown_text(v) for v in values) + f" | {citations} |"
        )
    lines.extend(["", "## Source manifest", ""])
    for context in content.get("comparability", []):
        if context["different_reported_context"]:
            lines.append(
                f"- {markdown_text(context['field'])}: differing reported context: "
                f"{markdown_text(', '.join(context['different_reported_context']))}. "
                "No normalization applied."
            )
    for source in links:
        lines.append(
            f"- {markdown_text(source['evidence_id'])}: "
            f"{markdown_text(source['source'])}, version `{source['version_id']}`, "
            f"page {source['page']}. [Preview]({source['preview_url']}) · "
            f"[Original]({source['original_url']})"
        )
    return "\n".join(lines) + "\n", "text/markdown"
