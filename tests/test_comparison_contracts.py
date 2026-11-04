import pytest

from vision_rag.analysis.contracts import ComparisonRequest, validate_table
from vision_rag.storage.findings import Findings
from vision_rag.storage.metadata import Metadata


def test_matrix_preserves_units_and_rejects_cross_version_or_missing_facts():
    request = ComparisonRequest(
        question="Compare revenue", version_ids=["v1", "v2"], fields=["Revenue"]
    )
    cells = [
        {
            "version_id": "v1",
            "field": "Revenue",
            "status": "reported",
            "value": "1,200",
            "currency": "EUR",
            "period": "FY2025",
            "scope": "Consolidated",
            "citations": ["E1"],
        },
        {"version_id": "v2", "field": "Revenue", "status": "missing"},
    ]
    sources = [{"evidence_id": "E1", "version_id": "v1"}]
    table = validate_table({"cells": cells}, request, sources)
    assert table.cells[0].value == "1,200" and table.cells[0].currency == "EUR"
    with pytest.raises(ValueError):
        validate_table({"cells": cells[:1]}, request, sources)
    with pytest.raises(ValueError):
        validate_table({"cells": [cells[0], cells[0]]}, request, sources)
    with pytest.raises(ValueError):
        validate_table(
            {"cells": cells}, request, [{"evidence_id": "E1", "version_id": "v2"}]
        )
    with pytest.raises(ValueError):
        validate_table(
            {"cells": [cells[0], {**cells[1], "value": "invented"}]}, request, sources
        )


def test_findings_persist_without_mutating_content_and_enforce_workspace(tmp_path):
    path = tmp_path / "library.sqlite"
    store = Findings(Metadata(path, "one"))
    draft = store.create(
        "Comparison", "comparison", {"answer": "sample", "sources": []}
    )
    assert not store.all()
    saved = store.update(draft["id"], reviewed=True, save=True)
    reopened = Findings(Metadata(path, "one")).get(saved["id"])
    assert reopened["content_hash"] == draft["content_hash"] and reopened["reviewed"]
    other = Findings(Metadata(path, "two"))
    assert not other.all()
    with pytest.raises(KeyError):
        other.update(saved["id"], title="Hijacked")
    store.clear_drafts()
    assert store.get(saved["id"])["state"] == "saved"
    store.delete(saved["id"])
    assert not store.all()
