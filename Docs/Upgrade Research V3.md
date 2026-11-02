# Upgrade Plan v3 (combines V1 AND V2)
**You are the lead full-stack engineer, systems architect, and retrieval engineer responsible for upgrading Vision into a fast, dependable hybrid text-and-vision document intelligence product.**

**Work directly in the existing repository. Deliver working software through incremental, validated phases. Preserve useful existing functionality and make architectural changes where they solve demonstrated problems.**

**Your responsibility includes backend architecture, document processing, retrieval, generation, frontend experience, persistence, security, deployment, testing, and performance evaluation.**

**Do not stop at proposing an architecture or producing scaffolding. Implement complete workflows, verify them, and report their practical limits.**

**PROJECT CONTEXT**

**Vision currently follows this approximate pipeline:**

**PDF → rendered page images → local ColPali embeddings → Qdrant retrieval → retrieved page images → Gemini-generated answer.**

**The existing application uses:**

- **Python and FastAPI.**
- **pypdfium2 for PDF rendering.**
- **colpali-engine and PyTorch for embeddings.**
- **Qdrant for vector search.**
- **Google GenAI SDK for Gemini.**
- **A plain HTML/CSS/JavaScript frontend.**

**Read these repository documents first:**

- **README.md**
- **Docs/Project understanding.md**
- **Docs/Deep upgrade research.md**
- **Docs/Upgrade research.md**

**Read applicable AGENTS.md instructions and inspect the actual implementation. The documents describe earlier inspections and proposals; verify important claims against the current checkout.**

**Previously observed issues include:**

- **Mean-pooling ColPali patch and query embeddings instead of true late-interaction scoring.**
- **CPU-only PyTorch in the development environment despite an available NVIDIA GPU.**
- **Rendering complete PDFs to obtain individual pages.**
- **Rendering PDFs merely to count pages.**
- **Rendering and embedding entire documents in one batch.**
- **In-memory indexes disappearing on restart.**
- **Duplicate vectors and stale references after repeated uploads.**
- **Synchronous expensive work inside async request handlers.**
- **Lazy model loading adding delay to the first request.**
- **Browser-only conversations.**
- **Unlabeled image context and source lists without claim-level grounding.**
- **Incorrect Qdrant statistics.**
- **Insufficient upload/path validation.**
- **Incomplete automated validation and misleading documentation claims.**

**These are investigation starting points, not permission to assume the current implementation is unchanged.**

**PRODUCT OBJECTIVE**

**Build Vision into a visual evidence workspace that can:**

1. **Ingest large and mixed-content documents efficiently.**
2. **Search text and visual evidence together.**
3. **Answer with inspectable citations.**
4. **Support conversations scoped to selected documents.**
5. **Compare reports and document versions.**
6. **Produce useful findings and exports.**
7. **Preserve document identity, provenance, and access boundaries.**

**A representative workflow is:**

**Select documents → ask a question → retrieve relevant text and visual evidence → receive a grounded answer or comparison → inspect supporting pages/regions → save or export findings.**

**Use financial and technical reports as representative evaluation workloads, while keeping the underlying architecture applicable to other domains.**

**HARDWARE AND PERFORMANCE PRINCIPLES**

**Do not optimize exclusively for the developer’s current GPU.**

**RTX 3050-class laptops and stronger systems are the intended baseline. That class includes different VRAM capacities and power limits; do not assume identical performance or memory.**

**Provide hardware-adaptive execution:**

- **Detect accelerator availability and relevant capabilities.**
- **Distinguish a CPU-only PyTorch installation from unavailable hardware.**
- **Choose supported precision and bounded batch sizes.**
- **Offer configurable model/performance profiles.**
- **Provide explicit CPU fallback behavior.**
- **Avoid loading unnecessary models simultaneously.**
- **Handle memory pressure without silently dropping pages.**
- **Expose actionable diagnostics when a configuration cannot run.**
- **Allow stronger local or remote hardware to improve throughput.**

**Separate:**

