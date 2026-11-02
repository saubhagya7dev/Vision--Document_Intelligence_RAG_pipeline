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

Stop after Phase 3 in this task. Preserve the original README and user research.
