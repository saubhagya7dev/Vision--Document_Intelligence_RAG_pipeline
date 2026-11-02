# Project understanding

Repository inspection: 2026-11-02. This describes the implementation in this checkout, rather than treating README claims or upgrade proposals as implemented features.

## Purpose and current architecture

Vision RAG is a Python application for asking questions about PDF documents using page images instead of extracting document text. FastAPI serves both a REST API and a plain HTML/CSS/JavaScript frontend. ColPali runs locally to embed documents and queries. Qdrant retrieves pages. Google's Gemini API receives the question and selected page images and generates the answer.

The application is a compact prototype with replaceable embedding, generation, and vector-store interfaces. It has no relational metadata database, user accounts, background job worker, or backend chat/session store.

### Ingestion

1. `POST /api/v1/ingest` accepts a multipart `file` whose filename ends with lowercase `.pdf`.
2. `get_components()` lazily constructs the PDF loader, ColPali model, Qdrant store, Gemini generator, ingestion pipeline, retriever, and synthesizer.
3. The upload is written to `data/<filename>` relative to the process working directory.
4. `DocumentLoader.load_pdf()` renders every PDF page at 300 DPI through pypdfium2/PDFium and returns RGB PIL images.
5. ColPali processes all page images together. Its patch embeddings are averaged along dimension 1 into one 128-dimensional vector per page.
6. Each page receives a new random UUID. Its payload contains `original_filename`, `source`, and a one-based `page_number`.
7. All page vectors are upserted into Qdrant in one call.

There is no page-image cache persisted during ingestion. The saved PDF is needed again at query time. There is no content hashing, deduplication, replacement transaction, or cleanup of an upload when embedding fails.

### Query and generation

1. `POST /api/v1/query` receives `query` and optional `top_k` (default 3).
2. `Retriever` embeds the query using the same local ColPali model, averaging its token embeddings into a single vector.
3. Qdrant performs cosine search over the page vectors, with no document filter, reranking, or relevance threshold.
4. `RAGSynthesizer` reads the source path and page number from each hit. It renders each distinct source PDF once within that query, including all its pages, then selects the requested pages.
5. Gemini receives a grounding instruction, the question, and the selected PIL images. It receives no explicit filename/page labels or conversation history.
6. The API returns the generated text and separate source records shaped as `{score, source, page}`.

No hits produce `No relevant documents found.` without calling Gemini. Hits with no usable page images produce a separate fallback. A missing or unreadable source PDF can raise an exception and fail the request.

### Retrieval semantics

The current implementation does **not** perform ColPali late-interaction MaxSim retrieval. Both image patches and query tokens are mean-pooled. The Qdrant collection has ordinary `VectorParams(size=128, distance=COSINE)` and no multivector configuration.

This distinction affects retrieval quality, storage design, and future heatmaps. Switching to true multivectors requires coordinated embedder/store changes and reindexing; an existing collection is currently checked only for its name, not schema compatibility.

## Source map

| File under `src/vision_rag/` | Responsibility |
| --- | --- |
| `config.py` | Pydantic settings loaded from `.env` and environment |
| `api/main.py` | FastAPI app, CORS, health endpoint, static mount, SPA fallback, Uvicorn entrypoint |
| `api/routes.py` | API schemas, lazy component wiring, uploads, document listing/deletion, previews, statistics |
| `core/embeddings.py` | Abstract image/query embedding interface |
| `core/vector_store.py` | Abstract upsert/search/statistics/delete interface |
| `core/generator.py` | Abstract question-plus-images generation interface |
| `ingest/document_loader.py` | PDF rendering; `fmt` is accepted but unused |
| `ingest/pipeline.py` | Render, embed, assign page metadata, upsert |
| `models/colpali_embedder.py` | Model/processor loading, device selection, inference, mean pooling |
| `models/gemini_generator.py` | API-key resolution, prompt construction, synchronous Gemini request |
| `vector_stores/qdrant_store.py` | Local/server Qdrant access and collection management |
| `retrieval/retriever.py` | Query embedding followed by vector search |
| `generate/synthesizer.py` | Retrieve pages, reload PDFs, generate answer |
| `static/index.html` | Four frontend views and preview/delete modals |
| `static/app.js` | Hash routing, requests, browser state, rendering, uploads, previews, deletion |
| `static/styles.css` | Dark/emerald design system and responsive layouts |

## HTTP surface

