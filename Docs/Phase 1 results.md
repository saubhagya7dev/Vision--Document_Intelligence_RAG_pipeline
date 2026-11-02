# Phase 1 — results and practical limits

Completed implementation: 2 November 2026. Work stops at Phase 1; Phases 2–7 remain unstarted.

Follow-up: the user subsequently requested CUDA installation. CUDA computation and real ColPali image/query embedding smoke checks now pass on the RTX 4050. See [GPU setup](GPU%20setup.md) and gpu-smoke.json. The CPU-only environment and unverified GPU statements below describe the original Phase 1 baseline, preserved as historical measurement context.

## Delivered behavior

The existing visual pipeline remains in place, with bounded work and observable performance:

- Direct metadata-based PDF page counting.
- Single-page rendering for previews and retrieved evidence.
- Content-addressed, lossless PNG page artifacts and thumbnails. Ingestion derives thumbnails from the existing page image rather than rendering twice. Partial cache writes are atomic; corrupt cached images regenerate.
- Bounded rendering/embedding batches, prompt image cleanup and explicit PDFium handle cleanup.
- A process-wide PDFium lock and a model inference lock. Blocking API handlers execute in FastAPI worker threads.
- Auto/explicit device selection, supported precision checks, CPU fallback and NVIDIA-versus-Torch diagnostics.
- Multi-item memory failures retry all items individually; single-item failures return an actionable configuration error.
- Shared, synchronized component initialization; optional startup loading; visible readiness/failure states; retry after initialization failure; shutdown cleanup.
- Correlated JSON stage timings and X-Trace-ID responses. Queue wait is measured separately from model inference.
- Qdrant statistics no longer read the removed vectors_count attribute. Vector batches with inconsistent lengths are rejected.
- Basic upload/query limits, original-file containment, duplicate-name rejection and compensating cleanup after synchronous ingest failure.

These last safeguards support the Phase 1 workflow. They are not durable versioning, deduplication, transactionality, or a replacement for Phase 2 jobs/metadata.

## Environment and measurement setup

- CPU: 13th Gen Intel Core i7-13700H.
- OS: Windows 11, build 26300.
- Python: 3.14.9.
- pypdfium2: 5.14.0; Pillow: 12.3.0.
- Installed PyTorch: 2.13.0, CPU-only (torch.version.cuda is null).
- Detected accelerator: NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB; NVIDIA driver 617.14.
- Qdrant client: 1.19.0; ColPali engine: 0.3.18; FastAPI: 0.141.1.

The PDF benchmark does not use the GPU. The environment was inspected rather than upgraded; CUDA installation and real GPU inference remain unverified. No model weights were downloaded and no Gemini calls were made.

