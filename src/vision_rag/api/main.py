import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from vision_rag.api.findings import router as findings_router
from vision_rag.api.routes import (
    get_library,
    router,
    shutdown_components,
    warmup_components,
)
from vision_rag.api.security import RequestBoundary
from vision_rag.api.security import router as security_router
from vision_rag.api.workspace import router as workspace_router
from vision_rag.config import settings
from vision_rag.telemetry import protect_logs, stage, trace


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        settings.check_deployment()
        protect_logs()
        await run_in_threadpool(get_library)
        if settings.model_warmup:
            await run_in_threadpool(warmup_components)
        yield
    finally:
        await run_in_threadpool(shutdown_components)


app = FastAPI(
    title="Vision-Native RAG API",
    description="OCR-free document intelligence pipeline using Vision-Language Models.",
    version="0.1.0",
    lifespan=lifespan,
)

# Same-origin browser use is the default. Explicit cross-origin bearer clients
# never get ambient cookie credentials through CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(findings_router, prefix="/api/v1")
app.include_router(security_router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def invalid_request(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid request",
            "errors": [
                {"field": list(e["loc"]), "message": e["msg"], "type": e["type"]}
                for e in error.errors()
            ],
        },
    )


@app.middleware("http")
async def request_trace(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    with trace() as identifier, stage("http_request", method=request.method):
        if request.method == "POST" and (
            request.url.path == "/api/v1/ingest"
            or request.url.path.endswith("/versions")
        ):
            request.state.library_generation = get_library().generation
        response = await call_next(request)
        response.headers["X-Trace-ID"] = identifier
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
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
async def serve_spa(full_path: str) -> HTMLResponse | dict[str, str]:
    """Keep the public project page separate from the owner's workspace."""
    if full_path.startswith(("api/", "static/")):
        raise HTTPException(404, "Not found")
    landing = full_path == ""
    index_file = STATIC_DIR / ("landing.html" if landing else "index.html")
    if index_file.exists():
        html = index_file.read_text(encoding="utf-8")
        for asset in (
            "styles.css",
            "workspace.css",
            "emerald.css",
            "app.js",
            "workspace.js",
            "evidence.js",
            "documents.js",
            "findings.js",
            "session.js",
            "landing.css",
            "landing.js",
            "wireframe.css",
            "wireframe.js",
            "charcoal.css",
            "dashboard.js",
            "chat-studio.css",
            "hero-simulation.css",
            "hero-simulation.js",
        ):
            digest = hashlib.sha256((STATIC_DIR / asset).read_bytes()).hexdigest()[:12]
            html = html.replace(f'/static/{asset}"', f'/static/{asset}?v={digest}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
    return {"detail": "Frontend not found. Place index.html in src/vision_rag/static/"}


def start() -> None:
    """Entry point for the application."""
    logging.basicConfig(level=logging.INFO)
    settings.check_deployment()
    uvicorn.run(
        "vision_rag.api.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        reload=False,
        proxy_headers=settings.trusted_tls_proxy,
        forwarded_allow_ips=",".join(settings.trusted_proxy_ips),
        access_log=False,
    )


# Added last so credentials/origin/body checks run before request tracing can
# initialize the library, and before uploads reach the multipart parser.
app.add_middleware(RequestBoundary)


if __name__ == "__main__":
    start()