| Method | Path | Actual behavior |
| --- | --- | --- |
| GET | `/health` | Always returns `{"status":"ok"}`; no model, database, or provider readiness check |
| POST | `/api/v1/ingest` | Saves and synchronously indexes a PDF |
| POST | `/api/v1/query` | Returns an answer and source list |
| GET | `/api/v1/documents` | Lists PDFs on disk; renders each entire PDF to count its pages |
| GET | `/api/v1/documents/{filename}/pages/{page_num}` | Renders the entire PDF, selects a page, returns JPEG at quality 85 |
| GET | `/api/v1/stats` | Counts PDFs on disk and consults the process-local vector-store object if initialized |
| DELETE | `/api/v1/documents/{filename}` | Deletes matching vectors only if the vector store is initialized, then unlinks the PDF |
| GET | `/static/*` | Serves static assets |
| GET | `/{full_path:path}` | Returns the SPA, including for otherwise-unmatched API GET paths |

FastAPI also exposes its generated schema/documentation routes. Initialization occurs before the ingest/query route's exception handler, so initialization failures do not use the custom exception handling inside those handlers.

## Frontend behavior

- Hash routes: dashboard, upload, chat, documents. No frontend build system or framework.
- Dashboard document/page counts come from the API. Query count and activity are browser-session values. The weekly analytics bars are hardcoded illustration values.
- Upload uses XMLHttpRequest progress events. Progress measures upload bytes; indexing continues after the upload reaches 100%. Only the first dropped file is handled.
- Chat sends only the current question and top-k. Previous turns are shown locally but never sent to the backend. Top-k slider range is 1–10.
- Source cards show page thumbnails, filenames, and raw similarity scores. Clicking opens a full-page image modal. There are no bounding boxes, patch heatmaps, or answer-span citation links.
- Chat, last sources, upload history, activity, and query count use `sessionStorage`. There is no server persistence of these records.
- Basic Markdown rendering escapes input before applying regex substitutions. It is not a full Markdown renderer.
- The UI checks `/health` every 30 seconds. Online status therefore indicates HTTP responsiveness only.
- Fonts come from Google Fonts. At widths under 768px the navigation pill is hidden, with no replacement navigation control in the current markup.
- The send button is disabled during queries, but the Enter handler calls `sendQuery()` without checking for an in-flight query, so overlapping requests remain possible.

## Settings and runtime

| Setting | Source default | Local checkout observation |
| --- | --- | --- |
| `qdrant_host` | `localhost` | localhost |
| `qdrant_port` | 6333 | 6333 |
| `qdrant_collection_name` | `vision_rag_docs` | No local override observed |
| `qdrant_in_memory` | true | No local override observed |
| `embedding_model_name` | `vidore/colpali` | `.env` selects `vidore/colpali-v1.3` |
| `generation_model_name` | `gemini-3.6-flash` | Same configured string; provider availability not validated |
| `google_api_key` | None | A nonempty key is configured; provider validity was not checked and the value was not printed |

The embedder constructor itself defaults to `vidore/colpali-v1.3`, differing from Settings. Device selection is CUDA, then MPS, then CPU. The code selects float16 off CPU and float32 on CPU. Model loading uses `from_pretrained()` and can require model downloads/access. Actual inference and device availability were not validated in this inspection.

The local virtual environment reports Python 3.14.9, torch 2.13.0, transformers 5.16.1, colpali-engine 0.3.18, qdrant-client 1.19.0, google-genai 2.22.0, FastAPI 0.141.1, and pypdfium2 5.14.0. Package metadata declares Python >=3.10 and <3.15; `.python-version` selects 3.14. `uv.lock` pins the resolved dependencies, while pyproject uses broad lower bounds.

Run from the repository root with `.venv/Scripts/python.exe -m vision_rag.api.main` or the documented uv equivalent. Uvicorn binds to `0.0.0.0:8000`, without reload. Docker Compose starts only Qdrant, exposes ports 6333/6334, uses the `latest` image tag, and persists its data in a named volume. Set `QDRANT_IN_MEMORY=False` to use that server.

## Storage and consistency

- In-memory Qdrant loses vectors on restart; saved PDFs remain. The application does not automatically rebuild the index.
- With a Qdrant server, vectors persist independently of the PDFs. Restoring/moving one without the other can break retrieval.
- Sources use paths relative to the launch directory. A different working directory changes both configuration discovery and document lookup.
- Re-uploading a filename overwrites the PDF but creates additional vectors with random UUIDs. Old vectors may then point to changed page content or nonexistent page numbers.
- Failed ingest can leave a visible PDF that is not indexed. Document listing is a filesystem inventory, not proof of successful indexing.
- Deletion before component initialization skips vector deletion, even if a persistent server contains vectors for that file.
- Multiple server workers would have separate models, singleton state, and in-memory databases. The lazy initialization is not an explicit lifecycle or concurrency management mechanism.
- `data/` is not ignored by Git, although `.env` and `.venv` are. The local data directory had no PDF files during inspection.

