import io

from test_hybrid import close
from test_phase4_indexes import prepare

from vision_rag.analysis.comparison import ComparisonEngine
from vision_rag.analysis.contracts import ComparisonRequest
from vision_rag.retrieval.engine import HybridRetriever


class Provider:
    last_usage = {}

    def generate_comparison(self, request, evidence, images):
        assert len(images) == len(evidence) <= 6
        cells = []
        for version in request["version_ids"]:
            refs = [e["id"] for e in evidence if e["version_id"] == version]
            for field in request["fields"]:
                if refs and field == "Revenue":
                    cells.append(
                        {
                            "version_id": version,
                            "field": field,
                            "status": "reported",
                            "value": "120",
                            "unit": "units",
                            "period": "FY2025",
                            "scope": "Reported total",
                            "citations": refs[:1],
                        }
                    )
                else:
                    cells.append(
                        {"version_id": version, "field": field, "status": "missing"}
                    )
        return {"cells": cells}


def test_old_versions_are_explicitly_retrievable_without_entering_default_search(
    tmp_path,
):
    lib, store, manager, models, first = prepare(tmp_path)
    try:
        manager.queue()
        lib.process_one()
        first_index = manager.active()
        original = lib.source(first["version_id"])[1].read_bytes()
        second = lib.upload(
            io.BytesIO(original + b"\n% revised report"),
            "report.pdf",
            replace_document=first["document_id"],
        )
        lib.process_one()
        manager.queue()
        lib.process_one()
        assert not any(manager.eligible(first_index).values())
        selected, _ = HybridRetriever(manager).retrieve(
            "ALPHA42", version_ids=[first["version_id"]], index_id=first_index["id"]
        )
        assert selected and selected[0]["payload"]["version_id"] == first["version_id"]
        result = ComparisonEngine(lib, Provider()).run(
            ComparisonRequest(
                question="Compare ALPHA42",
                version_ids=[first["version_id"], second["version_id"]],
                fields=["Revenue", "Unstated metric"],
            )
        )
        assert len(result["table"]["cells"]) == 4
        assert sum(c["status"] == "missing" for c in result["table"]["cells"]) == 2
        assert {s["version_id"] for s in result["sources"]} == {
            first["version_id"],
            second["version_id"],
        }
        assert result["verification"]["semantic_support"] == "unverified"
    finally:
        close(lib, store)