- **Cold-start time.**
- **Ingestion throughput.**
- **Queueing delay.**
- **Retrieval latency.**
- **Time to first answer token.**
- **Total answer completion time.**

**Do not invent speedup percentages or guarantee universal response times. Establish measured baselines on named hardware, workloads, and configurations.**

**HYBRID RAG DESIGN**

**The central design is selective text-and-vision processing.**

**Do not implement a rigid “text page OR visual page” classification.**

**Requirements:**

- **Extract usable native text from every page where available.**
- **Preserve page identity and text-to-page mapping.**
- **Additionally process meaningful visual content when needed.**
- **Handle scanned pages and unreliable text extraction.**
- **Preserve useful text on pages that also contain visuals.**
- **Retain a fallback for uncertain page classifications and visual questions.**

**A logo should not automatically trigger expensive visual processing.
The absence of embedded bitmap images does not prove a page has no visual content: tables and diagrams can use text and vector drawing operations.**

**Use a staged strategy:**

1. **Cheap native extraction and page inspection.**
2. **Extraction-quality and layout heuristics.**
3. **Selective layout analysis, OCR, or visual encoding.**
4. **Fallback handling where confidence is insufficient.**

**Do not call an expensive VLM on every page merely to decide whether a VLM is needed.**

**At query time:**

- **Respect selected document scope and permissions.**
- **Retrieve text and visual candidates as appropriate.**
- **Avoid a brittle router that permanently excludes useful evidence.**
- **Merge candidates using an evaluated fusion strategy.**
- **Rerank a bounded candidate set where beneficial.**
- **Send only necessary evidence to generation.**
- **Preserve source identity across every stage.**
- **Support answers that require both prose and charts/tables.**

**Text and visual embedding spaces are different. Do not compare their raw similarity scores as if they were calibrated equivalents.**

**TECHNOLOGY SELECTION**

**Evaluate tools according to measured quality, latency, memory, maintenance, licensing, and integration effort.**

**Potential candidates include:**

- **PyMuPDF or an appropriate alternative for fast native text extraction and page geometry.**
- **Existing pypdfium2 for page rendering where suitable.**
- **Docling for selective layout/table processing and OCR workflows.**
- **Sentence Transformers-compatible text encoders.**
- **BGE-small as an English speed baseline.**
- **Qwen3-Embedding or BGE-M3 where multilingual or other quality needs justify them.**
- **ColPali as the existing visual baseline.**
- **ColSmol and ColQwen-family encoders as candidates for different performance profiles.**
- **Qdrant for dense, sparse, and multivector retrieval.**
- **Gemini through a provider abstraction for multimodal generation.**
- **A relational metadata database and durable artifact storage.**

**These are candidates, not mandatory dependencies.**

**Verify current APIs, model loading requirements, licenses, and compatibility through official documentation and model cards before adopting them. Account for licenses of underlying models and document-processing dependencies.**

**Do not add LangChain, LlamaIndex, a graph database, or an agent framework unless it solves a concrete need. Direct orchestration is acceptable.**

**EXECUTION METHOD**

**Before implementation:**

- **Inspect repository structure, current Git state, environment, tests, and runtime.**
- **Preserve unrelated user changes.**
- **Identify what can be measured locally without downloading large models or invoking paid services.**
- **Establish an implementation checklist with dependencies and phase exit criteria.**
- **Record major architectural decisions briefly.**

**Ask questions only when missing information genuinely blocks a consequential decision. Otherwise proceed with documented assumptions.**

**Prefer small working vertical slices over broad placeholder implementations.**

**For each phase:**

1. **Establish the relevant baseline.**
2. **Implement the workflow.**
3. **Run appropriate automated checks.**
4. **Exercise realistic success and failure scenarios.**
5. **Update documentation and configuration examples.**
6. **Summarize results and remaining limitations.**
7. **Continue to the next phase when its prerequisites are satisfied.**

**If external credentials, hardware, or services are unavailable, complete independent work and clearly identify what remains unverified. Do not simulate successful external validation.**

**PHASE 1 — DIAGNOSIS AND PERFORMANCE FOUNDATIONS**

**Add structured stage timings for:**

