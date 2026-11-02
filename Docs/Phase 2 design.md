# Phase 2 implementation decisions

Scope: durable local documents, immutable versions, indexing jobs, and recovery.
The original README is preserved. No hybrid retrieval or Phase 3 work is included.

- SQLite owns document/version/page/build/job state. Use WAL, foreign keys, and
  short explicit transactions; never hold a transaction during model inference.
- Original bytes are validated and published under generated keys before metadata
  is committed. Startup reconciliation handles unpublished/orphaned artifacts.
- Default vectors use persistent local Qdrant, in a separate pooled-v1 collection.
  One application process and one worker own the local profile.
- A durable SQLite queue drives bounded ingestion. Cancellation and shutdown are
  cooperative at batch boundaries. Unfinished jobs are requeued on startup.
- A build is invisible until every expected page is indexed and SQLite publishes
  it atomically with the completed job. Failed replacement leaves the old version
  active. Ready build IDs and workspace filters are enforced before vector search.
- Retry clears the incomplete build and reuses deterministic build/page point IDs.
  Qdrant and SQLite do not share a transaction: publication gates visibility;
  retries and reconciliation compensate for partial writes.
- Deletion first tombstones metadata, immediately hiding the document, then runs
  retryable vector/file cleanup. Versions retain their original source identity.
- Existing root-level PDFs are imported once into metadata/generated storage;
  migration records prevent deleted legacy files from being reimported. Existing
  files and unknown legacy upload remnants are preserved.
- The existing UI will poll durable jobs and offer progress, retry and cancellation.
  Upload completion is no longer represented as successful indexing.

Validation gates: duplicate/concurrent upload identity; explicit replacement;
bounded batches and stable point IDs; retrieval hiding partial/deleted builds;
restart, retry, cancel and cleanup recovery; real persistent Qdrant tests; API and
UI integration checks. Routine tests use synthetic PDFs and fake model outputs.
Real model checks are reported separately and do not imply retrieval quality.
