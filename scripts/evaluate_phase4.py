"""Real-model evaluation on fictional, disjoint source families. No user PDFs.

Run with --provider for measured LLM routing, answers, and sampled support checks.
Persistent workdir permits resuming model/index work without repeating ingestion.
"""

import argparse
import io
import json
from pathlib import Path
from statistics import mean
from time import perf_counter, sleep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--work-dir", type=Path, default=Path(".tools/phase4-evaluation")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("Docs/phase4-evaluation.json")
    )
    parser.add_argument("--provider", action="store_true")
    parser.add_argument("--provider-only", action="store_true")
    parser.add_argument("--enrich-baseline", action="store_true")
    parser.add_argument("--provider-delay", type=float, default=12)
    args = parser.parse_args()

    import torch
    from phase4_corpus import FAMILIES, create

    from vision_rag.config import settings
    from vision_rag.generate.grounding import GroundedSynthesizer
    from vision_rag.ingest.document_loader import DocumentLoader
    from vision_rag.ingest.pipeline import IngestionPipeline
    from vision_rag.models.pooled_adapter import PooledAdapter
    from vision_rag.models.retrieval_models import RetrievalModels
    from vision_rag.retrieval.engine import TIERS, HybridRetriever
    from vision_rag.retrieval.indexes import RetrievalIndexes
    from vision_rag.retrieval.retriever import Retriever
    from vision_rag.retrieval.router import CostRouter, heuristic
    from vision_rag.retrieval.scoring import maxsim
    from vision_rag.runtime import device_diagnostics
    from vision_rag.storage.library import DocumentLibrary
    from vision_rag.vector_stores.qdrant_store import QdrantVectorStore

    root = args.work_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    questions = create(root / "corpus")
    (root / "manifest.json").write_text(json.dumps(questions, indent=2) + "\n")
    report = {
        "hardware": device_diagnostics(),
        "model_profile": None,
        "dpi": 150,
        "dataset": {
            "kind": "fictional synthetic",
            "questions": len(questions),
            "families": [{"split": f[0], "family": f[1]} for f in FAMILIES],
            "ocr": "disabled consistently; scan retrieval requires visual evidence",
            "limits": "small generated corpus, not real-world held-out answer quality",
        },
        "provider": {"status": "not_run", "dollar_cost": None},
        "samples": [],
        "policies": {},
    }
    if args.provider_only:
        report = json.loads(args.output.read_text(encoding="utf-8"))
    spec = {**settings.retrieval_specification, "dpi": 150}
    libroot = root / "library"
    models = RetrievalModels(
        settings.embedding_device,
        settings.embedding_precision,
        libroot / "artifacts/visual_tokens",
    )
    loader = DocumentLoader(dpi=150, cache_dir=libroot / "artifacts")
    store = QdrantVectorStore(path=libroot / "qdrant")
    pipeline = IngestionPipeline(loader, PooledAdapter(models, spec), store, 1)
    lib = DocumentLibrary(
        libroot, loader, store, lambda: pipeline, "evaluation-pooled-150", hybrid=True
    )
    manager = RetrievalIndexes(lib, models, spec)
    lib.retrieval = manager
    provider = None

    def save():
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    try:
        lib.start(False, False)
        if not args.provider_only:
            started = perf_counter()
            for source in sorted((root / "corpus").glob("*.pdf")):
                job = lib.upload(io.BytesIO(source.read_bytes()), source.name)
                if lib.metadata.job(job["id"])["state"] != "ready":
                    if lib.metadata.job(job["id"])["state"] in ("failed", "cancelled"):
                        lib.metadata.retry(job["id"])
                    lib.process_one()
                print(
                    "ingested",
                    source.name,
                    lib.metadata.job(job["id"])["state"],
                    flush=True,
                )
            report["ingestion_seconds"] = perf_counter() - started
            started = perf_counter()
            if (
                not manager.active()
                or manager.active()["snapshot"] != manager.snapshot()
            ):
                index = manager.queue()
                lib.process_one()
                if manager.row(index["id"])["state"] != "ready":
                    raise RuntimeError(manager.row(index["id"])["error"])
            report["index_seconds"] = perf_counter() - started
            report["model_profile"] = spec
            active = manager.active()
            report["profile_hash"] = active["profile"]
            retriever = HybridRetriever(
                manager, candidates=5, char_budget=10000, fusion="rrf"
            )
            baseline = Retriever(
                pipeline.embedder, store, lib.ready_builds, lib.workspace
            )
            names = {d["id"]: d["filename"] for d in lib.documents()}
            ids = {name: key for key, name in names.items()}
            training = []
            for sample in questions:
                requested = [ids[name] for name in sample["documents"]]
                record = {**sample, "tiers": {}}
                gold = {tuple(pair) for pair in sample["gold"]}
                for tier in TIERS:
                    started = perf_counter()
                    hits, info = retriever.retrieve(
                        sample["query"], 3, requested, tier=tier
                    )
                    elapsed = perf_counter() - started
                    pages = [
                        [
                            names[h["payload"]["document_id"]],
                            h["payload"]["page_number"],
                        ]
                        for h in hits
                    ]
                    success = bool(gold) and gold.issubset({tuple(p) for p in pages})
                    record["tiers"][tier] = {
                        "seconds": elapsed,
                        "gold_coverage": success,
                        "pages": pages,
                        "missing_documents": info["missing_documents"],
                    }
                started = perf_counter()
                hits, _ = retriever.retrieve(
                    sample["query"], 3, requested, tier="hybrid", fusion="borda"
                )
                record["borda"] = {
                    "seconds": perf_counter() - started,
                    "gold_coverage": bool(gold)
                    and gold.issubset(
                        {
                            (
                                names[h["payload"]["document_id"]],
                                h["payload"]["page_number"],
                            )
                            for h in hits
                        }
                    ),
                }
                started = perf_counter()
                old = baseline.retrieve(sample["query"], 3)
                record["pooled_baseline"] = {
                    "seconds": perf_counter() - started,
                    "gold_coverage": bool(gold)
                    and gold.issubset(
                        {
                            (
                                names[h["payload"]["document_id"]],
                                h["payload"]["page_number"],
                            )
                            for h in old
                        }
                    ),
                }
                winners = [
                    tier for tier in TIERS if record["tiers"][tier]["gold_coverage"]
                ]
                if sample["split"] == "train" and gold and winners:
                    cheapest = min(
                        winners, key=lambda tier: record["tiers"][tier]["seconds"]
                    )
                    training.append(
                        {
                            "query": sample["query"],
                            "documents": len(requested),
                            "label": TIERS.index(cheapest),
                        }
                    )
                report["samples"].append(record)
                print("evaluated", sample["id"], flush=True)
                save()
        active = manager.active()
        retriever = HybridRetriever(
            manager, candidates=5, char_budget=10000, fusion="rrf"
        )
        names = {d["id"]: d["filename"] for d in lib.documents()}
        ids = {name: key for key, name in names.items()}
        training = []
        for sample in report["samples"]:
            winners = [tier for tier in TIERS if sample["tiers"][tier]["gold_coverage"]]
            if sample["split"] == "train" and sample["gold"] and winners:
                cheapest = min(
                    winners, key=lambda tier: sample["tiers"][tier]["seconds"]
                )
                training.append(
                    {
                        "query": sample["query"],
                        "documents": len(sample["documents"]),
                        "label": TIERS.index(cheapest),
                    }
                )
        router = CostRouter.train(training, active["profile"])
        router_path = args.output.with_name("phase4-router.json")
        router.save(router_path)
        tests = [s for s in report["samples"] if s["split"] == "test" and s["gold"]]

        if args.enrich_baseline:
            enrich_baseline(report, lib, models, spec, manager, names, ids)
            save()

        def policy(name, chooser, provider_calls=0):
            selected = [s["tiers"][chooser(s)] for s in tests]
            report["policies"][name] = {
                "gold_coverage": mean(float(r["gold_coverage"]) for r in selected),
                "mean_retrieval_ms": mean(r["seconds"] for r in selected) * 1000,
                "provider_calls_per_query": provider_calls,
            }

        for tier in TIERS:
            policy("always_" + tier, lambda sample, tier=tier: tier)
        policy(
            "learned_starting_tier",
            lambda s: router.choose(s["query"], len(s["documents"])),
        )
        policy("heuristic", lambda s: heuristic(s["query"]))
        report["policies"]["borda_hybrid"] = {
            "gold_coverage": mean(float(s["borda"]["gold_coverage"]) for s in tests),
            "mean_retrieval_ms": mean(s["borda"]["seconds"] for s in tests) * 1000,
            "provider_calls_per_query": 0,
        }
        report["policies"]["selective_pooled_visual_unscoped"] = {
            "gold_coverage": mean(
                float(s["pooled_baseline"]["gold_coverage"]) for s in tests
            ),
            "mean_retrieval_ms": mean(s["pooled_baseline"]["seconds"] for s in tests)
            * 1000,
            "provider_calls_per_query": 0,
        }
        report["policies"].pop("pooled_baseline_unscoped", None)
        for field in ("all_visual_pooled_scoped", "all_visual_pooled_unscoped"):
            if tests and field in tests[0]:
                report["policies"][field] = {
                    "gold_coverage": mean(
                        float(s[field]["gold_coverage"]) for s in tests
                    ),
                    "mean_retrieval_ms": mean(s[field]["seconds"] for s in tests)
                    * 1000,
                    "provider_calls_per_query": 0,
                }
        if args.provider:
            from vision_rag.models.gemini_generator import GeminiGenerator

            provider = GeminiGenerator(
                settings.generation_model_name,
                settings.google_api_key,
                timeout_ms=15000,
                attempts=2,
            )
            saved_provider = report.get("provider", {})
            report["provider"] = {
                "status": "running",
                "answer_policy": "borda",
                "model": settings.generation_model_name,
                "dollar_cost": None,
                "usage": saved_provider.get("usage", []),
                "router": saved_provider.get("router", []),
                "answers": saved_provider.get("answers", [])
                if saved_provider.get("answer_policy") == "borda"
                else [],
                "support_estimates": saved_provider.get("support_estimates", [])
                if saved_provider.get("answer_policy") == "borda"
                else [],
            }
            try:
                synth = GroundedSynthesizer(
                    HybridRetriever(manager, candidates=30, fusion="borda"),
                    provider,
                    loader,
                    lib.source,
                )
                for sample in [s for s in report["samples"] if s["split"] == "test"][
                    :6
                ]:
                    if sample["id"] in {r["id"] for r in report["provider"]["answers"]}:
                        continue
                    sleep(args.provider_delay)
                    result = synth.query(
                        sample["query"], 3, [ids[n] for n in sample["documents"]]
                    )
                    expected = sample["expected"].lower().split(",")
                    correct = (
                        result["grounding_status"] == "insufficient"
                        if not sample["gold"]
                        else all(
                            value in result["answer"].lower() for value in expected
                        )
                    )
                    report["provider"]["answers"].append(
                        {
                            "id": sample["id"],
                            "expected": sample["expected"],
                            "expected_value_check": correct,
                            "result": result,
                        }
                    )
                    report["provider"]["usage"].extend(result["provider_usage"])
                    if (
                        result["claims"]
                        and len(report["provider"]["support_estimates"]) < 3
                    ):
                        images = []
                        try:
                            for source in result["sources"]:
                                _, path = lib.source(source["version_id"])
                                images.append(loader.load_page(path, source["page"]))
                            sleep(args.provider_delay)
                            judge = provider.judge_support(result["claims"], images)
                            report["provider"]["support_estimates"].append(
                                {"id": sample["id"], "same_model_judge": judge}
                            )
                            report["provider"]["usage"].append(provider.last_usage)
                        finally:
                            for image in images:
                                image.close()
                    save()
                for sample in [s for s in report["samples"] if s["split"] == "test"]:
                    if sample["id"] in {r["id"] for r in report["provider"]["router"]}:
                        continue
                    sleep(args.provider_delay)
                    started = perf_counter()
                    tier = provider.route_query(sample["query"])
                    report["provider"]["router"].append(
                        {
                            "id": sample["id"],
                            "tier": tier,
                            "seconds": perf_counter() - started,
                        }
                    )
                    report["provider"]["usage"].append(provider.last_usage)
                    save()
                choices = {r["id"]: r["tier"] for r in report["provider"]["router"]}
                policy("llm_prompted", lambda s: choices[s["id"]], 1)
                report["policies"]["llm_prompted"]["mean_retrieval_ms"] += (
                    mean(r["seconds"] for r in report["provider"]["router"]) * 1000
                )
                report["provider"]["status"] = "completed"
            except Exception as error:
                report["provider"]["status"] = "unavailable_or_partial"
                report["provider"]["error_type"] = type(error).__name__
                report["provider"]["code"] = getattr(error, "code", None)
                report["provider"]["error_message"] = str(error).replace(
                    settings.google_api_key or "not-set", "[redacted]"
                )[:1000]
        # Confirm at least one real Qdrant multivector score against the reference.
        allowed = manager.eligible(active)["visual"]
        if allowed:
            tokens = models.encode_visual(spec, ["Which bar is taller?"], False)[0]
            found = manager.store(active).search(tokens, allowed, 1, "visual")[0]
            with store.lock:
                original = store.client.retrieve(
                    manager.store(active).visual, [found["id"]], with_vectors=True
                )[0].vector["tokens"]
            report["exact_reference_error"] = abs(
                found["score"] - maxsim(tokens, original)
            )
        report["text_points"] = manager.store(active).count("text")
        report["visual_points"] = manager.store(active).count("visual")
        report["peak_cuda_allocated_bytes"] = (
            torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None
        )
        report["status"] = "completed"
        save()
        plot(report, args.output.with_name("phase4-cost-quality.png"))
        print(json.dumps(report["policies"], indent=2), flush=True)
    finally:
        if provider:
            provider.close()
        lib.close()
        store.client.close()
        models.close()


