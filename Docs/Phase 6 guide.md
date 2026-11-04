# Phase 6: compare, inspect, save and export

The core Phase 6 workflow is implemented. Stop before Phase 7 and before the
optional analytical extensions. The app compares explicitly selected reports or
retained versions, cites factual cells, preserves reported context and saves
immutable findings with source-linked exports. It does not calculate differences,
convert currencies/units or infer that reporting periods/scopes are equivalent.

## Start and use

Restart the existing local application to load schema 6 and the new frontend:

```powershell
.\.venv\Scripts\python.exe -m vision_rag.api.main
```

Open `http://127.0.0.1:8000`. Use one process against the library. Existing CUDA,
OCR and provider settings are unchanged; no new dependencies are required.

1. Upload reports and wait for ingestion and retrieval indexing. Open **Findings**.
2. Select two to four distinct ready versions, including different versions of
   one report if desired. Enter one to eight fields, one per line, and a question.
3. Build the comparison. Each version receives a separate bounded evidence search
   so a dominant report cannot consume the entire source budget.
4. Inspect cell citations in the adjacent evidence pane. Each link opens the
   cited immutable version/page, including an older version rather than the
   current replacement. Page navigation, thumbnails and zoom remain available.
5. Check the reported unit, currency, period and scope. Differences are flagged;
   unstated context remains null/“Not stated”. Missing means no supported value
   in the retrieved evidence, not that the entire PDF lacks that information.
6. Optionally mark that you reviewed the cited evidence. This flag is explicitly
   user review, not an independent semantic verification claim. Give the finding
   a title and save it.
7. Reopen it from Saved findings after reload/restart and download JSON, CSV or
   Markdown. Completed grounded chat answers also have a **Save finding** action.

New comparisons are server-owned drafts. Refresh can reopen the last draft on
this browser; only saved records appear in the saved list. Titles and user review
flags can change, while answer/table/source content and its hash remain fixed.
Building a new comparison creates another record rather than rewriting evidence.

Comparison generation uses a normal bounded provider request, not the chat SSE
stream. Keep the page open while it completes. The UI displays a pending state;
chat cancellation/streaming remains separate. Provider quota/failure or invalid
structured output produces an error without saving a fabricated comparison.
When no selected evidence is indexed, missing cells can be returned locally
without initializing the provider.

## Source and cell contracts

Every request names exact version IDs. Ordinary chat search continues to exclude
superseded versions. Comparison retrieval can read retained ready index revisions
for explicitly selected versions, still checking workspace, live document,
ready build and matching page-processing revision. It uses each index's pinned
encoder profile and never mixes vectors across incompatible profiles.

There is one cell for every requested version/field pair. The server rejects
missing/duplicate matrix positions, unknown fields/versions, uncited factual
values and citations from a different version. A reported cell retains its raw
value plus separate unit, currency, period and scope fields. Missing cells cannot
assert values/context or citations. A conflicting cell must cite at least two
evidence IDs; differing values across reports are not automatically contradictions.

Reference validation proves that a supplied evidence ID maps to the intended
source version/page. It does **not** prove semantic support or numerical accuracy.
The stored verification status says semantic support is unverified, even when a
user marks the finding reviewed. Comparison summaries report matrix coverage;
they do not invent an analytical conclusion or new arithmetic.

At most six source images and the configured excerpt budget are shared across
selected versions. This is bounded retrieval, not exhaustive whole-document
reasoning. Older versions need a retained ready index with eligible pages. Versions
never indexed while active, or invalidated by reprocessing, can show missing
evidence. Current versions can be reindexed from Upload; no automatic historical
reindex or document activation is performed by comparison requests.

## Saved findings and exports

SQLite schema 6 adds workspace-scoped finding records: kind, draft/saved state,
immutable content JSON, SHA256, title, user review flag and timestamps. Comparison
content includes selected version ordinals, original PDF hashes, cells, evidence,
retrieval profiles, coverage/context warnings and provider usage when available.
Saved answers retain their original turn/request, claims and citations.

The content hash covers the canonical stored content, not mutable titles/review
metadata or the whole exported file. The hash does not independently prove that
a model answer is correct. Export URLs resolve through the same application and
library; they do not embed the PDF or grant access to another recipient.

| Format | Contents |
| --- | --- |
| JSON | Full finding, exact raw cell values, provenance, verification and source manifest |
| CSV | One cell/claim per row, reported context, citation IDs/links, review status and hash |
| Markdown | Readable comparison table or answer, cited page links, context warnings and source manifest |

