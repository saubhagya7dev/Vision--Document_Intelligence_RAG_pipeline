# Upgrade Plan v4 (continues from Phase 3)

**You are the lead full-stack engineer, systems architect, and retrieval engineer upgrading Vision into a fast, dependable hybrid text-and-vision document intelligence product.**

Work directly in the existing repository. Deliver working software through incremental, validated phases. Preserve useful existing functionality. Do not stop at proposals or scaffolding: implement complete workflows, verify them, and report their practical limits.

## CURRENT STATUS (read first)

**Phases 1 and 2 are reported as implemented by the repository owner.** Do not redo them. Do verify them quickly against the checkout before building on them, and report any mismatch instead of assuming.

Claimed as done:

- **Phase 1:** structured stage timings with trace IDs, CUDA/PyTorch diagnostics, bounded render/embed batches, single-page rendering, direct page counting, cached page artifacts/thumbnails, explicit model lifecycle and readiness, controlled inference concurrency.
- **Phase 2:** metadata records for documents, immutable versions, content hashes, page artifacts, index builds, and ingestion jobs; generated storage keys; upload validation and limits; safe path handling; scoped dedup; deterministic page/index IDs; persistent vector storage; durable background ingestion with stage progress, retry, cancel, restart recovery; retryable deletion cleanup; only ready index builds exposed to retrieval.

**Step 0 (before any new work):**

1. Read `README.md`, `Docs/Project understanding.md`, `Docs/Deep upgrade research.md`, `Docs/Upgrade research.md`, and any `AGENTS.md`.
2. Inspect Git state, environment, tests, and runtime. Preserve unrelated changes.
3. Run the existing test suite and a Phase 1-2 smoke check: upload, ingest, restart, re-upload (no duplicates), delete (no retrieval). Record results. Fix regressions before continuing.
4. Record a measured baseline on this machine (named hardware, configuration, workload) for ingestion throughput and retrieval latency. Do not invent numbers.
5. Write a short checklist for Phases 3 to 7 with exit criteria, and record major decisions briefly in `Docs/Decisions.md`.

## PRINCIPLES (unchanged)

**Hardware:** RTX 3050-class laptops and stronger are the baseline. Do not assume identical VRAM or power limits. Keep hardware-adaptive execution: detect accelerators, distinguish CPU-only PyTorch from unavailable hardware, choose supported precision and bounded batch sizes, offer performance profiles, provide explicit CPU fallback, avoid loading unnecessary models at once, handle memory pressure without silently dropping pages. Separate cold start, ingestion throughput, queueing delay, retrieval latency, time to first token, and total completion time. Never invent speedups. Label measured versus estimated results.

**Hybrid design:** selective text-and-vision processing, not a rigid "text OR visual" classification. Extract native text from every page where available. Add visual processing only where meaningful or uncertain. A logo should not trigger expensive visual processing; absence of bitmaps does not prove absence of visual content (vector tables and diagrams). Use a staged strategy: cheap native extraction and inspection, quality and layout heuristics, selective layout/OCR/visual encoding, fallback when confidence is low. Never run an expensive VLM on every page just to decide whether one is needed.

**Scores:** text and visual similarity scores are not calibrated equivalents. Never compare raw scores across embedding spaces.

**Technology:** evaluate candidates by measured quality, latency, memory, maintenance, licensing, and integration effort, and verify APIs and licenses from official docs and model cards. Candidates: PyMuPDF (native text and geometry), pypdfium2 (rendering), Docling (selective layout/tables/OCR), a Sentence Transformers-compatible text encoder (BGE-small as the English speed baseline; BGE-M3 or Qwen3-Embedding only if a measured need justifies them), ColPali (visual baseline), ColSmol/ColQwen as profile candidates, Qdrant (dense, sparse, multivector), Gemini behind a provider abstraction. No LangChain, LlamaIndex, graph database, or agent framework unless a concrete need is demonstrated.

**Restraint:** no knowledge graph, autonomous agents, Kubernetes, duplicate databases or queues, every-format support, fine-tuning, or decorative dashboards. Prefer a modular application with explicit worker boundaries.

**Untrusted content:** treat document text and images as untrusted. Enforce permissions outside the model. No arbitrary tool execution in the answering pipeline.