def enrich_baseline(report, library, models, spec, manager, names, ids):
    from vision_rag.retrieval.scoring import centroid
    from vision_rag.storage.metadata import identity
    from vision_rag.vector_stores.retrieval_store import RetrievalStore

    baseline = RetrievalStore(
        library.store,
        "allvisualbaseline" + manager.profile[:12],
        spec["visual_dimensions"],
        spec["visual_dimensions"],
    )
    baseline.create()
    points = []
    started = perf_counter()
    for build in manager.source_builds():
        version_id = library.metadata.rows(
            "SELECT version_id FROM builds WHERE id=?", (build,)
        )[0]["version_id"]
        version, path = library.source(version_id)
        for number in range(1, version["page_count"] + 1):
            point = identity("phase2baseline:" + version_id + ":" + str(number))
            with library.loader.load_page(path, number) as image:
                vectors = models.encode_visual(spec, [image], True)[0]
            baseline.put_text(
                [point],
                [centroid(vectors)],
                [
                    {
                        "document_id": version["document_id"],
                        "version_id": version_id,
                        "page_number": number,
                    }
                ],
            )
            points.append((point, version["document_id"]))
        print("all-visual baseline", version["filename"], flush=True)
    report["all_visual_baseline_build_seconds"] = perf_counter() - started
    report["all_visual_baseline_points"] = baseline.count("text")
    for sample in report["samples"]:
        gold = {tuple(pair) for pair in sample["gold"]}
        requested = {ids[n] for n in sample["documents"]}
        for scoped in (True, False):
            started = perf_counter()
            query = models.encode_visual(spec, [sample["query"]], False, False)[0]
            allowed = [
                point
                for point, document in points
                if not scoped or document in requested
            ]
            found = baseline.search(query, allowed, 3, "text")
            pages = [
                [names[h["payload"]["document_id"]], h["payload"]["page_number"]]
                for h in found
            ]
            key = "all_visual_pooled_scoped" if scoped else "all_visual_pooled_unscoped"
            sample[key] = {
                "seconds": perf_counter() - started,
                "pages": pages,
                "gold_coverage": bool(gold)
                and gold.issubset({tuple(p) for p in pages}),
            }
    report["baseline_note"] = (
        "All 40 pages use mean token vectors, cosine-equivalent to "
        "the historical single-page pooled representation; "
        "scoped and unscoped baselines are separate."
    )


