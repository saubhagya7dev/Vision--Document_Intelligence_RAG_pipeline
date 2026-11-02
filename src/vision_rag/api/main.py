import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from vision_rag.api.routes import get_components, router, shutdown_components
from vision_rag.config import settings
from vision_rag.telemetry import stage, trace


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        if settings.model_warmup:
            await run_in_threadpool(get_components)
        yield
    finally:
        await run_in_threadpool(shutdown_components)


app = FastAPI(
    title="Vision-Native RAG API",
    description="OCR-free document intelligence pipeline using Vision-Language Models.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for development convenience
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.middleware("http")
async def request_trace(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    with trace() as identifier, stage("http_request", method=request.method):
        response = await call_next(request)
        response.headers["X-Trace-ID"] = identifier
        return response


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


# Resolve static directory path relative to this file's location
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Mount static files (CSS, JS, images)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Catch-all route: serve index.html for any non-API, non-static path (SPA routing)
@app.get("/{full_path:path}", response_model=None)
async def serve_spa(full_path: str) -> FileResponse | dict[str, str]:
    """Serve the SPA index.html for all frontend routes."""
    if full_path.startswith(("api/", "static/")):
        raise HTTPException(404, "Not found")
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"detail": "Frontend not found. Place index.html in src/vision_rag/static/"}


def start() -> None:
    """Entry point for the application."""
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("vision_rag.api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    start()
