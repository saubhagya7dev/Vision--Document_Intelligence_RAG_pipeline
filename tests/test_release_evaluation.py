import json

import pypdfium2 as pdfium
import pytest

from scripts.check_release import fingerprint, gates
from scripts.evaluate_phase7 import metrics
from scripts.phase7_corpus import create


def test_ranking_metrics_distinguish_partial_and_complete_coverage():
    value = metrics(["noise", "a", "b"], {"a": 2, "b": 1, "c": 1})
    assert value["recall_at_3"] == pytest.approx(2 / 3)
    assert value["complete_coverage_at_3"] == 0
    assert value["mrr"] == 0.5
    assert 0 < value["ndcg_at_3"] < 1
    assert metrics(["a"], {"a": 2})["ndcg_at_3"] == 1
    assert metrics(["157"], {157: 2})["recall_at_3"] == 1


def test_release_gates_fail_closed_without_measurements(tmp_path):
    result = gates(tmp_path)
    assert result["release_ready"] is False
    assert not any(result["gates"].values())
    project = tmp_path / "project"
    docs = project / "Docs"
    docs.mkdir(parents=True)
    config = project / "pyproject.toml"
    config.write_text("first configuration")
    (docs / "phase7-verification.json").write_text(
        json.dumps({"source_fingerprint": fingerprint(project)})
    )
    assert gates(docs)["gates"]["source_matches_verification"] is True
    config.write_text("changed configuration")
    assert gates(docs)["gates"]["source_matches_verification"] is False


def test_demo_sources_and_gold_pages_are_reproducible_and_resolvable(tmp_path):
    manifest, sources = create(tmp_path)
    first_hashes = manifest["sources"]
    assert create(tmp_path)[0]["sources"] == first_hashes
    ids = {str(p["corpus_id"]) for p in manifest["pages"]}
    for page in manifest["pages"]:
        with pdfium.PdfDocument(sources[page["doc_id"]]) as document:
            assert 1 <= page["page_number_in_doc"] <= len(document)
    for query in manifest["queries"]:
        assert set(query["gold"]).issubset(ids)
    assert {t["kind"] for t in manifest["product_tasks"]} >= {
        "unanswerable",
        "version_change",
        "prompt_injection",
        "multi_page",
    }