CSV fields are quoted and suspicious spreadsheet prefixes are escaped for human
spreadsheet imports. `value_json` preserves the exact original value for programmatic
round trips, including values altered for display safety; full JSON is canonical.
No CSV strategy guarantees safe behavior in every spreadsheet after arbitrary
editing/resaving. See [OWASP's CSV guidance](https://github.com/OWASP/www-community/blob/master/pages/attacks/CSV_Injection.md).
Markdown escapes untrusted HTML/markup and keeps generated citation links separate.
Browser rendering uses text nodes, not provider-supplied HTML.

Reads, saves, review changes and **every export format** recheck workspace/source
availability. Deleted or unavailable sources block viewing/exporting the content;
the owned finding can still be deleted from the selector. An already downloaded
export cannot be revoked when a source is later deleted. These checks are local
workspace boundaries, not shared-user authentication or production authorization.

Clear history removes conversations and draft comparisons but keeps saved
findings. It waits for a comparison's publication boundary before clearing old
drafts. Cache clearing keeps findings. Start fresh removes all findings and
rejects mixed-workspace metadata, including another workspace's findings even
when it has no document rows. No automatic retention/pruning policy is included.

## API

Typed contracts are available in `/openapi.json`; clients cannot submit arbitrary
finding content to be treated as validated output.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/comparisons` | Build a comparison draft from question, version_ids and fields |
| `GET /api/v1/findings` | List saved finding metadata in this workspace |
| `GET /api/v1/findings/{id}` | Reopen an available finding |
| `POST /api/v1/findings/{id}/save` | Save the server-owned draft |
| `PATCH /api/v1/findings/{id}` | Change title/user review flag, never content |
| `DELETE /api/v1/findings/{id}` | Delete an owned finding |
| `POST /api/v1/findings/from-message/{id}` | Save a completed grounded chat answer |
| `GET /api/v1/findings/{id}/export?format=json\|csv\|md` | Source-checked download |

Draft export returns 409 until saved. Unavailable selected versions return 404;
invalid cells return 422; provider quota returns 429; deleted finding sources
block export with 409. Foreign workspace finding IDs return 404 without content.

## Verification

The routine suite runs without downloads or paid APIs and exercises real local
SQLite/Qdrant/PDFium where appropriate. Tests cover matrix completeness,
cross-version citation rejection, context retention, historical eligibility,
immutable finding hashes, save/reopen, all export formats, formula/HTML handling,
missing evidence without provider initialization, invalid-output nonpublication,
chat-answer findings, source deletion, reset/history and workspace isolation.

Final verification passed **123 tests** with two upstream deprecation warnings
in 90.8 seconds. Ruff lint/format, strict mypy (42 source files), Python
compilation, JavaScript syntax and whitespace checks passed. Test-run duration
is not a model latency measurement. See [verification record](phase6-verification.json).

The isolated browser fixture uses generated PDFs and simulated inference. It
compares an older Alpha version (120 million EUR, FY2024, consolidated) with Beta
(150 million USD, FY2025, parent company), leaving undisclosed margins missing.
Browser checks exercised citation inspection, review, save, reload/reopen and
actual JSON/CSV/Markdown downloads. Downloaded files were parsed and checked for
four cells, preserved currencies/review state and matching source URLs. Narrow
layout width equaled viewport width (384 CSS pixels), with table overflow inside
its panel. See [desktop](phase6-comparison.png) and [mobile](phase6-mobile.png).

A separate **real Gemini comparison request** passed on two fictional PDF pages:
both revenue values, million units, currencies, periods and scopes were preserved;
both undisclosed operating-margin cells were missing with no invented values.
The adapter returned all four cells with valid same-version references in about
11.2 seconds, using 4,108 provider-reported tokens. See the
[provider smoke record](phase6-provider-smoke.json). This was one adapter check,
not a retrieval benchmark, representative quality evaluation or dollar-cost claim.
No user documents were sent, model/key/billing settings were not switched, and
the earlier Phase 4 router comparison and Phase 5 live streaming checks were not
resumed by this test.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy src
node --check src/vision_rag/static/findings.js
# Disposable UI fixture on port 18006; no provider calls:
$env:PYTHONPATH='.;scripts;tests'
.\.venv\Scripts\python.exe -u tests/browser_phase6_fixture.py
# Optional: one real provider request, consuming account quota:
.\.venv\Scripts\python.exe scripts/check_phase6_provider.py
```

Optional deterministic calculations, region questions, automated version-diff
review and similarity maps were deliberately deferred. Broad real-document
quality, authentication/shared deployment, retention and release hardening remain
Phase 7 work. The original README and user research documents are preserved.