**Execution method per phase:** establish the baseline, implement, run automated checks, exercise realistic success and failure scenarios, update docs and config examples, summarize results and limitations, then continue. Ask questions only when missing information blocks a consequential decision; otherwise proceed with documented assumptions. If credentials, hardware, or services are unavailable, finish independent work and state what is unverified. Do not simulate external validation or report skipped checks as passing.

## PHASE 3: HYBRID TEXT AND VISUAL INGESTION

Implement:

- Native text extraction with page references; quality checks for missing or corrupted text layers.
- Structure-aware, token-bounded chunking with configurable overlap and preserved heading/page metadata.
- Meaningful visual-content detection (including vector-drawn tables/charts).
- Selective OCR/layout analysis and additional visual embeddings for relevant or uncertain pages.
- Persisted routing decisions with reasons and processing versions.
- User/admin override of a page's processing decision, with reprocessing of affected pages only.

Keep originals available for fallback and verification. Cover difficult cases: mixed prose and chart pages, vector tables, multi-column layouts, scanned pages, empty/decorative pages, rotated pages, dense footnotes, cross-page tables, broken or misleading text layers.

Exit criteria:

- Text-only, visual, scanned, and mixed documents take appropriate paths.
- Usable text is retained on visual pages.
- Uncertain pages have a defined recovery path.
- Selective processing is evaluated against an all-visual and an all-text baseline on the same documents (cost, time, storage, retrieval quality).

## PHASE 4: RETRIEVAL, LEARNED ROUTING, AND GROUNDING

**Text retrieval:** dense retrieval, lexical/sparse where useful, document and metadata filters, optional reranking only if measurements justify it.

**Visual retrieval:** preserve multivectors; implement model-correct late-interaction (MaxSim) scoring with correct padding, masks, dimensions, and preprocessing; build a small exact-scoring reference first; then evaluate compressed candidates followed by original-multivector reranking. Do not assume every encoder shares dimension or patch grid. Use versioned collections with a safe reindex/switch/rollback process. Never mix incompatible embedding versions.

**Evidence selection:** fuse text and visual candidate rankings with an evaluated strategy (compare at least reciprocal rank fusion against one alternative). Deduplicate while keeping useful multiple regions/chunks. Apply bounded context budgets. Preserve coverage across explicitly requested documents. Add neighboring pages only when justified.

**Learned cost-aware routing (key differentiator):**

1. Build the evaluation set first (see Phase 7 sets; use a train split and a held-out split with no document-family leakage).
2. Run every retrieval tier on the training questions and cache the results: text-only, visual-only, hybrid fusion, and hybrid plus rerank.
3. Label each question with the cheapest tier whose answer is correct (or whose retrieved evidence contains the gold page).
4. Train a small router (start with embedding + logistic regression or gradient boosting on cheap query features; only try a small encoder if that underperforms).
5. The router chooses the **starting tier**. It is an escalation policy, not a gate: a verifier or low-confidence signal must be able to escalate to the next tier, so useful evidence is never permanently excluded.
6. Compare against: always-text, always-visual, always-hybrid, always-hybrid-plus-rerank, an LLM-prompted router, and a heuristic router. Report a cost-quality curve (quality vs. latency and vs. provider cost) on named hardware. Report honestly if the router does not beat the best fixed tier.

**Generation:**

- Label evidence with stable IDs and source metadata (document, version, page).
- Use structured response contracts for claims and citations; validate every citation ID against supplied evidence and reject unknown IDs.
- Handle missing, conflicting, and insufficient evidence; abstain honestly.
- Preserve original and rewritten follow-up questions.
- Provider deadlines and bounded retries.
- A syntactically valid citation does not prove semantic support: keep reference validation separate from claim-support evaluation (for example, a sampled NLI or LLM-judge check, clearly labeled as an estimate).

Exit criteria:

- Retrieval improves over the Phase 2 baseline on held-out tasks, or tradeoffs are documented.
- Sources resolve to correct document versions.
- Unanswerable questions are handled honestly.
- Comparison queries do not retrieve from only one requested source.
- The router result (or its honest failure) is reported with the cost-quality plot.

## PHASE 5: EVIDENCE WORKSPACE AND CONVERSATIONS (focused scope)

Build the minimum coherent product experience; defer anything not listed:

