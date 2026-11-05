"""Opt-in real-model retrieval smoke on a pinned, gold-enriched ViDoRe V3 subset.

Not the official benchmark: two books, eight English questions, small candidate
pool. Selection is fixed before inference. No provider requests or user data.
"""

import argparse
import hashlib
import io
import json
import math
import re
import sqlite3
import threading
from pathlib import Path
from time import perf_counter

import numpy as np

REPO = "vidore/vidore_v3_computer_science"
REVISION = "d5cc75883d92e294f0c0fc2662551c9708a06ebc"


class RemoteFile(io.RawIOBase):
    """Read Parquet ID metadata via bounded, verified HTTP ranges, not images."""

    def __init__(self, url, size):
        self.url, self.size, self.position = url, size, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = (
            0 if whence == 0 else self.position if whence == 1 else self.size
        ) + offset
        if not 0 <= self.position <= self.size:
            raise ValueError("Invalid range offset")
        return self.position

    def read(self, size=-1):
        import requests

        size = min(self.size - self.position, size if size >= 0 else self.size)
        if not size:
            return b""
        if size > 8 * 1024**2:
            raise ValueError("Metadata request exceeded range budget")
        end = self.position + size - 1
        with requests.get(
            self.url,
            headers={"Range": f"bytes={self.position}-{end}"},
            timeout=90,
            stream=True,
        ) as response:
            if (
                response.status_code != 206
                or response.headers.get("Content-Range")
                != f"bytes {self.position}-{end}/{self.size}"
            ):
                raise ValueError("Server did not honor the exact byte range")
            data = response.raw.read(size + 1)
        if len(data) != size:
            raise ValueError("Truncated range response")
        self.position += size
        return data


def metrics(ranking, gold, k=3):
    gold = {str(key): value for key, value in gold.items()}
    ranking = [str(key) for key in ranking]
    top = ranking[:k]
    relevant = {key for key, score in gold.items() if score > 0}
    dcg = sum(
        (2 ** gold.get(key, 0) - 1) / math.log2(i + 2) for i, key in enumerate(top)
    )
    ideal = sum(
        (2**score - 1) / math.log2(i + 2)
        for i, score in enumerate(sorted(gold.values(), reverse=True)[:k])
    )
    return {
        "recall_at_3": len(set(top) & relevant) / len(relevant),
        "complete_coverage_at_3": float(relevant.issubset(top)),
        "mrr": next(
            (1 / (i + 1) for i, key in enumerate(ranking) if key in relevant), 0
        ),
        "ndcg_at_3": dcg / ideal if ideal else 0,
    }


