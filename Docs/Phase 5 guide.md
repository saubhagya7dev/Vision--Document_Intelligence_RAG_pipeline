# Phase 5: evidence workspace and conversations

Phase 5 adds saved conversations, live answer events and a split-pane evidence
viewer. Stop before Phase 6. The app remains a single-process local workspace;
shared deployment and authentication are later release work.

## Run and use

Use the existing environment and keep its installed CUDA Torch:

```powershell
.\.venv\Scripts\python.exe -m vision_rag.api.main
```

Open `http://127.0.0.1:8000`. Run one application process against the library.
If the port is already occupied by this app, use that instance or stop it first.
No new package installation or framework migration is needed for Phase 5.
The existing Phase 4 model and provider configuration applies.

1. Upload PDFs and inspect real page/job progress on Upload or Documents. Failed
   files retain errors and retry controls; running jobs retain cancellation.
2. Open Chat, create a conversation and select document scope. Leaving the
   selection empty uses automatic library-wide retrieval. Up to six documents
   can be selected for an explicit comparison.
3. Ask a question. Progress events show queueing, retrieval, generation and
   reference validation. Draft text is explicitly provisional; final structured
   answers replace it and carry authoritative citation mappings. Streaming does
   not reduce total inference compute and no latency improvement is claimed.
4. Click a citation or a source card to inspect its immutable version/page.
   Navigate pages, select thumbnails, zoom or open the original PDF. The last
   viewed version, page, zoom and scroll position are saved per conversation.
5. Reopen a conversation from the selector after reload or restart. Every turn
   retains its request scope, final answer, source versions and completion state.
   Later scope changes apply to future turns. Deleted documents remain recorded
   in saved scope/citations but are shown as unavailable when opened or queried.
6. Use Stop to cancel an active answer. Cancelled, interrupted and failed turns
   show retry controls. A retry creates a new turn and retains the old outcome.
   Find pages saves a local source-discovery result without calling Gemini.

Rename and delete controls manage individual conversations. Data & history →
Clear history removes saved conversations and their messages/events, while
keeping documents and ingestion recovery records. Start fresh also clears all
conversation data. Derived cache clearing preserves conversations and indexed
evidence. The downloaded model cache outside the library is unchanged.

Previous session-only chats are not imported into the new authoritative store.
Their old browser session keys remain until history is cleared; new saved chats
start with Phase 5. The browser stores only the last selected conversation ID
for navigation; SQLite is authoritative for conversation content.

## Storage and API contracts

SQLite schema 5 adds workspace-scoped conversations, question/message rows and
sequenced events. Each question row contains the question, request scope,
result, state and cancellation flag. Terminal result and final event publish in
one transaction, and a cancelled question cannot publish a late answer.
One conversation can have one pending turn at a time; the local process admits
at most four question workers. Expensive retrieval/generation remains serialized
through the existing library access boundary. This favors local consistency,
not concurrent multi-user throughput.