- Persistent conversations and messages with visible document scope.
- Library view with real ingestion progress, per-file errors, retry/cancel.
- Split-pane evidence viewer: citation previews, page navigation, thumbnails, zoom, preserved viewer position. Every citation opens the intended document version and page.
- Streamed answer events (ordered progress, answer-delta, final-answer, error); final structured citations are authoritative; handle disconnect and cancellation. Do not claim streaming reduces total compute.
- Clear empty, loading, offline, and failure states; keyboard accessibility; usable mobile navigation.
- Typed API contracts used consistently. A framework migration is optional and only if interaction complexity justifies it, with a working migration path.
- Replace invented analytics with real metrics or clearly labeled demo data.
- Sanitize all rendered Markdown/HTML; fix the inline-JavaScript filename handling.

Exit criteria: a user can upload, query, inspect evidence, revisit a conversation, and recover from a failure, on desktop and narrow screens.

## PHASE 6: ONE COMPLETE ANALYSIS WORKFLOW

Implement **only** evidence-linked comparison end to end, then stop unless time remains:

- Compare selected reports or versions; attach citations to every factual table cell; show missing evidence explicitly; preserve units, currencies, reporting periods, and scope.
- Save findings (answer, table, citations, verification status) and export machine-readable (JSON/CSV) and human-readable (Markdown or PDF) formats that stay linked to source/version and page. Enforce access checks on export.

**Optional, only after the above is verified and evaluated:** deterministic numerical calculations with reported-vs-calculated distinction; region questions; version review; retrieval similarity maps (only with correct model/grid metadata, labeled as retrieval similarity and never as proof of correctness).

Exit criteria: at least one multi-document comparison works end to end, numbers are reproducible, exports stay connected to evidence.

## PHASE 7: EVALUATION, HARDENING, AND RELEASE

**Evaluation suite:** text questions, exact identifiers, tables and numbers, charts and diagrams, multi-page reasoning, cross-document comparisons, version changes, scanned and mixed documents, unanswerable questions, varied document sizes. Use a pinned ViDoRe V3 subset where practical (check dataset terms) plus an internal product dataset. Avoid document-family and version leakage between development and held-out sets.

**Measure:** candidate recall, final retrieval relevance and coverage, answer correctness, numerical accuracy, citation validity and semantic support, abstention quality, ingestion throughput, cold and warm latency, time to first token and completion, peak RAM/VRAM, storage per page, provider usage/cost, and user time to verify findings.

**Compare:** (1) existing baseline, (2) text-only, (3) visual-only, (4) hybrid with fixed fusion, (5) hybrid with the learned router, (6) relevant optimized variants. Keep other variables fixed per comparison. Test the RTX 3050-class profile and any stronger system available; label unmeasured hardware as estimated.

**Harden:** authentication and authorization before any shared exposure; scope enforcement across search, files, conversations, caches, and exports; upload and processing limits; prompt-injection containment; secret handling; structured errors; timeouts and bounded retries; backup and restore; index migration and rollback; reproducible dependencies and containers; restrict CORS (no wildcard origins with credentials).

**Provide:** verified setup instructions, a local profile (and a shared profile only if verified), config examples without secrets, accurate architecture diagrams, a demo corpus with redistribution rights, API examples matching real responses, a benchmark report with hardware/configuration details, known limitations, and a feature matrix marking implemented / experimental / planned. Fix README claims that do not match reality (test counts, MaxSim claims, caching claims).

## TESTING REQUIREMENTS

- Unit tests: routing, chunking, identity, geometry, numeric functions, router feature extraction.
- Integration tests: storage, Qdrant, jobs, consistency.
- API tests: contracts, validation, authorization, errors.
- Browser tests for critical workflows.
- Failure and recovery tests: interrupted ingestion, restart, reindex rollback.
- Model-dependent quality and performance evaluations kept separate from routine tests; routine tests must run without model downloads or paid APIs.
- Mocks alone are not evidence that retrieval, generation, or deployment works.

## DELIVERY EXPECTATIONS

Give concise progress updates: what was learned, what changed, what remains uncertain, what the next validation will establish. Do not spend the task on documentation while leaving implementation incomplete.

At completion, report:

1. Implemented workflows and architectural changes.
2. Important files and configuration changes.
3. Tests and real checks performed.
4. Measured performance and quality results, including the router cost-quality plot.
5. Unverified assumptions and external blockers.
6. Exact instructions to run the upgraded application.
7. Remaining work, clearly separated from completed work.

Do not claim production readiness solely because tests pass.

**Begin with Step 0: verify the Phase 1-2 status, record the baseline, then start Phase 3.**