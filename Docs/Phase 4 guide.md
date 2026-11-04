# Phase 4: retrieval and grounded answers

Phase 4 implementation is complete. Stop before Phase 5. The local evaluation,
GPU scoring smoke test, six sampled provider answer checks, and browser checks
ran successfully. The full LLM routing comparison remains incomplete because
the configured Gemini account reached its daily request quota. This is not a
production quality or performance certification.

## Start and use

Run the existing environment without replacing its CUDA installation:

```powershell
.\.venv\Scripts\python.exe -m vision_rag.api.main
```

Use one application process for the persistent local library. If port 8000 is
already occupied by this application, use that instance or stop it before
starting another. See [GPU setup](GPU%20setup.md) if rebuilding the environment;
a generic dependency sync can replace the separately installed CUDA Torch.
NumPy is now a direct dependency. Matplotlib is an optional `evaluation` extra,
needed only for the benchmark plot.

`PHASE4_ENABLED=true` is the default. Existing `.env` files inherit the new
defaults; `.env.example` lists the settings. First use downloads the pinned
public text encoder and visual adapter/base snapshots if they are not cached.
The BGE text encoder runs on CPU; ColPali uses the configured accelerator.
PDFium page rendering remains on CPU. `MODEL_WARMUP=true` explicitly loads both
encoders using a small query, without contacting Gemini. Otherwise they load
when needed. `/ready` reports visual model readiness, not provider availability
or index freshness; `/diagnostics` also reports text model loading.

1. Upload documents and wait for page processing, then retrieval indexing.
2. The Upload screen shows queued/building/ready/failed index revisions. **Build
   new index** creates a revision; activation happens after successful completion
   unless disabled in the API request. **Use this index** switches to another
   ready revision of the current source snapshot. A failed build leaves the
   previous index available.
3. In Chat, select up to six documents, or leave the selection empty to search
   the library. The API also supports page ranges and explicit retrieval tiers.
   Comparisons reserve evidence for each selected document.
4. Send a question for a structured answer. Click a numbered citation to open
   its immutable document version and page. Citations in older messages keep
   their own sources.
5. **Find pages** retrieves source pages and excerpts locally with no Gemini
   call. This also works while provider quota is exhausted. Answer requests
   return an actionable HTTP 429 in that case.

Existing delete, cache/history clearing and confirmed Start fresh controls also
clean Phase 4 data. Cleanup still handles retained Phase 4 collections if the
feature is subsequently disabled. Clearing derived artifacts does not erase
persistent indexed evidence; Start fresh does. Downloaded Hugging Face models
outside the library are not removed by a library reset.

## Retrieval and index contracts

- BGE-small-en-v1.5 produces 384-dimensional normalized CLS vectors, using its
  query instruction. Text is split by the actual tokenizer; overlong queries
  fail rather than silently truncating. SQLite FTS5 supplies keyword candidates.
- ColPali-v1.3 stores valid original 128-dimensional token embeddings. Attention
  padding and zero rows are removed; valid query augmentation tokens remain.
  MaxSim sums each query token's largest document-token dot product. The NumPy
  reference retains negative maxima and checks shapes/finiteness.
- Qdrant stores original-token DOT/MaxSim vectors and a normalized mean centroid.
  Exact visual search is the reference path; the rerank tier obtains centroid
  candidates and scores their original tokens. Compression reduces candidate
  representation, not the authoritative token representation. The verified
  embedded Qdrant engine performs local exact search; no large-scale ANN speedup
  is claimed. Server-mode operation has not been validated as a deployment.
- Fusion uses ranks rather than adding unrelated dense/keyword/visual scores.
  RRF and Borda are implemented. Borda is the default after development-set
  comparison. Source scores are rank scores, not answer confidence.
- Workspace, live document/version, build, page processing revision, selected
  document and page-range filters apply before retrieval limits. Deleted or
  superseded evidence stays excluded while replacement indexing runs.
- Evidence is deduplicated by version/page, at most three text chunks per page,
  at most six page images, and a configurable 14,000-character total excerpt
  budget. Truncation is recorded. Explicit comparisons require every selected
  document to remain represented in the final citations, or abstain.
- Durable index revisions use isolated collection UUIDs, immutable model/profile
  specifications, snapshot checks and an atomic SQLite active pointer. Retrying
  an interrupted build uses fresh collections. Missing vector storage marks an
  index failed and queues recovery. Current queries use the active profile's
  encoder revisions, including after rollback.
- Profile fingerprints cover model and base/adapter revisions, dimensions,
  scoring/pooling, rendering DPI and extraction/chunk configuration. Old pooled
  vectors never mix with new multivectors. Ready prior-phase source builds can
  seed the upgrade without reuploading the original PDFs.
- Rollback switches retrieval revisions of the **current source snapshot**; it
  does not restore a deleted document or roll back an original PDF version.
  Inactive revisions are retained and consume disk; automatic retention/pruning
  is not included. Document deletion removes its points from all revisions.

## Grounding and routing

The provider returns a strict status/claims/citations contract. Unknown evidence
IDs, malformed responses, uncited claims and incomplete comparison citations
are rejected. Supported and conflicting answers retain cited immutable page
references; insufficient evidence produces an abstention. Original and rewritten
queries are returned for simple pronoun-based follow-ups. This is a heuristic,
not persistent conversation memory.