def prepare(root):
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    def download(name):
        return Path(
            hf_hub_download(
                REPO, name, repo_type="dataset", revision=REVISION, local_dir=root
            )
        )

    queries = pq.read_table(download("queries/test-00000-of-00001.parquet")).to_pylist()
    qrels = pq.read_table(download("qrels/test-00000-of-00001.parquet")).to_pylist()
    gold = {}
    for row in qrels:
        if row["score"] > 0:
            gold.setdefault(row["query_id"], {})[row["corpus_id"]] = row["score"]
    selected = [
        q
        for q in queries
        if q["language"] == "english" and 0 < len(gold.get(q["query_id"], {})) <= 3
    ][:8]
    if len(selected) != 8:
        raise ValueError("Pinned dataset selection changed")
    mapping_path = root / "page-map.json"
    if not mapping_path.exists():
        mapping = []
        for index, size in enumerate([228901444, 283984867]):
            name = f"corpus/test-0000{index}-of-00002.parquet"
            url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{name}"
            table = pq.ParquetFile(RemoteFile(url, size)).read(
                columns=["corpus_id", "doc_id", "page_number_in_doc"], use_threads=False
            )
            mapping.extend(table.to_pylist())
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    wanted = {key for q in selected for key in gold[q["query_id"]]}
    # Fixed IDs spread across both books; unrelated to measured model scores.
    wanted.update(row["corpus_id"] for row in mapping[::170][:8])
    pages = [row for row in mapping if row["corpus_id"] in wanted]
    pages = [
        {
            **row,
            "dataset_page_index": row["page_number_in_doc"],
            "page_number_in_doc": row["page_number_in_doc"] + 1,
        }
        for row in pages
    ]
    sources = {row["doc_id"]: download(f"pdfs/{row['doc_id']}.pdf") for row in pages}
    manifest = {
        "repository": REPO,
        "revision": REVISION,
        "license": "CC-BY-4.0",
        "attribution": "ViDoRe V3 contributors; OpenStax textbook authors",
        "selection": "first 8 English queries with 1-3 positive pages; "
        "all gold pages plus every 170th corpus ID (8 distractors)",
        "split": "held-out evaluation; never router training",
        "limits": "Gold-enriched candidate pool; not official full-corpus scores",
        "pages": pages,
        "queries": [
            {
                "id": q["query_id"],
                "query": q["query"],
                "content_type": q["content_type"],
                "gold": gold[q["query_id"]],
            }
            for q in selected
        ],
        "sources": {
            name: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for name, path in sources.items()
        },
    }
    return manifest, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path(".tools/vidore-v3"))
    parser.add_argument(
        "--output", type=Path, default=Path("docs/phase7-retrieval.json")
    )
    parser.add_argument("--internal", action="store_true")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    if args.internal:
        from scripts.phase7_corpus import create

        manifest, sources = create(args.work_dir / "internal")
    else:
        manifest, sources = prepare(args.work_dir)
    import psutil
    import pypdfium2 as pdfium
    import torch

    from vision_rag.config import settings
    from vision_rag.ingest.document_loader import DocumentLoader
    from vision_rag.models.retrieval_models import RetrievalModels
    from vision_rag.retrieval.scoring import centroid, fuse, maxsim
    from vision_rag.runtime import device_diagnostics

    report = {
        "dataset": manifest,
        "hardware": device_diagnostics(),
        "dpi": 150,
        "profile": {**settings.retrieval_specification, "dpi": 150},
        "samples": [],
        "status": "running",
        "visual_cache_files_before": len(
            list((args.work_dir / "tokens").glob("*.npz"))
        ),
        "timing_note": "Preparation reuses available visual token caches. Query 1 may "
        "include lazy model loading. Text timing excludes keyword fusion; "
        "reranking is simulated from cached exact scores, not a speed benchmark.",
        "not_measured": [
            "answer quality",
            "semantic support",
            "provider cost",
            "user verification time",
            "RTX 3050",
            "shared deployment",
        ],
    }
    models = RetrievalModels("cuda", "auto", args.work_dir / "tokens")
    spec, loader = report["profile"], DocumentLoader(dpi=150)
    pages = manifest["pages"]
    ids = [str(row["corpus_id"]) for row in pages]
    tokens, dense = [], []
    keyword = sqlite3.connect(":memory:")
    keyword.execute("CREATE VIRTUAL TABLE pages USING fts5(id UNINDEXED, text)")
    stop = threading.Event()
    rss = [0]

    def sample_ram():
        process = psutil.Process()
        while not stop.wait(0.05):
            rss[0] = max(rss[0], process.memory_info().rss)

    sampler = threading.Thread(target=sample_ram, daemon=True)
    sampler.start()
    torch.cuda.reset_peak_memory_stats()
    started = perf_counter()
    try:
        for row in pages:
            path, number = sources[row["doc_id"]], row["page_number_in_doc"]
            with pdfium.PdfDocument(path) as document:
                page = document[number - 1]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                    finally:
                        textpage.close()
                finally:
                    page.close()
            chunks = models.split_text(spec, text) if text.strip() else [" "]
            keyword.execute(
                "INSERT INTO pages VALUES (?,?)", (str(row["corpus_id"]), text)
            )
            dense.append(np.asarray(models.encode_text(spec, chunks), dtype=np.float32))
            with loader.load_page(path, number) as image:
                tokens.append(np.asarray(models.encode_visual(spec, [image], True)[0]))
            print("embedded page", row["corpus_id"], flush=True)
        report["subset_preparation_seconds"] = perf_counter() - started
        centers = np.asarray([centroid(t) for t in tokens])
        report["raw_token_bytes_per_page"] = sum(t.nbytes for t in tokens) / len(tokens)
        for query in manifest["queries"]:
            started = perf_counter()
            qtext = np.asarray(models.encode_text(spec, [query["query"]], True)[0])
            text_scores = [float((d @ qtext).max()) for d in dense]
            text_seconds = perf_counter() - started
            started = perf_counter()
            qvisual = models.encode_visual(spec, [query["query"]], False)[0]
            visual_encode_seconds = perf_counter() - started
            started = perf_counter()
            visual_scores = [maxsim(qvisual, t) for t in tokens]
            scoring_seconds = perf_counter() - started

            def rank(scores):
                return [
                    {"id": ids[i], "score": float(scores[i])}
                    for i in sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
                ]

            text_rank, visual_rank = rank(text_scores), rank(visual_scores)
            terms = re.findall(r"[\w]+", query["query"])[:32]
            expression = " OR ".join('"' + t + '"' for t in terms)
            keyword_rank = (
                [
                    {"id": row[0]}
                    for row in keyword.execute(
                        "SELECT id FROM pages WHERE pages MATCH ? "
                        "ORDER BY bm25(pages),id",
                        (expression,),
                    )
                ]
                if expression
                else []
            )
            text_rank = fuse([text_rank, keyword_rank], "rrf", limit=len(ids))
            coarse = centers @ np.asarray(centroid(qvisual))
            candidate_ids = {h["id"] for h in rank(coarse)[:10]}
            rerank = [h for h in visual_rank if h["id"] in candidate_ids]
            rankings = {
                "text_dense_keyword": text_rank,
                "exact_visual": visual_rank,
                "pooled_baseline": rank(coarse),
                "coarse_10_rerank": rerank,
                "hybrid_rrf": fuse([text_rank, visual_rank], "rrf"),
                "hybrid_borda": fuse([text_rank, visual_rank], "borda"),
            }
            from vision_rag.retrieval.router import CostRouter, heuristic

            tiers = {
                "text": text_rank,
                "visual": visual_rank,
                "hybrid": rankings["hybrid_rrf"],
                "rerank": fuse([text_rank, rerank], "rrf"),
            }
            rankings["heuristic_start"] = tiers[heuristic(query["query"])]
            router = CostRouter.load(Path("docs/phase4-router.json"))
            rankings["learned_start_cross_domain"] = tiers[
                router.choose(query["query"], 2)
            ]
            report["learned_note"] = (
                "Unmodified synthetic Phase 4 router evaluated "
                "out of domain; starting tier only, no generation or escalation"
            )
            sample = {
                "query_id": query["id"],
                "text_seconds": text_seconds,
                "visual_encode_seconds": visual_encode_seconds,
                "exact_scoring_seconds": scoring_seconds,
                "policies": {},
            }
            for name, hits in rankings.items():
                ranked = [h["id"] for h in hits]
                sample["policies"][name] = {
                    **metrics(ranked, query["gold"]),
                    "top_3": ranked[:3],
                }
            report["samples"].append(sample)
            args.output.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        report["metrics"] = {
            name: {
                key: sum(s["policies"][name][key] for s in report["samples"])
                / len(report["samples"])
                for key in metrics([], {"x": 1})
            }
            for name in rankings
        }
        report["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated()
        report["sampled_peak_process_rss_bytes"] = rss[0]
        report["cached_token_bytes_per_page"] = sum(
            p.stat().st_size for p in (args.work_dir / "tokens").glob("*.npz")
        ) / len(pages)
        report["status"] = "measured_smoke_only"
    finally:
        stop.set()
        sampler.join()
        keyword.close()
        models.close()
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
