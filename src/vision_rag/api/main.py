from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from vision_rag.api.routes import router

app = FastAPI(
    title="Vision-Native RAG API",
    description="OCR-free document intelligence pipeline using Vision-Language Models.",
    version="0.1.0"
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

@app.get("/health")
def health_check():
    return {"status": "ok"}

# Resolve static directory path relative to this file's location
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Mount static files (CSS, JS, images)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Catch-all route: serve index.html for any non-API, non-static path (SPA routing)
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve the SPA index.html for all frontend routes."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"detail": "Frontend not found. Place index.html in src/vision_rag/static/"}

def start():
    """Entry point for the application."""
    uvicorn.run("vision_rag.api.main:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    start()