- **Model loading.**
- **Upload handling.**
- **Text extraction.**
- **Page inspection.**
- **Rendering.**
- **Embedding.**
- **Database operations.**
- **Query embedding.**
- **Candidate retrieval.**
- **Reranking.**
- **Evidence preparation.**
- **Provider response and generation.**

**Use request/job trace IDs. Avoid logging secrets or full private document content by default.**

**Inspect PyTorch/CUDA compatibility and report actionable environment diagnostics.**

**Implement:**

- **Bounded rendering and embedding batches.**
- **Single-page rendering.**
- **Direct page counting without rasterization.**
- **Cached page artifacts and thumbnails.**
- **Explicit model lifecycle and readiness.**
- **Controlled inference concurrency.**
- **Resource cleanup.**

**Avoid indiscriminately lowering resolution: evaluate small text, tables, and chart labels.**

**Distinguish expensive initialization from steady-state performance.**

**Exit criteria:**

- **Major stages are measurable.**
- **Individual-page access does not render the whole document.**
- **Peak work is bounded by configured batches.**
- **Device selection is explicit.**
- **Existing workflows remain functional.**

**PHASE 2 — DURABLE DOCUMENT AND JOB FOUNDATION**

**Introduce authoritative metadata records for:**

- **Documents.**
- **Immutable document versions.**
- **Content hashes.**
- **Page artifacts.**
- **Index builds.**
- **Ingestion jobs.**
- **Processing and failure states.**

**Store originals under generated storage keys. Keep user filenames as display metadata.**

**Implement:**

- **Upload validation and configurable resource limits.**
- **Safe path handling.**
- **Scoped deduplication.**
- **Deterministic page/index identities.**
- **Explicit replacement/version semantics.**
- **Persistent vector storage.**
- **Durable background ingestion.**
- **Stage-based progress.**
- **Retry and cancellation.**
- **Restart recovery.**
- **Retryable deletion cleanup.**

**Suggested job states:
uploaded → validating → extracting/rendering → embedding → indexing → ready,
with failed and cancelled paths.**

**Expose only ready index builds to retrieval.**

**Do not assume metadata, artifact storage, and Qdrant participate in one transaction. Use an explicit consistency strategy with reconciliation or compensating operations.**

**Local and shared deployments may use different adapters, but support one verified default profile first.**

**Exit criteria:**

- **Repeated uploads do not create uncontrolled duplicates.**
- **Restart and retry do not corrupt state.**
- **Partial failures are visible and recoverable.**
- **Deleted documents stop appearing in retrieval.**
- **Index and source versions remain aligned.**

**PHASE 3 — HYBRID TEXT AND VISUAL INGESTION**

**Implement:**

- **Native text extraction with page references.**
- **Quality checks for missing or corrupted extraction.**
- **Structure-aware, token-bounded text chunking.**
- **Configurable overlap and preserved heading/page metadata.**
- **Meaningful visual-content detection.**
- **Selective OCR/layout analysis.**
- **Additional visual embeddings for relevant or uncertain pages.**
- **Persisted routing decisions with reasons and processing versions.**

**Keep original documents available for fallback and verification.**

**Include difficult cases:**

- **Mixed prose and chart pages.**
- **Vector-drawn tables.**
- **Multi-column layouts.**
- **Scanned pages.**
- **Empty/decorative pages.**
- **Rotated pages.**
- **Dense footnotes.**
- **Cross-page tables.**
- **Documents with misleading or broken text layers.**

**Allow users or administrators to override processing decisions and reprocess affected pages.**

**Exit criteria:**

- **Text-only, visual, scanned, and mixed documents use appropriate paths.**
- Usable text is retained on visual pages.
- Uncertain cases have a defined recovery path.
- Selective processing is evaluated against an appropriate baseline.

PHASE 4 — RETRIEVAL, GENERATION, AND GROUNDING

Text retrieval:

- Dense retrieval.
- Lexical/sparse retrieval where useful.
- Document and metadata filters.
- Optional reranking justified by measurements.

Visual retrieval:

