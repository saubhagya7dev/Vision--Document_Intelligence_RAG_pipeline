"""Render the recorded retrieval comparisons without estimating missing results."""

import json
from pathlib import Path
from statistics import mean


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    root = Path("Docs")
    public, internal = [
        json.loads((root / name).read_text())
        for name in ("phase7-retrieval.json", "phase7-internal.json")
    ]
    labels = {
        "pooled_baseline": "Pooled visual baseline",
        "text_dense_keyword": "Dense text + keyword",
        "exact_visual": "Exact visual MaxSim",
        "coarse_10_rerank": "Coarse top-10 + MaxSim",
        "hybrid_rrf": "Hybrid / RRF",
        "hybrid_borda": "Hybrid / Borda",
        "heuristic_start": "Heuristic starting tier",
        "learned_start_cross_domain": "Learned starting tier (experimental)",
    }
    lines = [
        "# Phase 7 benchmark",
        "",
        "Recorded on the RTX 4050 Laptop; local "
        "smoke experiments, not an official benchmark or production approval.",
        "",
        "## Retrieval relevance",
        "",
        "| Policy | Public recall@3 | Public complete coverage@3 | Internal recall@3 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, label in labels.items():
        p, i = public["metrics"][name], internal["metrics"][name]
        lines.append(
            f"| {label} | {p['recall_at_3']:.2%} | "
            f"{p['complete_coverage_at_3']:.2%} | {i['recall_at_3']:.2%} |"
        )
    lines.extend(
        [
            "",
            "![Retrieval comparison](phase7-retrieval-comparison.png)",
            "",
            "Public: eight English questions, 20 pages, two OpenStax books from "
            "[ViDoRe V3 computer science](https://huggingface.co/datase"
            "ts/vidore/vidore_v3_computer_science), "
            "revision `d5cc75883d92e294f0c0fc2662551c9708a06ebc`. CC-BY-4.0; "
            "attribution: ViDoRe V3 contributors and OpenStax textbook "
            "authors. Selection "
            "is fixed before inference: first eight English queries with one to three "
            "positive pages, all gold pages plus eight fixed corpus-ID distractors. "
            "This gold-enriched pool is much easier than full-corpus retrieval. "
            "Scores are not official ViDoRe results.",
            "",
            "Internal: 16 questions over 18 candidate pages from generated Juniper, "
            "Basalt and Granite reports. Includes numbers, identifiers,"
            " tables, charts, "
            "image-only scans and sampled pages from a 64-page PDF. All versions of "
            "these families are held out from Phase 4 router training. "
            "Related versions "
            "occur together only inside the held-out product split. The corpus is "
            "synthetic and template-based; its results do not establish"
            " generalization.",
            "",
            "Both runs use identical candidate pages for all policies, 150 DPI, pinned "
            "BGE/ColPali revisions and original token matrices. Text "
            "uses native extraction "
            "without OCR in this experiment. Exact scoring runs locally in NumPy; "
            "coarse reranking is simulated from cached exact scores and"
            " is not a latency "
            "optimization measurement. Learned and heuristic rows "
            "choose starting tiers "
            "without generation/escalation; the unmodified synthetic "
            "router is evaluated "
            "out of domain and remains disabled in normal use.",
            "",
            "Coarse candidate recall@10: public "
            f"{public['mean_candidate_recall_at_10']:.2%}; internal "
            f"{internal['mean_candidate_recall_at_10']:.2%}. The public coarse "
            "stage drops relevant evidence. Hybrid improves over pooled"
            " retrieval here, "
            "but loses three internal scan queries that exact visual retrieval finds. "
            "No policy is declared best for general use, and no router "
            "cost win is claimed.",
            "",
            "## Timing and memory",
            "",
            "| Measurement | Public | Internal |",
            "| --- | ---: | ---: |",
        ]
    )
    for label, key, scale, suffix in [
        (
            "Warm dense encoding + scoring (mean, queries 2+)",
            "text_seconds",
            1000,
            "ms",
        ),
        (
            "Warm visual query encoding (mean, queries 2+)",
            "visual_encode_seconds",
            1000,
            "ms",
        ),
        (
            "Exact scoring over candidate tokens (mean)",
            "exact_scoring_seconds",
            1000,
            "ms",
        ),
    ]:
        values = [
            mean(s[key] for s in r["samples"][1:]) * scale for r in (public, internal)
        ]
        lines.append(
            f"| {label} | {values[0]:.2f} {suffix} | {values[1]:.2f} {suffix} |"
        )
    lines.extend(
        [
            "",
            "Timing excludes provider generation, database filtering and most "
            "application work; text timing also excludes keyword fusion. First query "
            "visual encoding can include lazy model loading; inspect raw samples. "
            "Cached subset preparation is not cold ingestion throughput. The separate "
            "[uncached internal run](phase7-internal-cold.json) prepared 18 pages in "
            "117.78 seconds including model loading (0.153 pages/s), "
            "outside the durable "
            "application ingestion pipeline. It measured a peak CUDA allocator value "
            "of 8.71 GB and process RSS of 4.47 GB. CUDA allocator bytes are not a "
            "measurement of physically resident VRAM; the laptop has about 6 GiB of "
            "GPU memory and Windows may oversubscribe it. This does not prove the "
            "workload fits a 4 GiB card.",
            "",
            "Original float32 tokens occupy about 1.06 MB/page before compression; "
            "compressed token files are about 0.305 MB/page. These are token-only "
            "storage figures, excluding PDFs, page caches, indexes and "
            "SQLite. Hardware, "
            "Torch/CUDA versions, exact profiles, source hashes and per-query results "
            "are in [public](phase7-retrieval.json) and "
            "[internal](phase7-internal.json) records. "
            "Only the RTX 4050 Laptop is measured; RTX 3050 and other "
            "systems are unmeasured.",
            "",
            "## Answer quality and provider cost",
            "",
            "The real streaming check passed: first provisional claim delta 5.53 s, "
            "completion 5.57 s. This is adapter latency, not browser "
            "TTFT. A supplied-gold "
            "version-comparison sample correctly reported 137 and 163 million EUR "
            "with valid references. Remaining product checks and the prompted router "
            "baseline stopped on HTTP 503; inspect the checkpointed "
            "[provider](phase7-provider.json) and "
            "[answers](phase7-answers.json) reports. "
            "Resume scripts skip completed requests and stop at the first new error.",
            "",
            "Token usage is recorded where supplied by the provider. Dollar cost is "
            "unknown, not zero; no verified account billing rate is "
            "available. Phase 4's "
            "[cost/quality comparison](phase4-cost-quality.png) remains a synthetic "
            "cached-tier experiment. Partial prompted routes are not compared against "
            "full test-set means. Independent semantic support, representative answer "
            "correctness/abstention and human time-to-verify are unmeasured. Routine "
            "contract and browser tests do not fill those gaps.",
            "",
        ]
    )
    (root / "Phase 7 benchmark.md").write_text("\n".join(lines), encoding="utf-8")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)
    for axis, report, title in zip(
        axes,
        (public, internal),
        ("Public: 8 queries / 20 pages", "Fictional: 16 queries / 18 pages"),
    ):
        values = [100 * report["metrics"][name]["recall_at_3"] for name in labels]
        axis.barh(list(labels.values()), values, color="#167d8d")
        axis.set_xlim(0, 108)
        axis.set_xlabel("Mean gold-page recall @3 (%)")
        axis.set_title(title)
        axis.grid(axis="x", alpha=0.2)
        axis.set_axisbelow(True)
    axes[0].invert_yaxis()
    fig.suptitle("Phase 7 retrieval smoke checks — small candidate pools")
    fig.tight_layout()
    fig.savefig(root / "phase7-retrieval-comparison.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
