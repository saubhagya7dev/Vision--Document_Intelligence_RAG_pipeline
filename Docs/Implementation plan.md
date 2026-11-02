# Vision implementation checklist

Scope agreed on 2 November 2026: implement and stop after Phase 1. Existing research documents are reference material, not shipped features.

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

## Later phases — not started

2. Durable documents/jobs: authoritative metadata, content identity, versions, durable background ingestion, retry/cancel/recovery, persistent vectors and reconciliation. Exit: upload/restart/retry/delete preserve index/source consistency.
3. Hybrid ingestion: native text on every usable page, quality checks, chunking, selective visual/OCR/layout processing and overrides. Exit: mixed/scanned/uncertain pages preserve usable text and have recovery paths.
4. Retrieval/grounding: dense/lexical/visual fusion, exact multivector reference, versioned reindex, document scope and validated citations. Exit: held-out quality tradeoffs measured; evidence resolves to correct versions.
5. Workspace: persistent conversations, evidence viewer, streaming, real progress/errors and accessibility. Exit: upload, ask, inspect, revisit and recover work end to end.
6. Analysis: cited comparisons, deterministic numerical calculations, regions/version review, findings and exports. Exit: one complete reproducible multi-document workflow.
7. Evaluation/release: held-out document tasks, quality and hardware comparisons, access controls, security, deployment/restore and accurate release documentation. Exit: measured release gates, no unsupported production claims.

Tests and measurements run throughout each implemented phase. No architecture migration, new extraction dependency, new model, frontend framework, or distributed service was adopted in Phase 1.