## Reproducible PDF benchmark

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_phase1.py --output Docs/phase1-benchmark.json
```

The script creates an eight-page synthetic raster PDF containing prose, a table, small labels and a line chart. Pages are US Letter size and rendered at 300 DPI. Each case uses a fresh subprocess and three wall-clock samples. The historical reference renders all pages, with explicit cleanup added to avoid comparing accidental resource leaks.

| Case | Median wall time | Peak process working set |
| --- | ---: | ---: |
| Historical count by rendering all pages | 718.471 ms | 353.6 MiB |
| Direct page count | 1.108 ms | 34.6 MiB |
| Historical page preview by rendering all pages | 646.566 ms | 353.5 MiB |
| Requested page only, no application cache | 80.680 ms | 127.2 MiB |
| Requested page from warmed artifact cache | 69.247 ms | 127.4 MiB |
| All pages, batches of two, cache disabled | 639.425 ms | 159.6 MiB |
| All pages, batches of two, populate pages/thumbnails | 2410.157 ms | 161.6 MiB |

Raw samples are stored in phase1-benchmark.json.

Interpretation:

- Direct counting removes rasterization entirely.
- Single-page access avoids work proportional to the entire document.
- Batching bounds page buffers and lowers memory; it is not a promise of faster full-document rendering.
- Lossless cache population adds first-pass CPU/disk work. The warmed cache produced a modest time difference on this fixture; decoding PNG still costs time and memory.
- Process peaks include the interpreter, dependencies, three samples and case warmup. They are not isolated image-buffer sizes, VRAM readings, or end-to-end application peaks.
- OS filesystem caches, CPU power/thermal conditions and other processes are uncontrolled. Three samples do not establish a service latency target.
- This fixture does not establish small-label readability, visual retrieval accuracy, or answer correctness on real reports.
- No hardware-to-hardware or full-model speedup claim is made.

## Checks performed

- 36 tests passed, including original loader/retriever/API coverage and new real PDF/Qdrant checks.
- Ruff passed across src, tests and scripts.
- Strict mypy passed across all 16 source files.
- Python bytecode compilation and JavaScript syntax checks passed.
- Actual ColPali/Transformers imports succeeded without loading model weights.
- Real Qdrant insert/count/delete and a PDF → bounded ingestion → Qdrant retrieval → page-context workflow passed. The latter uses fake encoder/generator outputs and validates adapter wiring, not model quality.
- Failure checks cover invalid queries/uploads, size limits, duplicate-name protection, interrupted synchronous ingestion cleanup, incomplete encoder output, bad cache artifacts and oversized rasters.
- Concurrency/lifecycle checks cover one model initialization across competing callers, serialized inference, health responsiveness during a blocked query, initialization failure/retry, warmup and resource cleanup.
- Timing checks confirm that a page-inspection event in a worker thread shares the HTTP trace ID and excludes the document filename.
- Two upstream deprecation warnings remain (Starlette/AnyIO and Google SDK typing on Python 3.14).

Inside the restricted Codex sandbox, the original API test attempts stalled in Windows asyncio socket-pair creation before app code ran. The API suite was subsequently run successfully outside that sandbox. The stalled processes were stopped. This was not treated as a passing test.

## Timing contract and cold start

The normal module entrypoint enables INFO logs. Timing records contain trace_id, stage, duration_ms, outcome and bounded operational metadata such as page/item counts.

Instrumented stages: HTTP handling, upload copy/validation, page inspection, rendering, cache reads/writes, model imports/loading, inference queue wait, inference, document embedding, vector upsert, query embedding, candidate retrieval, evidence preparation and provider generation.

Stages not yet implemented (native text extraction, reranking, stream first-token latency) do not emit invented measurements. Upload timing begins after multipart parsing and does not measure network transfer.

MODEL_WARMUP=false preserves lightweight library startup and exposes not_loaded/failed readiness. The first ingest/query includes imports/model loading. MODEL_WARMUP=true initializes components during startup. Loaded readiness does not verify a remote provider request, warm kernels, or complete an inference benchmark.

## Decisions and boundaries

- Keep pypdfium2, ColPali, Qdrant, Gemini and the existing frontend; no new extraction/model framework was adopted.
- Preserve 300 DPI and pooled embedding/index semantics. Changing retrieval representations requires a versioned reindex in Phase 4.
- Store full pages losslessly so this phase does not silently lower small-text quality.
- Use worker threads and explicit locks in one local process. Durable worker jobs and cancellation are Phase 2.
- Keep the existing Qdrant storage modes. Uploaded originals can outlive an in-memory index; Phase 2 must provide authoritative metadata and reconciliation.
- Preserve original filenames temporarily while preventing path escape and overwrites. Generated storage keys and immutable versions arrive in Phase 2.
- Keep the two pre-existing untracked research files untouched and outside these commits.

Remaining limitations:

- Model cold start, real CPU/GPU throughput, provider response time, peak model RAM/VRAM and end-to-end query latency are not measured.
- CUDA/bfloat16/MPS execution and single-page accelerator OOM behavior were exercised through configuration/unit checks, not those devices.
- No universal RTX 3050 memory/performance guarantee; model weights may exceed a particular accelerator's capacity.
- No real-corpus fidelity/quality benchmark, provider availability verification, browser automation, or clean-environment installation test.
- No persistent ingestion jobs, restart recovery, immutable versions or concurrency-safe cross-store transactions. Failed-cleanup sources may remain and need reconciliation.
- Cached artifacts currently have no disk quota/retention or automatic deletion of orphaned hashes.
- Current uploads remain synchronous HTTP operations; upstream disconnects/timeouts do not cancel inference.
- Basic application upload checks run after multipart parsing and do not enforce a network body limit.
- No new access-control boundary, hybrid retrieval, MaxSim migration, structured citations, streaming or persistent conversations.

## Run instructions

Keep the existing .env and environment if already configured:

```powershell
.\.venv\Scripts\python.exe -m vision_rag.api.main
```

Open http://localhost:8000. Inspect /api/v1/diagnostics before model-dependent work. For a fresh configuration, copy .env.example, set a real GOOGLE_API_KEY and an available GENERATION_MODEL_NAME, and configure device/batch settings. Use the official PyTorch installer selector for a compatible CUDA build, then rerun diagnostics.

Phase 2 is intentionally not started.
