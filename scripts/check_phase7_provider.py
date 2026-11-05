"""Opt-in live streaming check and resumable prompted-router baseline.

Uses fictional evidence and cached Phase 4 samples, never the user's library.
Stops at the first provider error and records its type/code without raw errors.
"""

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter, sleep

from vision_rag.config import settings
from vision_rag.models.gemini_generator import GeminiGenerator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-router", action="store_true")
    parser.add_argument("--delay", type=float, default=12)
    args = parser.parse_args()
    output = Path("docs/phase7-provider.json")
    report = {
        "model": settings.generation_model_name,
        "attempts": 1,
        "dollar_cost": None,
        "cost_note": "No verified account billing rate",
        "stream": {},
        "router": [],
    }
    if output.exists():
        report = json.loads(output.read_text(encoding="utf-8"))
    if report.get("model") != settings.generation_model_name:
        raise ValueError("Use a separate report when changing the provider model")
    provider = GeminiGenerator(
        settings.generation_model_name,
        settings.provider_api_key,
        timeout_ms=30000,
        attempts=1,
    )

    def save():
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    try:
        if report["stream"].get("status") != "passed":
            from PIL import Image, ImageDraw

            image = Image.new("RGB", (900, 400), "white")
            ImageDraw.Draw(image).text(
                (30, 40),
                "Fictional release fixture: revenue 120 million EUR.",
                fill="black",
                font_size=26,
            )
            evidence = [
                {
                    "id": "E1",
                    "source": "fictional-release.pdf",
                    "page": 1,
                    "excerpt": "Fictional release fixture: revenue 120 million EUR.",
                }
            ]
            deltas, first = [], []
            started = perf_counter()

            def delta(value):
                if value:
                    first.append(perf_counter() - started)
                    deltas.append(value)

            try:
                result = provider.generate_grounded(
                    "What revenue is reported?", evidence, [image], on_delta=delta
                )
            finally:
                image.close()
            valid = result["status"] == "supported" and bool(result["claims"])
            valid = valid and all(c["citations"] == ["E1"] for c in result["claims"])
            valid = valid and "120" in " ".join(c["text"] for c in result["claims"])
            report["stream"] = {
                "status": "passed" if valid and deltas else "failed",
                "first_claim_delta_seconds": first[0] if first else None,
                "completion_seconds": perf_counter() - started,
                "delta_count": len(deltas),
                "result": result,
                "usage": provider.last_usage,
                "scope": "provider adapter; not browser end-to-end latency",
            }
            save()
        if args.resume_router:
            baseline = json.loads(Path("docs/phase4-evaluation.json").read_text())
            if not report["router"]:
                report["router"] = baseline["provider"]["router"].copy()
            samples = [s for s in baseline["samples"] if s["split"] == "test"]
            for sample in samples:
                if sample["id"] in {r["id"] for r in report["router"]}:
                    continue
                sleep(max(0, args.delay))
                started = perf_counter()
                tier = provider.route_query(sample["query"])
                report["router"].append(
                    {
                        "id": sample["id"],
                        "tier": tier,
                        "seconds": perf_counter() - started,
                        "usage": provider.last_usage,
                    }
                )
                save()
                print("routed", len(report["router"]), "/", len(samples), flush=True)
            report["router_status"] = "complete"
            report["mean_router_seconds"] = mean(r["seconds"] for r in report["router"])
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
        save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "stream": report["stream"].get("status"),
                "routes": len(report["router"]),
            }
        )
    )


if __name__ == "__main__":
    main()