def plot(report, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {
        "always_text": "Dense text + keyword",
        "always_visual": "Exact visual MaxSim",
        "always_hybrid": "Hybrid / RRF",
        "always_rerank": "Coarse rerank / RRF",
        "learned_starting_tier": "Learned starting tier (experimental)",
        "heuristic": "Heuristic starting tier",
        "borda_hybrid": "Hybrid / Borda (default)",
        "selective_pooled_visual_unscoped": "Selective pooled / unscoped",
        "all_visual_pooled_scoped": "All-page pooled / scoped",
        "all_visual_pooled_unscoped": "All-page pooled / unscoped",
        "llm_prompted": "LLM starting tier",
    }
    policies = [(n, m) for n, m in report["policies"].items() if n in labels]
    names = [labels[n] for n, _ in policies]
    figure, axes = plt.subplots(1, 2, figsize=(13, 7), sharey=True)
    colors = ["#167d8d" if n == "borda_hybrid" else "#64748b" for n, _ in policies]
    for axis, key, scale in zip(axes, ("gold_coverage", "mean_retrieval_ms"), (100, 1)):
        values = [m[key] * scale for _, m in policies]
        bars = axis.barh(names, values, color=colors)
        axis.bar_label(bars, fmt="%.1f", padding=4, fontsize=9)
        axis.set_xlim(0, max(values) * 1.16)
        axis.grid(axis="x", alpha=0.2)
        axis.set_axisbelow(True)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Gold page-set coverage @3 (%) — 20 answerable tests")
    axes[1].set_xlabel("Mean measured retrieval latency (ms)")
    figure.suptitle(
        "Phase 4: synthetic held-out families — quality and latency\n"
        "Scoped pooled baseline matches hybrid coverage at lower latency",
        fontsize=13,
    )
    figure.text(
        0.03,
        0.025,
        "Cached tier comparisons; generation/escalation and cheap routing overhead "
        "excluded. All shown policies use 0 router provider calls.\n"
        "LLM baseline: only 6/24 routes, blocked by daily quota; omitted. "
        "Synthetic templates do not establish real-document quality or dollar cost.",
        fontsize=9,
    )
    figure.subplots_adjust(left=0.30, right=0.96, top=0.86, bottom=0.17, wspace=0.14)
    figure.savefig(output, dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    main()
