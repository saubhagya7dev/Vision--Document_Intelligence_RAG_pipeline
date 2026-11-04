import csv
import io
import json

from vision_rag.analysis.exports import csv_text, export_finding


def test_exports_preserve_original_values_and_escape_untrusted_content():
    value = '=HYPERLINK("https://example.invalid", "value")'
    content = {
        "question": "<script>alert(1)</script>",
        "answer": "Comparison",
        "versions": [{"id": "v1", "filename": "<img src=x>.pdf", "ordinal": 1}],
        "sources": [
            {"evidence_id": "E1", "source": "report.pdf", "version_id": "v1", "page": 2}
        ],
        "table": {
            "cells": [
                {
                    "version_id": "v1",
                    "field": "Revenue | total",
                    "status": "reported",
                    "value": value,
                    "citations": ["E1"],
                }
            ]
        },
        "verification": {"references": "validated", "semantic_support": "unverified"},
    }
    finding = {
        "id": "finding",
        "title": "Report",
        "content_hash": "hash",
        "reviewed": False,
        "content": content,
    }
    text, _ = export_finding(finding, "csv", "http://localhost:8000")
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["value"].startswith("'=")
    assert json.loads(row["value_json"]) == value
    assert json.loads(row["source_links"])[0]["original_url"].endswith(
        "/v1/file#page=2"
    )
    markdown, _ = export_finding(finding, "md", "http://localhost:8000")
    assert "<script>" not in markdown and "<img" not in markdown
    assert "Revenue \\| total" in markdown
    raw, _ = export_finding(finding, "json", "http://localhost:8000")
    assert json.loads(raw)["content"]["table"]["cells"][0]["value"] == value
    for prefix in ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋"):
        assert csv_text(prefix + "payload").startswith("'")