## Confirmed defect and other risks

### Confirmed installed-client statistics defect

`QdrantVectorStore.get_collection_info()` reads `info.vectors_count`. Installed qdrant-client 1.19.0's `CollectionInfo` does not expose that attribute. A disposable in-memory probe inserted one point and successfully searched it; raw collection information showed one point, while the wrapper returned zero counts and `unknown`. The broad exception handler hides the failure. Mypy independently flags the absent attribute.

### Source-observed risks

- Upload filenames are joined directly to `data` without resolving and enforcing directory containment. Crafted upload names can escape the intended directory. Existing same-name files are overwritten.
- Document deletion/preview paths likewise lack explicit containment validation. Actual exploitability depends on routing/path encoding, and was not tested against deployed HTTP infrastructure.
- There is no authentication, authorization, document ownership, upload/page limit, or query limit. CORS allows all origins with credentials enabled.
- Synchronous PDF rendering, Torch inference, database calls, and provider generation run directly within async route handlers and can block the event loop.
- All pages are rendered and embedded together, without bounded batches. Large PDFs can exhaust host or accelerator memory.
- Full-PDF rendering is repeated for listing, query context, each thumbnail, and preview requests. The synthesizer cache exists only within one query.
- `QueryRequest` does not restrict blank questions or nonpositive/excessive top-k values. Upload validation checks filename extension only and disagrees with the frontend on uppercase `.PDF`.
- Gemini receives images without explicit source identities. Returned sources are retrieval metadata rather than verified claim-to-page citations. `str(response.text)` can yield `"None"` if no text is present.
- Raw exception strings go to clients and tracebacks to stderr. There is no structured logging, retry policy, provider timeout configuration, rate-limit handling, or answer-quality evaluation in application code.
- The document delete button embeds filenames in inline JavaScript using HTML escaping. HTML entity decoding does not make a filename safe inside a JavaScript string; apostrophes can break the handler, and crafted names warrant security review.
- Vector upsert uses `zip()` without checking equal list lengths, so mismatched inputs can silently truncate.

## Tests, tools, and documentation

There are six test functions: two PDF-loader tests, two retriever tests, and two API tests. The loader tests render a real temporary two-page PDF. Retrieval is mocked; the query API mocks component initialization and synthesis. There are no tests for actual model inference, Gemini, full ingestion/synthesis, document management, statistics, duplicates, malformed uploads, or retrieval quality. README's badge claiming ten passing tests does not match the test count.

Inspection checks:

- Disposable Qdrant probe: insert, cosine search, and payload-filter deletion succeeded; statistics defect reproduced.
- Ruff: 51 findings across source and tests, including import ordering, unused imports, and long lines.
- Mypy: 14 errors across three files, including the Qdrant attribute and missing function annotations.
- The four PDF-loader/retriever tests passed in 0.32 seconds. Full-suite attempts did not produce a usable pytest report; a bounded diagnostic run returned exit code 1 with no captured output. The two API tests therefore remain unverified in this environment. A separate Torch import succeeded; the full-suite failure was not localized.

`Makefile` provides setup/test/lint/format and Docker shortcuts. Pre-commit pins Ruff 0.1.13 and mypy 1.8.0, older than the installed tools. No CI workflow was found in the tracked files. There is no application Dockerfile or deployment configuration beyond the Qdrant service.

README also describes MaxSim, an ingestion-time image cache, and nested source payloads that do not match the implementation. Its statements about perfect visual understanding are product claims, not demonstrated evaluation results.

`Docs/Upgrade research.md` is a proposed roadmap: true MaxSim, document filters, conversational memory, streaming, more formats, cross-document routing, and visual explanations. These are not implemented. Its comparative claims and effort estimates were not independently researched in this inspection.

## Practical development priorities

1. Correct the Qdrant statistics adapter and add behavior coverage for the demonstrated failure.
2. Make uploads/path handling safe and establish stable document IDs, replacement semantics, and index/file consistency.
3. Separate vector-store initialization from model/provider initialization, and add readiness checks and explicit lifecycle management.
4. Render only required pages, obtain page counts without rasterization, and bound embedding batches and upload work.
5. Align retrieval with intended ColPali semantics through multivectors/MaxSim and a planned reindex, then measure retrieval quality.
6. Add document-scoped search, explicit source labels and citation validation; introduce backend conversation state if follow-up questions are required.
7. Expand meaningful integration coverage and align the README with verified behavior.

No application source was changed as part of this inspection.