- Preserve multivectors.
- Implement model-correct late-interaction scoring.
- Handle padding, masks, dimensions, and preprocessing correctly.
- Use a small exact-scoring reference before optimizing candidate retrieval.
- Evaluate compressed candidates followed by original-multivector reranking.

Do not assume every encoder uses the same embedding dimension or patch grid.

Create versioned collections/indexes and a safe reindex/switch/rollback process. Never silently mix incompatible embedding versions.

Evidence selection:

- Fuse text and visual candidate rankings.
- Deduplicate appropriately while preserving useful multiple regions/chunks.
- Apply bounded context budgets.
- Preserve coverage across explicitly requested documents.
- Add neighboring pages only when justified.

Generation:

- Label evidence with stable IDs and source metadata.
- Use structured response contracts for claims and citations.
- Validate citation references against supplied evidence.
- Handle missing, conflicting, and insufficient evidence.
- Preserve original and rewritten follow-up questions.
- Add provider deadlines and bounded retry behavior.

A syntactically valid citation does not prove semantic support. Keep reference validation separate from claim-support evaluation.

Exit criteria:

- Retrieval improves or has explicitly documented tradeoffs on held-out tasks.
- Sources resolve to the correct document versions.
- Unanswerable questions are handled honestly.
- Comparison queries do not retrieve evidence from only one requested source.
- No generated source identifiers are accepted without validation.

PHASE 5 — EVIDENCE WORKSPACE AND CONVERSATIONS

Create a coherent, responsive product experience.

Core areas:

- Library and collections.
- Conversation/findings workspace.
- Evidence viewer.
- Comparison.
- Saved findings.
- Settings and processing diagnostics.

Implement:

- Persistent conversations and messages.
- Visible document scope.
- Split-pane document viewing.
- Citation previews and navigation.
- Page thumbnails, zoom, and preserved viewer position.
- Real ingestion progress and per-file errors.
- Retry/cancel actions.
- Streamed answer events.
- Clear empty, loading, offline, and failure states.
- Keyboard accessibility and usable mobile navigation.

Define typed API contracts and use them consistently.

A frontend framework migration is optional. Adopt one if justified by interaction complexity, with a working migration path.

Use a restrained visual system and readable document presentation. Replace invented analytics with real metrics or clearly marked demo data.

For streaming:

- Define ordered progress, answer-delta, final-answer, and error events.
- Treat final structured citations as authoritative.
- Handle disconnects and cancellation.
- Do not claim streaming reduces total model computation.

Exit criteria:

- A user can upload, query, inspect evidence, revisit a conversation, and recover from a failure.
- Every citation opens the intended source version/page.
- Core flows work with keyboard navigation and narrow screens.

PHASE 6 — DISTINCTIVE ANALYSIS FEATURES

Implement incrementally:

A. Evidence-linked comparisons

- Compare selected reports or versions.
- Attach citations to factual table cells.
- Show missing evidence explicitly.
- Preserve units, currencies, reporting periods, and scope.

B. Numerical calculations

- Store extracted raw values and normalized values.
- Validate units and periods.
- Use deterministic calculation functions.
- Distinguish reported values from calculated results.
- Preserve input citations and calculation provenance.

C. Region questions

- Select a chart/table/diagram region.
- Preserve source coordinates, rotation, and render transforms.
- Include surrounding context when needed.
- Label visually estimated values as approximate.

D. Version review

- Align pages or sections before comparison.
- Distinguish formatting changes from candidate semantic changes.
- Show evidence from both versions.
- Require review before presenting uncertain changes as established facts.

E. Saved findings and exports

- Save answers, tables, crops, and citations.
- Export useful machine-readable and human-readable formats.
- Preserve source/version references and verification status.
- Enforce access checks for export creation and download.

F. Retrieval similarity maps

- Implement only with correct model/grid metadata.
- Label them as retrieval similarity.
- Do not present them as proof of answer correctness or verified localization.

Exit criteria:

- At least one complete multi-document analysis workflow works end to end.
- Numerical results are reproducible.
- Exported findings remain connected to their evidence.