Reference validation checks that a citation exists and resolves to the intended
version/page. It does **not** prove that the source entails the claim. Runtime
responses explicitly label semantic support unverified. Sampled same-model
support judgments in the evaluation are estimates, not independent proof.
Document content is explicitly treated as untrusted evidence in provider prompts.

The learned router is a small local softmax model over cheap query features. It
is trained on the cheapest successful cached development tier, with document
families kept separate from test families. Runtime routing can escalate on empty
or incomplete evidence, malformed claims or provider abstention, with at most
two generation calls. The provider has a configurable 30-second HTTP timeout
and two SDK attempts; this is a per-request bound, not a guaranteed total query
deadline across retries, model loading and escalation.

The learned router remains **off by default**. `ROUTER_PATH` may opt into a
matching-profile trained artifact. The included experiment uses 150 DPI and
cannot be enabled for a default 300 DPI index without retraining. Fixed hybrid
Borda is the normal policy. The evaluation's heuristic and prompted LLM router
are comparison policies, not additional runtime dependencies.

## Measured results

The [raw report](phase4-evaluation.json), [cost/quality plot](phase4-cost-quality.png)
and [model smoke report](phase4-model-smoke.json) record local measurements on the
RTX 4050 Laptop GPU, 6 GB, with Torch 2.13.0+cu130. The fixture contains 16 PDFs,
40 pages and 48 questions: four development families and four test families,
with 20 answerable and four unanswerable questions per split. Native prose,
tables, charts, scans, identifiers and two-document comparisons are included.
OCR is consistently disabled in this benchmark to exercise visual scan retrieval.
Families are disjoint, but share synthetic templates; these results do not
establish broad real-document generalization.

Gold page-set coverage @3 requires all annotated pages for an answerable test
question. It is a retrieval metric, not answer correctness.

| Policy | Test coverage | Mean retrieval ms |
| --- | ---: | ---: |
| Dense text + keyword | 16/20 | 133.2 |
| Exact visual MaxSim on routed pages | 12/20 | 179.7 |
| Hybrid RRF | 16/20 | 221.3 |
| Coarse rerank RRF | 16/20 | 218.5 |
| Hybrid Borda, default | 20/20 | 223.6 |
| Learned starting tier, experimental | 20/20 | 141.4 |
| Heuristic starting tier | 20/20 | 151.7 |
| Selective pooled visual, unscoped | 12/20 | 88.2 |
| All-page pooled, scoped | 20/20 | 45.7 |
| All-page pooled, unscoped | 18/20 | 45.9 |

Development coverage was 16/20 for RRF and 20/20 for Borda; default selection used
development data. Cached tier timings exclude generation, escalation and cheap
router decision overhead. The learned policy does not beat the scoped all-page
pooled baseline: that baseline matches coverage at much lower latency on this
small fixture. The selective pooled row is a Phase 3-style routed-page baseline,
not an all-page Phase 2 baseline. Neither learned routing nor multivectors are
claimed universally faster or more accurate.

Initial page ingestion took 149.8 seconds including cold loading; Phase 4 indexing
took 5.4 seconds using cached visual token artifacts. These times are not a fair
cold independent ingestion speed comparison. A real local Qdrant score differed
from the exact reference by about 1.58e-7. A separate CUDA processor comparison
also passed; its vectors contained 1,031 image and 19 query tokens.

Six sampled Borda answer checks passed, including numeric/table/chart/scan,
two-document comparison and abstention. Three same-model support estimates
were positive. Only **6 of 24** held-out prompted LLM routes completed before the
account's daily free-tier request limit of 20 was exhausted. The remaining LLM
comparison is pending quota reset and is excluded from the plot. Recorded usage
omits one early escalation response, and no exact dollar cost is established.
Only generated fictional documents were used for provider checks.

## Reproduce and resume

The benchmark writes an isolated ignored library under `.tools/phase4-evaluation`;
it does not ingest the user's document library. It can take several minutes on
first model download/load. Plotting requires the optional evaluation dependency.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_phase4.py --enrich-baseline
# After the provider quota resets, resume the partial paid/provider portion:
.\.venv\Scripts\python.exe scripts/evaluate_phase4.py --provider --provider-only
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy src
node --check src/vision_rag/static/app.js
```

The provider option makes real API requests and consumes account quota. Cached
local retrieval results and saved successful provider records are reused when
resuming; no model/key switching or billing change is needed to finish later.

Regression coverage includes MaxSim, filtering, activation/rollback, interrupted
builds, missing vectors, old-profile migration, deletion/reset with the feature
disabled, citation rejection, comparison coverage, malformed-response escalation,
provider deadlines/quota and provider-free search. Browser verification used
fictional PDFs with fake inference to check index activation, scoped chat and
the correct version/page citation preview. See [chat](phase4-chat.png) and
[citation preview](phase4-citation-preview.png).

The final regression run passed **107 tests**, with two upstream deprecation
warnings. Ruff lint/format, strict mypy (33 source files), compilation,
JavaScript syntax and whitespace checks passed.

Phase 5 persistent conversations, streaming and the broader evidence workspace
have not been started. Broader held-out real-document quality, hardware scaling,
retention policies and release/security gates remain later work.
