# Implementation and architecture

Consolidated 9 November 2026 from phase designs, guides and architectural decisions.
The [upgrade history](Upgrade%20history.md) records the old/new diagrams and each
phase. [Usage](Usage.md) contains setup and operational procedures.

## Storage and jobs

One process owns each library. SQLite owns document identity, immutable original
versions, page extraction/revisions, builds, jobs, conversations, events and
findings. Display filenames are not storage keys. Originals use generated keys;
content hashes provide scoped deduplication and explicit replacement semantics.

```text
data/
  metadata.sqlite3          authoritative records and queues
  metadata.sqlite3-wal      recovery files when present
  .library.lock            local process ownership
  originals/<uuid>.pdf     immutable managed originals
  incoming/<uuid>.part     upload staging
  artifacts/              regenerable pages/thumbnails/token artifacts
  qdrant/                 persistent local vectors
```

Upload returns HTTP 202 with a durable job. A single worker records stage/page
progress, retry/cancel and restart recovery. Stable vector identities prevent
duplicate publication on retry. A replacement publishes only after expected work
completes; failure leaves previous evidence ready. Deletion hides evidence before
retryable cleanup, including retained retrieval revisions. Reset markers and a
library-generation fence prevent pre-reset uploads from resurrecting data.

`QDRANT_MODE=local` is the persistent embedded default; memory is disposable and
server mode is unverified. `WORKSPACE_ID` is a configured scope, not a user account.
Owner authentication is a separate boundary. Multiple processes cannot share this
embedded storage directory.

## Extraction and routing

PDFium supplies metadata counting, CPU page rendering, native Unicode extraction
and geometry/layout signals. A process-wide lock serializes PDFium; explicit
image/handle cleanup and bounded batches limit transient memory. Content-addressed
artifacts include renderer/DPI identities; atomic writes and regeneration recover
from incomplete/corrupt cache files.

Native text is retained even when vision is selected. Heading-aware, page-local
chunks, quality/layout signals and processing reasons persist in SQLite.
Tables/vector rules, columns, rotations, uncertain text and dense small content
can select additional visual processing. These are conservative heuristics, not
an unrestricted table parser. Optional local OCR has a deadline and warning-based
visual fallback. Reprocessing a page creates durable revisioned work and hides
only affected evidence while pending/failed.

ColPali inference uses the configured device/precision. CUDA requires a compatible
Torch build; rendering itself stays on CPU. Inference is serialized; multi-item
memory failures retry individual items, while single-item failure reports a
configuration problem. Model lifecycle initialization and cleanup are synchronized.

## Retrieval and grounding

| Channel | Representation / scoring |
| --- | --- |
| Dense text | Pinned BGE-small, CPU, 384-dimensional normalized CLS vectors |
| Keyword | SQLite FTS5 candidates |
| Original visual | ColPali valid token matrices, 128 dimensions per token, DOT/MaxSim |
| Coarse visual | Normalized token centroid; rerank candidates against original tokens |
| Pooled baseline | Historical mean-token representation, isolated from current matrices |

Text uses the real tokenizer for bounded windows; overlong queries fail instead
of silently truncating. Visual padding/zero rows are removed while valid query
augmentation tokens remain. Exact MaxSim sums each query token's largest
document-token dot product; the reference checks shape/finiteness and preserves
negative maxima. Embedded search is verified locally; no large-scale ANN speedup
is inferred from those measurements.

Rank fusion avoids adding incomparable raw scores. RRF/Borda are implemented;
Borda is the default from development-set comparison. Scores are not confidence
probabilities. Eligibility applies workspace, live version, build/profile,
processing revision, selected documents and page ranges before retrieval limits.
Evidence is deduplicated by version/page, bounded to at most six page images,
three text chunks per page and a configurable excerpt budget (default 14,000 chars).

Index revisions have isolated collections, immutable profile specifications,
snapshot checks and an atomic active pointer. Profiles include model/base/adapter
revisions, dimensions, scoring/pooling, DPI and extraction/chunk configuration.
Interrupted builds use fresh collections; missing storage triggers recovery.
Activation/rollback applies to eligible revisions of the current source snapshot.
Inactive revisions consume disk; automatic retention/pruning is not implemented.

The provider returns status, claims and supplied evidence IDs. Unknown references,
uncited/invalid contracts and incomplete explicit comparison coverage are rejected.
Insufficient evidence has an abstention path. References resolve immutable
version/pages; that is not independent semantic entailment. Document instructions
remain untrusted data; there is no claim that prompt injection is solved.

Original and rewritten follow-ups are retained. Provider timeout/SDK retries and
generation escalation are bounded; a per-request timeout is not a total query SLA
including model load and retries. The experimental local softmax router chooses
a starting tier and can escalate on unusable evidence/answers. It is off by
default. The retained 150-DPI router artifact cannot simply be applied to a default
300-DPI index: `ROUTER_PATH` requires a matching profile and retraining when needed.

## Conversations, comparisons and exports

Server records own conversations, immutable turn source scope, results and ordered
events. SSE exposes progress, provisional deltas and an authoritative validated
final answer. Disconnect/restart/cancel paths produce explicit interrupted states.
GPU/provider work may finish before cancellation reaches a safe boundary.

The current frontend requires explicit selection for new questions, saves tab-local
drafts and uses text-node rendering for untrusted content. Version-specific viewer
state and source lookup prevent replacements from silently changing an old citation.

Comparison selects two to four versions and reserves bounded evidence per version.
Each field/version has reported/missing/conflicting status, reported context and
citations. Historical versions require retained eligible indexes. Findings retain
immutable content and hashes with mutable title/review metadata. Export routes
check source availability and owner access, and sanitize spreadsheet/Markdown
outputs. Missing evidence is not a computed zero; no implicit currency conversion
or calculated financial result is introduced.

## Design decisions

- Keep FastAPI, plain JavaScript, PDFium and the local SQLite/Qdrant boundary;
  add lifecycle/evidence contracts rather than a framework migration.
- Prefer immutable versions and profile-isolated indexes over in-place mutation.
- Keep useful native text and visual fallback together instead of claiming OCR-free
  processing for every input.
- Pin models and compare fixed policies before introducing a learned router;
  the measured router has no established general cost advantage.
- Separate citation-reference validity, user review and independent semantic support.
- Keep local owner access explicit; do not imply enterprise tenancy or shared readiness.
- HMAC-authenticate backup manifests before local Qdrant deserialization. Integrity
  checks alone do not make untrusted pickle-based storage safe to open.
- Use generated fixtures for deterministic tests and distinct real-model/provider
  reports for quality/performance evidence. Missing measurements remain open gates.

## Source map

| Responsibility | Code |
| --- | --- |
| HTTP/owner boundary | [`api/`](../src/vision_rag/api/) |
| Metadata, versions, jobs and ownership | [`storage/`](../src/vision_rag/storage/) |
| Rendering/extraction/OCR/routing | [`ingest/`](../src/vision_rag/ingest/) |
| Encoders and provider adapters | [`models/`](../src/vision_rag/models/) |
| Eligibility, index lifecycle and scoring | [`retrieval/`](../src/vision_rag/retrieval/) |
| Grounding/events | [`generate/`](../src/vision_rag/generate/) |
| Cited comparisons | [`analysis/`](../src/vision_rag/analysis/) |
| Workspace and evidence UI | [`static/`](../src/vision_rag/static/) |
| Backup | [`backup.py`](../src/vision_rag/backup.py) |

See [Validation](Validation.md) for what was actually measured and
[Research](Research.md) for retained product intentions that are not shipped features.