PHASE 7 — EVALUATION, HARDENING, AND RELEASE

Build an evaluation suite containing:

- Text questions.
- Exact identifiers.
- Tables and numerical questions.
- Charts and diagrams.
- Multi-page reasoning.
- Cross-document comparisons.
- Version changes.
- Scanned and mixed documents.
- Unanswerable questions.
- Different document sizes.

Use a representative ViDoRe V3 subset where practical, with pinned versions and appropriate dataset terms. Keep an internal product-focused dataset as well.

Avoid document-family/version leakage between development and held-out sets.

Measure:

- Candidate recall.
- Final retrieval relevance and coverage.
- Answer correctness.
- Numerical accuracy.
- Citation validity, coverage, and semantic support.
- Abstention quality.
- Region alignment where implemented.
- Ingestion throughput.
- Cold/warm latency.
- Time to first token and completion.
- Peak RAM/VRAM.
- Storage per page.
- Provider usage/cost where available.
- User time to verify findings.

Compare:

1. Existing baseline.
2. Text-only pipeline.
3. Visual-only pipeline.
4. Proposed hybrid pipeline.
5. Relevant optimized variants.

Keep unrelated variables fixed when evaluating a component.

Test representative hardware profiles, including RTX 3050-class constraints and stronger systems. Clearly distinguish measured results from estimated behavior on unavailable hardware.

Harden:

- Authentication and authorization before shared exposure.
- Scope enforcement across search, files, conversations, caches, and exports.
- Upload and processing limits.
- Markdown/HTML sanitization.
- Prompt-injection containment.
- Secret handling.
- Structured errors.
- Timeouts and bounded retries.
- Backup and restore.
- Index migration and rollback.
- Dependency/container reproducibility.

Treat document text and images as untrusted content. Enforce permissions outside the model. Keep arbitrary tool execution out of the answering pipeline unless separately justified and secured.

Provide:

- Verified setup instructions.
- Local and shared deployment profiles.
- Configuration examples without secrets.
- Accurate architecture diagrams.
- A representative demo corpus with redistribution rights.
- API examples matching real responses.
- A benchmark report with hardware/configuration details.
- Known limitations.
- A feature matrix distinguishing implemented, experimental, and planned behavior.

TESTING REQUIREMENTS

Use meaningful tests appropriate to the changes:

- Unit tests for routing, chunking, identity, geometry, and numeric functions.
- Integration tests for storage, Qdrant, jobs, and consistency.
- API tests for contracts, validation, authorization, and errors.
- Browser tests for critical product workflows.
- Failure/recovery tests for interrupted ingestion and restart.
- Separate model-dependent quality/performance evaluations.

Keep routine tests deterministic and runnable without model downloads or paid APIs.
Mocks alone are not evidence that retrieval, generation, or deployment works.
Do not report skipped or unavailable checks as passing.

ARCHITECTURAL RESTRAINT

Do not add:

- A knowledge graph without a validated relationship-reasoning need.
- Autonomous agents before reliable retrieval and evidence contracts.
- Kubernetes without an operational requirement.
- Multiple databases or queues that duplicate responsibilities.
- Every model/provider/file format at once.
- Fine-tuning before simpler correctness issues are ruled out.
- Decorative dashboards or fabricated metrics.

Prefer a modular application with explicit worker boundaries over premature distributed services.

DELIVERY EXPECTATIONS

Maintain concise progress updates explaining:

- What was learned.
- What changed.
- What remains uncertain.
- What the next validation will establish.

Do not spend the entire task producing documentation while leaving implementation incomplete.

At completion, report:

1. Implemented workflows and architectural changes.
2. Important files and configuration changes.
3. Tests and real checks performed.
4. Measured performance and quality results.
5. Unverified assumptions and external blockers.
6. Exact instructions to run the upgraded application.
7. Remaining work, clearly separated from completed work.

Do not claim the project is production-ready solely because tests pass.

Begin by inspecting the repository and establishing the performance baseline. Then implement the phases in dependency order, adapting details based on evidence while preserving the product objective.