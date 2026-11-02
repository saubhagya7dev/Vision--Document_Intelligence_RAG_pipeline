from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings."""

    # Vector DB
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_name: str = "vision_rag_docs"
    qdrant_in_memory: bool = (
        True  # Set to False when using a real Qdrant server (e.g. Docker)
    )

    # Models
    embedding_model_name: str = "vidore/colpali"
    generation_model_name: str = "gemini-3.6-flash"

    # API Keys
    google_api_key: Optional[str] = None
    data_dir: Path = Path("data")
    render_dpi: int = Field(default=300, ge=72, le=600)
    ingestion_batch_size: int = Field(default=2, ge=1, le=32)
    embedding_device: Literal["auto", "cuda", "mps", "cpu"] = "auto"
    embedding_precision: Literal["auto", "float16", "float32", "bfloat16"] = "auto"
    model_warmup: bool = False
    max_upload_mb: int = Field(default=100, ge=1)
    max_document_pages: int = Field(default=1000, ge=1)
    max_render_pixels: int = Field(default=40_000_000, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Global settings instance
settings = Settings()
