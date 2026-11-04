# Upgrade decisions

## Phase 3 — 2026-11-03

- Baseline: the existing 57 tests pass on this checkout. The disk-backed library
  tests exercise upload, ingest, restart, deduplication, and deletion. These tests
  use synthetic PDFs and fake inference; they are not model quality measurements.
- Keep PDFium for native Unicode text, text object geometry, rotation, and vector
  object inspection. Its existing BSD/Apache wrapper avoids adding an AGPL PDF
  dependency. Layout interpretation is conservative heuristics, not a table parser.
- Keep native text even when visual processing is selected. Store extraction,
  quality signals, routing reasons, chunks, and processing revisions in SQLite.
- OCR uses an optional local Tesseract executable, with a deadline and explicit
  unavailable/failure warnings. Missing OCR must retain a visual recovery path.
- Add a small lexical discovery bridge for text-only pages. Keep lexical and
  visual scores separate; dense text retrieval, evaluated fusion, MaxSim, and
  learned query routing remain Phase 4.
- Reprocess one page through a durable task. Hide only that page's evidence while
  it is pending or failed; leave other pages and immutable originals available.

## Exit checklist

- Phase 3: mixed page extraction/routing, bounded chunks, persisted reasons,
  selective OCR/vision, page override/recovery, measured baseline comparison.
- Phase 4: measured text/visual retrieval and grounding, safe index migration.
- Phase 5: persistent conversations and accessible evidence workspace.
- Phase 6: cited multi-document comparison and reproducible exports.
- Phase 7: held-out evaluation, security, backup/restore, accurate release claims.

## Phase 4 — 2026-11-04

- Keep the existing local SQLite/Qdrant worker boundary. Add UUID-isolated
  retrieval revisions with pinned encoder, scoring and rendering profiles.
  Activate only completed current-snapshot builds; retain the previous revision
  and filter deleted/superseded evidence immediately.
- Use BGE-small normalized CLS text vectors on CPU and ColPali-v1.3 original
  token matrices on CUDA. Pin the adapter and base snapshots independently.
  Reuse derived image-token artifacts to avoid a second image forward pass.
- Keep an exact NumPy MaxSim reference, Qdrant DOT/MaxSim original tokens and a
  centroid candidate/rerank path. Do not infer ANN scaling from embedded exact
  search measurements.
- Select Borda rank fusion using development data (20/20 versus RRF 16/20).
  The held-out synthetic test also scored 20/20; the faster scoped all-page
  pooled baseline matched it. No overall retrieval improvement is established.
- Train a cheap local router on disjoint development families and keep it off
  by default. Cached tier comparisons measure starting policy, not full answer
  escalation cost. Its 150 DPI profile is intentionally incompatible with the
  default 300 DPI index.
- Validate structured claim references and selected-document coverage before
  returning citations. Separate reference validity from semantic entailment.
  Same-model support estimates are explicitly not independent verification.
- Use a flat provider JSON schema for compatibility, followed by strict local
  validation. Preserve deadline/retry bounds and expose quota errors. Add local
  Find pages so source discovery needs no provider request.
- The configured provider hit its daily free-tier quota after six held-out LLM
  routes. Six sampled answer checks and three support estimates passed; the
  remaining routing comparison is pending reset. No billing/key/model changes
  were made to bypass the quota, and no dollar-cost conclusion is drawn.
- The final suite passes 107 tests. Browser verification used isolated fictional
  PDFs and fake inference; real CUDA/provider checks are separate saved reports.

## Phase 5 — 2026-11-04

- Keep the existing framework-free frontend and local SQLite boundary. Persist
  conversations, request scope, answers, viewer state and ordered turn events
  rather than treating browser session storage as authoritative chat history.
- Emit real provider chunk text as visibly provisional. Validate the final
  structured response before publishing authoritative citations. Never interpret
  question, filename, excerpt or answer HTML in the workspace.
- Use replayable SSE and cooperative cancellation with a bounded local queue.
  Stream disconnect cancels unfinished work; restart marks it interrupted.
  Provider deadlines and GPU boundaries limit how promptly cancellation stops
  underlying work; do not promise immediate compute or billing cancellation.
- Reuse the existing library access lock for consistency with deletion and
  immutable evidence. The verified profile remains one local process, not
  concurrent shared deployment.
- Preserve the last evidence version/page/zoom/scroll state per conversation.
  Use a split pane on desktop and a stacked layout with visible navigation on
  narrow screens. Keep source handlers free of inline filename JavaScript.
- Remove invented dashboard analytics. Count document pages and completed saved
  questions from live metadata; these are retained records, not lifetime usage.
- Browser verification uses generated PDFs and simulated streamed inference;
  real HTTP disconnect, cancellation/retry, viewer restore and narrow-screen
  checks passed. Live Gemini streaming and remaining Phase 4 provider comparisons
  are still externally unverified; no additional paid requests were made.

Stop after Phase 5 in this task. Preserve the original README and user research.
