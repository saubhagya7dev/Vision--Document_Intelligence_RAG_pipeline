"""Report release gates from recorded checks; missing evidence fails closed."""

import argparse
import json
from pathlib import Path


def gates(root: Path):
    def read(name):
        path = root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    checks = read("phase7-verification.json")
    public = read("phase7-retrieval.json")
    internal = read("phase7-internal.json")
    provider = read("phase7-provider.json")
    audit = read("phase7-dependencies.json")
    result = {
        "routine_checks": checks.get("routine_checks_passed") is True,
        "backup_restore": checks.get("backup_restore_passed") is True,
        "owner_browser": checks.get("owner_browser_passed") is True,
        "wheel_smoke": checks.get("wheel_smoke_passed") is True,
        "public_retrieval_measured": public.get("status") == "measured_smoke_only",
        "internal_retrieval_measured": internal.get("status") == "measured_smoke_only",
        "live_stream": provider.get("stream", {}).get("status") == "passed",
        "prompted_router_complete": provider.get("router_status") == "complete",
        "dependency_advisories_resolved": audit.get("after_advisories") == 0,
        "container_runtime": checks.get("container_runtime_passed") is True,
        "shared_tls_deployment": checks.get("shared_tls_passed") is True,
        "representative_answer_quality": checks.get("answer_quality_passed") is True,
        "independent_semantic_support": checks.get("semantic_support_passed") is True,
        "rtx3050_measurements": checks.get("rtx3050_measured") is True,
        "human_verification_time": checks.get("human_timing_measured") is True,
    }
    return {
        "gates": result,
        "release_ready": all(result.values()),
        "note": "Smoke tests are not broad quality approval. Recorded checks apply "
        "to their recorded source revision and environment; rerun after changes.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=Path("Docs"))
    parser.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    result = gates(args.docs)
    (args.docs / "phase7-release-gates.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    if args.require_release and not result["release_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
