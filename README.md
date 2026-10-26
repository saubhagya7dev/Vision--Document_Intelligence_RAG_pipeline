<div align="center">

#  Vision - A Native Document Intelligence

### OCR-Free RAG Pipeline using Vision-Language Models

[![ColPali](https://img.shields.io/badge/ColPali-v1.3-orange.svg)](https://huggingface.co/vidore/colpali-v1.3)
[![Qdrant](https://img.shields.io/badge/Qdrant-Vector%20DB-DC244C.svg)](https://qdrant.tech/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Gemini](https://img.shields.io/badge/Gemini-3.6--flash-4285F4.svg)](https://ai.google.dev/)
[![Python 3.10 - 3.14](https://img.shields.io/badge/python-3.10--3.14-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/uv-Package%20Manager-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Tests](https://img.shields.io/badge/Tests-10%20passed-brightgreen?logo=pytest&logoColor=white)](#-running-tests)


*A next-generation document retrieval system that bypasses OCR entirely — treating every page as an image and using Vision-Language Models to understand layout, tables, charts, and diagrams perfectly.*

</div>

<div align="center">
  <img src="Screenshots/Screenshot 2026-10-20 061731.png" alt="Dashboard" width="49%" />
  <img src="Screenshots/Screenshot 2026-10-20 062234.png" alt="Query and Results" width="49%" />
</div>

## The Problem

Traditional RAG (Retrieval-Augmented Generation) pipelines convert PDFs to text using OCR before feeding them into a language model. This approach **completely breaks down** when dealing with:

- 📊 **Complex tables** with merged cells and nested headers
- 📈 **Charts and graphs** where meaning is purely visual
- 🏗️ **Architecture diagrams** and flowcharts
- 📝 **Multi-column layouts** with mixed text and images
- 🎨 **Infographics** where spatial arrangement carries meaning

**Vision-Native RAG** solves this by skipping text extraction entirely. Every document page is treated as an image and understood visually.

---

## Architecture

```mermaid
flowchart LR
    UI["Web UI / REST Client"]

    subgraph INGEST["1. Document Ingestion"]
        direction LR
        PDF["PDF Documents"] --> LOADER["PDF Loader"]
        LOADER --> IMG["Page Images"]
        IMG --> COLPALI["ColPali Vision Embedder"]
        COLPALI --> DB[("Qdrant Vector DB")]
        LOADER -.-> CACHE[("Local Image Cache")]
    end

    subgraph RETRIEVAL["2. Retrieval & Generation"]
        direction LR
        QUERY["User Question"] --> QEMB["ColPali Query Embedder"]
        QEMB --> SEARCH["MaxSim Search"]
        SEARCH --> TOPK["Top-k Pages"]
        TOPK --> RAG["RAG Synthesizer"]
        RAG --> GEMINI["Gemini Vision Model"]
        GEMINI --> ANSWER["Grounded Answer + Citations"]
    end

    UI --> PDF
    UI --> QUERY
    DB <--> SEARCH
    CACHE -.-> RAG
    ANSWER --> UI
```
### How It Works

1. **Ingest** → Upload a PDF. Each page is converted to a high-res image using `pypdfium2` (zero external dependencies). ColPali generates a 128-dimensional embedding vector for each page. These vectors are stored in Qdrant.

2. **Query** → Your question is embedded by ColPali into the same vector space. Qdrant finds the most visually relevant pages. Those page images (not text!) are sent directly to Gemini, which reads and reasons over them to produce an answer.

**The key insight:** The VLM sees the *exact same thing* a human sees — tables, charts, formatting, and all. No information is lost to OCR.

---

##  Project Structure

```
Vision-Native-RAG-Pipeline/
│
├── src/vision_rag/              # Main application package
│   ├── api/                     # FastAPI endpoints
│   │   ├── main.py              # App entrypoint & uvicorn config
│   │   └── routes.py            # /ingest, /query and UI routes
│   │
│   ├── static/                  # Interactive UI
│   │   ├── index.html           # SPA Shell
│   │   ├── styles.css           # Wallety-inspired styling
│   │   └── app.js               # Application logic
│   │
│   ├── core/                    # Abstract base classes (interfaces)
│   │   ├── embeddings.py        # BaseEmbeddingModel
│   │   ├── generator.py         # BaseVLMGenerator
│   │   └── vector_store.py      # BaseVectorStore
│   │
│   ├── models/                  # Model implementations
│   │   ├── colpali_embedder.py  # ColPali embedding model
│   │   └── gemini_generator.py  # Gemini VLM generator
│   │
│   ├── ingest/                  # Document ingestion pipeline
│   │   ├── document_loader.py   # PDF → PIL Images
│   │   └── pipeline.py          # Orchestrates ingest flow
│   │
│   ├── retrieval/               # Search & retrieval
│   │   └── retriever.py         # Query → Top-K pages
│   │
│   ├── generate/                # Answer generation
│   │   └── synthesizer.py       # End-to-end RAG orchestrator
│   │
│   ├── vector_stores/           # Vector DB implementations
│   │   └── qdrant_store.py      # Qdrant client wrapper
│   │
│   └── config.py                # Pydantic settings from .env
│
├── tests/                       # Test suite
│   ├── test_ingest.py
│   ├── test_retrieval.py
│   └── test_api.py
│
├── data/                        # Persisted uploaded PDFs
├── docker-compose.yml           # Qdrant (production mode)
├── Makefile                     # Dev shortcuts
├── pyproject.toml               # Dependencies & build config
└── .env                         # Environment variables
```

---

##  🚀 Quick Start

### Prerequisites

- **Python 3.10 – 3.14** (PyTorch does not support Python 3.15 yet)
- **Google API Key** for Gemini ([Get one here](https://aistudio.google.com/apikey))

### 1. Clone & Install

```bash
git clone https://github.com/saubhagya7dev/Vision---Document-Intelligence-RAG-pipeline.git
cd Vision---Document-Intelligence-RAG-pipeline

# Create virtual environment and install dependencies
uv venv
uv pip install -e .[dev]
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# Vector Database
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Models
EMBEDDING_MODEL_NAME=vidore/colpali-v1.3
GENERATION_MODEL_NAME=gemini-3.6-flash

# API Keys
GOOGLE_API_KEY=your_google_api_key_here
```

### 3. Run the Server

```bash
uv run python -m vision_rag.api.main
```

The API will be live at `http://localhost:8000`. Open `http://localhost:8000/docs` for the interactive Swagger UI.

### 4. Try It Out

**The Interactive UI:**
Open [http://localhost:8000](http://localhost:8000) in your browser to access the beautiful Wallety-inspired interactive dashboard. You can upload documents, view statistics, and chat with your PDFs visually.

**Using the API:**

**Upload a PDF:**
```bash
curl -X POST "http://localhost:8000/api/v1/ingest" \
  -F "file=@your_document.pdf"
```

**Ask a Question:**
```bash
curl -X POST "http://localhost:8000/api/v1/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the total revenue in Q3?", "top_k": 3}'
```

---

##  Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | `6333` | Qdrant server port |
| `QDRANT_IN_MEMORY` | `True` | Use in-process Qdrant (no Docker needed) |
| `EMBEDDING_MODEL_NAME` | `vidore/colpali-v1.3` | HuggingFace model for visual embeddings |
| `GENERATION_MODEL_NAME` | `gemini-3.6-flash` | Gemini model for answer generation |
| `GOOGLE_API_KEY` | — | Your Google AI API key |

### Storage Modes

| Mode | Config | Requires Docker | Data Persists |
|------|--------|----------------|---------------|
| **In-Memory** (default) | `QDRANT_IN_MEMORY=True` | ❌ No | ❌ Lost on restart |
| **Docker** (production) | `QDRANT_IN_MEMORY=False` | ✅ Yes | ✅ Persistent |

To switch to persistent storage:
```bash
docker compose up -d          # Start Qdrant
# Set QDRANT_IN_MEMORY=False in .env
uv run python -m vision_rag.api.main
```

---

##  Testing

```bash
# Run all tests
make test

# Or directly
pytest tests/
```

---

##  Development

```bash
# Format code
make format

# Lint
make lint

# Setup dev environment (includes pre-commit hooks)
make setup
```

---

##  Extensibility

The project uses **Abstract Base Classes** in the `core/` directory, making it easy to swap components:

| Interface | Current Implementation | Swap With |
|-----------|----------------------|-----------|
| `BaseEmbeddingModel` | ColPali (visual) | CLIP, SigLIP, any VLM encoder |
| `BaseVLMGenerator` | Gemini 3.6 Flash | GPT-4o, Claude, LLaVA |
| `BaseVectorStore` | Qdrant | Pinecone, Weaviate, ChromaDB |

To add a new implementation, simply create a class that inherits from the base and inject it in `routes.py`.

---

##  API Reference

### `GET /health`
Health check endpoint.

**Response:** `{"status": "ok"}`

---

### `GET /api/v1/documents`
List all uploaded PDF documents.

---

### `GET /api/v1/stats`
Get dashboard statistics.

---

### `DELETE /api/v1/documents/{filename}`
Delete a document and its associated vectors.

---

### `POST /api/v1/ingest`
Upload and process a PDF document.

**Request:** `multipart/form-data` with a `file` field (PDF only)

**Response:**
```json
{
  "status": "success",
  "message": "Successfully ingested report.pdf"
}
```

---

### `POST /api/v1/query`
Query the ingested documents.

**Request Body:**
```json
{
  "query": "What are the key findings?",
  "top_k": 3
}
```

**Response:**
```json
{
  "answer": "Based on the document pages, the key findings are...",
  "sources": [
    {"id": "uuid", "score": 0.92, "payload": {"source": "report.pdf", "page_number": 5}}
  ]
}
```

---

##  Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API Framework** | FastAPI | High-performance async REST API |
| **Embedding Model** | ColPali v1.3 | Vision-native document embeddings |
| **Vector Database** | Qdrant | Similarity search and storage |
| **Generation Model** | Gemini 3.6 Flash | Multimodal reasoning over images |
| **PDF Processing** | pypdfium2 | Fast, zero-dependency PDF page → image conversion |
| **Config Management** | Pydantic Settings | Type-safe environment configuration |

---

##  Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
---
<BR>

<div align="center">

**Built using Vision-Language Models**

*If legacy OCR-based RAG is a bicycle, Vision-Native RAG is a Tesla.*

</div>
