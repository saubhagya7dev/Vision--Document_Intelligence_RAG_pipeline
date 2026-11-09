# Vision implementation checklist

Current scope: the core Phase 6 workflow is implemented. Stop before Phase 7 and optional analytical extensions. The earlier quota-limited prompted-router comparison has not been resumed. Existing research documents are reference material, not shipped features. Preserve the original README; current upgrade instructions live in this Docs directory.

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

## Phase 4 — retrieval and grounding

- [x] Pinned CPU dense text encoder and keyword retrieval, with document/page scope.
- [x] Original ColPali token matrices and exact masked MaxSim reference checks.
- [x] Coarse centroid candidates reranked against original tokens; isolated profiles.
- [x] RRF/Borda comparison, bounded evidence and requested-document coverage.
- [x] Durable staged index builds, activation, rollback, restart and cleanup.
- [x] Strict claims/citations contract, reference validation and abstention.
- [x] Original/rewritten follow-ups, bounded provider attempts and actionable quota errors.
- [x] Local provider-free Find pages; index controls and message-specific citations.
- [x] Learned cheap router experiment with disjoint train/test families and tier cache.
- [x] Fixed-tier, heuristic and learned-policy cost/quality comparisons and plot.
- [x] Real CUDA/Qdrant MaxSim check and six sampled provider answer checks.
- [x] Three sampled same-model support estimates, labeled as estimates.
- [x] 107 tests, lint/format, strict types, compilation, JS syntax and browser checks.
- [ ] Complete the prompted LLM router baseline: 6/24 test routes completed before daily quota.
- [ ] Representative real-document quality and independent semantic support evaluation.

See [Phase 4 guide](Phase%204%20guide.md) for setup, migration, measurements,
limits and provider resume instructions. Hybrid and learned policies match the
scoped pooled baseline's coverage on the toy corpus but are slower; learned
routing remains experimental and disabled by default. Phase 4 implementation
is finished; the external comparison above is not reported as completed.

## Phase 5 — evidence workspace and conversations

- [x] Persist workspace conversations, immutable turn scope, results and events.
- [x] Reopen, rename and delete chats; clear conversation data with history/reset.
- [x] Typed conversation/query contracts and ordered replayable SSE events.
- [x] Stream provisional claim text; final validated citations are authoritative.
- [x] Cooperative cancellation, disconnect recovery and restart interruption states.
- [x] Split evidence pane with version-specific pages, thumbnails, zoom and position.
- [x] Narrow-screen navigation, keyboard controls and visible progress/failures.
- [x] Text-node rendering, safe citation actions and removal of inline source handlers.
- [x] Replace invented dashboard bars with persisted page/job/answer metrics.
- [x] Browser checks for reopen, citations, navigation, cancel/retry and disconnect.
- [x] Regression tests and static checks; see Phase 5 guide for final results.
- [ ] Live provider streaming validation after account quota availability.
- [ ] Broad accessibility audit and real-provider performance measurements.

See [Phase 5 guide](Phase%205%20guide.md). At Phase 5 delivery, no analytical findings
or exports had been added. Routine verification uses isolated fictional documents and
simulated inference; existing Phase 4 quality limits still apply.

## Phase 6 — one complete comparison workflow

- [x] Explicit selection of two to four reports/retained document versions.
- [x] Per-version bounded hybrid evidence and complete field/version matrices.
- [x] Cited factual cells, explicit missing evidence and constrained conflicts.
- [x] Reported value/unit/currency/period/scope retention and context warnings.
- [x] Citation inspection in an independent evidence pane.
- [x] Immutable saved findings, user review status and chat-answer findings.
- [x] JSON/CSV/Markdown exports with source manifests and access checks.
- [x] Source deletion, workspace/reset isolation, history/draft behavior and sanitization.
- [x] Browser compare → inspect → review → save → reopen → download workflow.
- [x] One real provider comparison smoke check on fictional pages.
- [x] Regression and static checks; see Phase 6 guide and verification record.
- [ ] Optional calculations, regions, automated version diffs and similarity maps.
- [ ] Representative quality, shared access/authentication and release validation.

See [Phase 6 guide](Phase%206%20guide.md). No normalization or new numerical
calculations are presented as reported facts. Historical versions without retained
eligible indexes show missing evidence. Phase 7 implementation and local validation
are recorded below.

## Phase 7 — evaluation, hardening and release


- [x] Single-owner sessions/bearer access and fixed-workspace authorization.
- [x] Host/origin/CORS/body boundaries, cookie revocation and secret masking.
- [x] Signed offline backup and restore with real storage/search/history validation.
- [x] Pinned ViDoRe V3 subset, new fictional product corpus and real CUDA retrieval comparisons.
- [x] Real provider streaming check and resumable router/product-answer measurements.
- [x] Wheel build and isolated packaged API/static/session smoke.
- [x] Pinned container recipe and localhost-only optional Qdrant compose configuration.
- [x] Dependency advisory fixes, explicit remaining advisory and auditor exclusions.
- [x] Fail-closed release gates with source fingerprints; current guide and feature matrix.
- [x] 133 regression tests plus lint, format, strict typing, compilation and JS syntax checks.
- [ ] Complete remaining live provider samples after service availability.
- [ ] Independent semantic support, broad answer quality and human verification timing.
- [ ] RTX 3050 measurements, container runtime and shared TLS deployment verification.

See [Phase 7 guide](Phase%207%20guide.md), [benchmark](Phase%207%20benchmark.md),
and [release gates](phase7-release-gates.json). Local implementation is delivered;
unverified release gates remain false. No production or shared-deployment readiness
is claimed. The README was updated on 9 November 2026 to describe the implemented
phases and subsequent workspace redesign, following the user's new instruction.

Tests and measurements run throughout each implemented phase. Phase 2 adds a durable local metadata/worker boundary without new extraction dependencies, models, frontend frameworks or distributed services.
