# Vision implementation checklist

Current scope: Phase 3 is implemented. Stop before Phase 4. Existing research documents are reference material, not shipped features. Preserve the original README; current upgrade instructions live in this Docs directory.

## Phase 1 — diagnosis and performance foundations

Implemented and covered by local regression checks:

- [x] Inspect actual code, Git state, environment and original tests.
- [x] Identify CPU-only Torch despite detected NVIDIA hardware.
- [x] Structured timings and request trace propagation.
- [x] Direct page count without rasterization.
- [x] Single-page rendering for previews and evidence.
- [x] Content-addressed page/thumbnail artifacts, cache recovery.
- [x] Bounded page/embedding batches and serialized inference.
- [x] Configurable device/precision/model/batch settings and CPU fallback.
- [x] Multi-item OOM retry without omitted pages; actionable single-item failure.
- [x] Model initialization/readiness, optional startup loading and shutdown cleanup.
- [x] Thread-pool execution for blocking API handlers.
- [x] Real PDF/Qdrant adapter checks, failure checks and reproducible PDF benchmark.
- [x] Accurate setup, configuration examples and documented limits.

External validation still required:

- [x] Follow-up: install a compatible CUDA build and verify actual CUDA image/query embeddings on the local RTX 4050. See GPU setup.md.
- [ ] Measure actual model cold start, warm inference and provider response.
- [ ] Check small text/chart/table fidelity on representative real documents.
- [ ] Measure RTX 3050-class and stronger hardware using the same workloads.

The Phase 1 implementation is complete; unavailable model/hardware/provider checks are not reported as passing. See Phase 1 results.md.

## Phase 2 — durable documents and jobs

- [x] SQLite documents, immutable versions, page artifacts, builds and durable jobs.
- [x] Generated original storage keys, validation, hashing and scoped deduplication.
- [x] Explicit replacement/version semantics; failed replacement keeps old evidence active.
- [x] Persistent local Qdrant and deterministic page/index point identities.
- [x] Background worker with stage progress, retry, cancel and restart recovery.
- [x] Ready-only retrieval filtered by workspace, active version and index profile.
- [x] Immediate deletion tombstones and retryable vector/file cleanup.
- [x] One-time legacy import and orphan/restart reconciliation.
- [x] Version-specific sources, page previews and original downloads.
- [x] Server-backed UI job history and recovery actions.
- [x] Real disk, worker-thread and abrupt-process-exit tests; browser retry verification.
- [x] 57 tests, lint, strict type checks, compilation and JavaScript syntax checks.

See [Phase 2 guide](Phase%202%20guide.md) for setup, migration, contracts and limits. The verified profile is one local application process with SQLite and persistent local Qdrant. Model/provider quality and shared-deployment validation remain separate work.

## Phase 3 — hybrid text and visual ingestion

- [x] Native Unicode extraction on every new page; text quality and layout signals.
- [x] Heading-aware page-local chunks, bounded UTF-8 budgets and overlap.
- [x] Raster/vector/table/column/rotation/uncertainty routing with persisted reasons.
- [x] Selective local OCR adapter and visual fallback with explicit warnings.
- [x] Native text retained on visual pages; revisioned extraction records.
- [x] Durable page overrides, restart recovery, isolated publication and deletion.
- [x] Page inspection and reprocessing UI; version-scoped API contracts.
- [x] Lexical discovery bridge keeps text-only pages usable before Phase 4.
- [x] Legacy schema/page-override migration and regression checks.
- [x] Real GPU comparison against all-visual and native-only generated-PDF baselines.
- [x] Browser verification of a successful page override with native text retained.
- [x] 79 tests, lint, strict types, compilation, JavaScript syntax and whitespace checks.
- [x] Follow-up: project-local Tesseract and real English scan recognition, CUDA ingestion, and OCR text search.
- [ ] Broad OCR/language quality and representative held-out quality.

See [Phase 3 guide](Phase%203%20guide.md) for setup, measurements, and limits.
Follow-up button styling and [Data controls](Data%20controls.md) add history/cache
clearing and confirmed, recoverable local resets. The current suite has 87 tests.
The optional OCR adapter and fallback are implemented and a real scan smoke check passed; broad recognition quality and
held-out product quality are not claimed as validated.

## Later phases — not started

4. Retrieval/grounding: dense/lexical/visual fusion, exact multivector reference, versioned reindex, document scope and validated citations. Exit: held-out quality tradeoffs measured; evidence resolves to correct versions.
5. Workspace: persistent conversations, evidence viewer, streaming, real progress/errors and accessibility. Exit: upload, ask, inspect, revisit and recover work end to end.
6. Analysis: cited comparisons, deterministic numerical calculations, regions/version review, findings and exports. Exit: one complete reproducible multi-document workflow.
7. Evaluation/release: held-out document tasks, quality and hardware comparisons, access controls, security, deployment/restore and accurate release documentation. Exit: measured release gates, no unsupported production claims.

Tests and measurements run throughout each implemented phase. Phase 2 adds a durable local metadata/worker boundary without new extraction dependencies, models, frontend frameworks or distributed services.
