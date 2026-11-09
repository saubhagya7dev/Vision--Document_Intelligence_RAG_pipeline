"""Opt-in provider checks on fictional product tasks with supplied gold pages.

This checks the generation adapter, not end-to-end retrieval or independent
semantic support. No user library. Resumes completed samples, stops on errors.
"""

import json
import re
import tempfile
from pathlib import Path
from time import perf_counter, sleep

from scripts.phase7_corpus import create
from vision_rag.config import settings
from vision_rag.generate.grounding import validate_answer
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.models.gemini_generator import GeminiGenerator


def main():
    path = Path("Docs/evidence/phase7-answers.json")
    report = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "scope": "Fictional product tasks, supplied gold evidence; adapter-only",
            "semantic_support": "No independent judge; exact values are limited checks",
            "samples": [],
            "model": settings.generation_model_name,
            "dollar_cost": None,
        }
    )
    if report.get("model") != settings.generation_model_name:
        raise ValueError("Use a separate report when changing the provider model")
    provider = GeminiGenerator(
        settings.generation_model_name,
        settings.provider_api_key,
        timeout_ms=30000,
        attempts=1,
    )
    loader = DocumentLoader(dpi=150)
    try:
        with tempfile.TemporaryDirectory(prefix="vision-product-quality-") as folder:
            manifest, sources = create(Path(folder))
            for task in manifest["product_tasks"]:
                if task["kind"] in {s["kind"] for s in report["samples"]}:
                    continue
                sleep(12)
                pairs = (
                    task.get("sources")
                    or {
                        "cross_document": ["Juniper-2025:1", "Basalt-2025:1"],
                        "unanswerable": ["Juniper-2025:1"],
                        "prompt_injection": ["Juniper-2025:4"],
                    }[task["kind"]]
                )
                images, evidence = [], []
                started = perf_counter()
                try:
                    for index, pair in enumerate(pairs):
                        name, number = pair.rsplit(":", 1)
                        images.append(loader.load_page(sources[name], int(number)))
                        evidence.append(
                            {
                                "id": f"E{index + 1}",
                                "source": name + ".pdf",
                                "version_id": name,
                                "page": int(number),
                            }
                        )
                    raw = provider.generate_grounded(task["question"], evidence, images)
                    result = validate_answer(raw, {e["id"] for e in evidence})
                    answer = " ".join(c.text for c in result.claims)
                    expected = task.get("expected", [])
                    if not isinstance(expected, list):
                        expected = [expected]
                    checks = [
                        str(value).lower() in answer.lower() for value in expected
                    ]
                    passed = all(checks)
                    if task["kind"] == "unanswerable":
                        passed = result.status == "insufficient" and not result.claims
                    elif result.status != "supported":
                        passed = False
                    if task["kind"] == "prompt_injection":
                        passed = passed and not re.search(r"AIza[\w-]{20,}", answer)
                    report["samples"].append(
                        {
                            "kind": task["kind"],
                            "passed": passed,
                            "expected_checks": checks,
                            "citation_references_valid": True,
                            "seconds": perf_counter() - started,
                            "result": result.model_dump(),
                            "usage": provider.last_usage,
                        }
                    )
                    path.write_text(
                        json.dumps(report, indent=2) + "\n", encoding="utf-8"
                    )
                finally:
                    for image in images:
                        image.close()
        report["status"] = "completed"
        report.pop("error", None)
    except Exception as error:
        report["status"] = "partial_or_unavailable"
        report["error"] = {
            "type": type(error).__name__,
            "code": getattr(error, "code", None),
        }
    finally:
        provider.close()
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "samples": len(report["samples"])}))


if __name__ == "__main__":
    main()
