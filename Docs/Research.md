# Research summary and original baseline

Consolidated 9 November 2026. This replaces the overlapping Upgrade Research
V1–V4 documents, original inspection and UX proposal. It retains their important
reasoning; obsolete execution prompts, duplicated proposals and stale instructions
such as “stop before Phase 4” are intentionally removed. This is historical
context and a backlog, not instructions to run another implementation phase.

## Original code baseline

The 2 November inspection found a compact visual PDF chat prototype: synchronous
upload/embedding, filename-based originals, in-memory Qdrant by default, pooled
page/query vectors and cosine search. The old README's MaxSim claim exceeded the
actual code. Counting/previews rendered whole PDFs, no persisted page cache
existed, chat state was browser-session-owned and the UI had illustrative analytics.

There was no relational document/version/job boundary, durable conversation store,
owner-authentication layer, comparison workflow or application backup tool. The
initial environment detected NVIDIA hardware but installed CPU-only Torch.
The inspection found six test functions, not the old badge's ten; four non-API
tests passed in that diagnostic run and two API tests were unverified there.

These are inspection findings, not claims that the older screenshot itself proves
backend behavior. The [upgrade history](Upgrade%20history.md) preserves old/new
pictures, architectural diagrams and phase-level implementation changes.

## How the research direction evolved

| Material replaced | Important direction retained | Current interpretation |
| --- | --- | --- |
| Research V1 | Source viewer, real MaxSim, scoped chat, streaming and comparisons | Core workflow implemented; heatmaps/formats still deferred |
| Research V2 | Dependable evidence inspection/comparison instead of a feature-count demo | Versioned evidence and a complete comparison workflow took priority |
| Research V3 | Merge product ambition with incremental delivery and evaluation | Seven implementation phases, with bounded tests and honest evidence |
| Research V4 | Continue from durable ingestion into hybrid retrieval, grounding and release | Phases delivered locally; unverified release gates remain open |
| UX proposal | A conversation-first document assistant with explicit scope | Implemented in the November workspace redesign |

The original product hypothesis remains: help users inspect and compare visually
complex reports with fewer unsupported claims and less verification effort.
Actual user verification time and broad answer quality have not been established.
Do not turn that hypothesis into a measured product claim.

## Principles carried into implementation

- Preserve original document versions and stable page references before adding
  analytical presentation or visual effects.
- Measure page work, model loading and retrieval separately; avoid attributing
  CPU rendering improvements to GPU inference.
- Correct representations and source eligibility before replacing models.
- Retain native text and select additional OCR/vision based on page evidence.
- Evaluate fixed text/visual/hybrid policies before enabling learned routing.
- Separate development/held-out document families and versions; do not tune on
  the final benchmark questions.
- Keep provider-free evidence discovery useful during quota/provider outages.
- Treat semantic support as different from syntactic citation validity.
- Deliver one complete compare → inspect → review → save → export workflow.
- Keep unverified shared deployment and hardware claims out of the supported profile.

## UX choices retained

The assistant should expose selected documents and original evidence, not require
users to understand embeddings, index profiles or model routing. Chat became the
default entry point; detailed processing controls remain available when needed.
The initial November workspace direction used ink black, cream and burnt orange,
square corners, restrained type and quiet dividers. By 12 November the interface
uses charcoal and cream, a separate public landing, a saved-data dashboard,
permanent searchable chat history and an adjustable original-page reader.
Current readiness text reflects real work. These are implementation updates,
not new research findings; see [Usage](Usage.md#reading-a-conversation-and-its-evidence).

Explicit source chips, safe empty scope, persistent recent chats, an inspectable
source drawer and a mobile sheet took priority over promotional dashboard art.
Reduced-motion and keyboard behavior are implemented, but broad accessibility
and real-user adoption still need evaluation. See [Usage](Usage.md#chat-and-evidence).

## Deferred ideas and the evidence needed first

| Idea | Current state | Before implementation/claiming benefit |
| --- | --- | --- |
| Patch/region similarity maps | Not shipped | Preserve correct model/grid geometry; label retrieval similarity, not proof |
| Region questions | Not shipped | Version/page/region contracts, coordinate validation and user tasks |
| Automatic version diffs | Not shipped | Compare aligned immutable pages; evaluate real revision-review tasks |
| Deterministic calculations | Not shipped | Reported-vs-calculated distinction, reproducible units/periods and tests |
| More document formats/connectors | PDF workflow first | Conversion/source provenance, limits, access control and format-specific evaluation |
| Alternate encoders/rerankers | No replacement selected from these proposals | Pinned, controlled quality/storage/latency comparison on held-out data |
| Shared multi-user deployment | Unverified | Verified TLS deployment, roles/tenancy, resource scope and recovery checks |
| Large-scale ANN optimization | Unverified | Representative candidate recall, index/storage cost and named hardware |

Early research mentioned other projects as inspiration. Their historical feature
comparisons and proposed time estimates are not maintained recommendations or
evidence that Vision ships equivalent functionality. The current status is in
the [documentation index](README.md#current-status) and [Validation](Validation.md).

## References retained from the earlier research

These were part of the historical reading list, not newly checked product claims:

- [ViDoRe V3 paper](https://arxiv.org/abs/2601.08620): retrieval evaluation context.
- [Qdrant PDF retrieval at scale](https://qdrant.tech/documentation/advanced-tutorials/pdf-retrieval-at-scale/)
  and [hybrid queries](https://qdrant.tech/documentation/hybrid-queries/): search design.
- [ColPali similarity maps](https://github.com/illuin-tech/colpali/blob/main/colpali_engine/interpretability/similarity_maps.py):
  background for deferred region/similarity-map work.
- [Docling document model](https://github.com/docling-project/docling/blob/main/docs/concepts/docling_document.md):
  background for deferred document conversion.
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output):
  generation contracts; model availability must be checked per account.
- [W3C accessibility guidance](https://www.w3.org/TR/wcag/) and
  [OWASP prompt-injection guidance](https://github.com/OWASP/www-project-top-10-for-large-language-model-applications/blob/main/2_0_vulns/LLM01_PromptInjection.md):
  evaluation/security considerations, not evidence of certification.