The API exposes typed Pydantic request/response models in `/openapi.json`:

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /api/v1/conversations` | List or create conversations |
| `GET/PATCH/DELETE /api/v1/conversations/{id}` | Reopen, rename/change scope/save viewer, or delete |
| `POST /api/v1/conversations/{id}/messages` | Start a durable question, returning HTTP 202 |
| `GET /api/v1/messages/{id}` | Inspect saved question state and result |
| `POST /api/v1/messages/{id}/cancel` | Request cooperative cancellation |
| `GET /api/v1/messages/{id}/events?after=N` | Replay ordered SSE events after a sequence |
| `GET /api/v1/versions/{id}/info` | Resolve live immutable version/page metadata |

Existing `/query` clients still work. Conversation requests reuse the same
query/answer contracts and grounding implementation. The conversation's saved
scope overrides a caller-supplied per-turn scope; document availability and
workspace membership are checked. Page ranges and viewer limits are validated.
The framework-free frontend has matching shape annotations and consumes server
responses rather than inventing source metadata.

SSE events use increasing IDs and the types `progress`, `answer-delta`,
`final-answer`, and `error`. A draft reset event clears text when grounding
escalates to another tier. The stream drains committed terminal events before
closing, including races between event polling and result publication. The
cursor supports replay; the UI reopens pending turns from persisted state.

Disconnect requests cancellation. Restart marks unfinished turns interrupted,
with retry guidance. Cancellation is cooperative: it checks queue/retrieval,
page and provider-chunk boundaries, closes the provider stream and suppresses
late publication. It cannot interrupt an in-flight GPU kernel or guarantee that
the remote provider stops billing immediately. An unresponsive provider can
remain pending until its configured HTTP timeout/retry boundary. Reconnecting
does not automatically repeat a cancelled paid request.

## Rendering and interaction

The evidence panel sits beside messages on desktop and below them on narrow
screens. Page controls, thumbnails and citation links use native keyboard
controls, visible focus and accessible labels. Progress/status regions announce
changes; a skip link moves focus without changing the SPA route. Mobile
navigation stays visible and the tested narrow layout has no page-wide
horizontal overflow.

Question, answer, filename and excerpt content is rendered through text nodes
or `textContent`, not interpreted as HTML. The answer renderer supports a small
safe formatting subset (bold, inline code and validated citation links); other
Markdown is displayed as text. Source actions use event listeners, not inline
JavaScript with interpolated filenames. The existing escaped library rendering
continues to protect document labels.

The dashboard's invented weekly bars were removed. It now reports live document
page totals, pending jobs and completed persisted questions. Saved-answer counts
fall when conversations/history are deleted; these are retained local records,
not lifetime analytics or provider usage totals. Collection health remains a
storage status, not a claim of model/provider readiness.

## Verification and limitations

The regression suite covers disk persistence, workspace isolation, immutable
turn scope, restart recovery, ordered replay, atomic final results, cancellation,
provider chunk decoding, stream closure, history/reset cleanup and dashboard
metrics. API checks include source version/page resolution and filenames with
quotes and markup characters. Tests use fake inference and never download
models or make paid calls.

Final verification: **115 tests passed**, with two upstream deprecation warnings.
Ruff lint/format, strict mypy (36 source files), Python compilation, all three
frontend JavaScript syntax checks and whitespace checks passed. The full suite
took 69.0 seconds locally; this is test-run duration, not model latency.

The isolated browser fixture uses generated PDFs, real SQLite/Qdrant/PDFium and
simulated provider chunks, failures and slow responses. Browser checks exercised
saved conversations, scope, citations, page navigation, zoom restoration,
keyboard page navigation, cancellation/retry, real HTTP disconnect recovery,
failure states and local Find pages. At the narrow viewport, document width
equaled viewport width (384 CSS pixels). These checks validate workflow wiring,
not answer quality. See [desktop](phase5-workspace.png) and
[mobile](phase5-mobile.png) screenshots.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy src
node --check src/vision_rag/static/workspace.js
node --check src/vision_rag/static/evidence.js
```

To run the separate disposable UI fixture (port 18005):

```powershell
$env:PYTHONPATH='.;scripts;tests'
.\.venv\Scripts\python.exe -u tests/browser_phase5_fixture.py
```

No new model/provider quality benchmark was run in Phase 5. The SDK streaming
adapter is tested with controlled chunks; live Gemini streaming and the remaining
Phase 4 prompted-router comparison remain externally unverified because of the
previous account quota limit. See [Phase 4 guide](Phase%204%20guide.md) for the
measured retrieval results and their limits. Do not infer production readiness
or independent semantic verification from passing workflow tests.

Phase 6 saved findings, analytical comparisons and exports are not implemented
by this phase. Broader accessibility auditing, shared access controls, retention
and real-provider/hardware performance measurements remain later work.
