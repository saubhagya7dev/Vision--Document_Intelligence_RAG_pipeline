import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings."""

    # Vector DB
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_name: str = "vision_rag_docs"
    qdrant_mode: Literal["local", "memory", "server"] = "local"
    # Accepted so older .env files still load; qdrant_mode now selects storage.
    qdrant_in_memory: bool | None = None

    # Models
    embedding_model_name: str = "vidore/colpali-v1.3"
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
    workspace_id: str = Field(default="local", min_length=1, max_length=100)
    ingestion_worker_enabled: bool = True
    import_legacy_pdfs: bool = True
    hybrid_ingestion: bool = True
    text_chunk_limit: int = Field(default=1200, ge=32, le=8000)
    text_chunk_overlap: int = Field(default=120, ge=0, le=2000)
    ocr_enabled: bool = True
    tesseract_executable: str = "tesseract"
    ocr_language: str = "eng"
    ocr_timeout_seconds: float = Field(default=60, ge=1, le=600)
    phase4_enabled: bool = True
    text_model_name: str = "BAAI/bge-small-en-v1.5"
    text_model_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    visual_model_revision: str = "b5c6dd62125326e6f0b540c1f7b36e901cdc0a11"
    visual_base_revision: str = "30ab955d073de4a91dc5a288e8c97226647e3e5a"
    retrieval_candidates: int = Field(default=30, ge=5, le=100)
    evidence_char_budget: int = Field(default=14000, ge=1000, le=64000)
    provider_timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    provider_attempts: int = Field(default=2, ge=1, le=3)
    router_path: Path | None = None
    deployment_profile: Literal["local", "authenticated"] = "local"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    access_token: SecretStr | None = None
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "::1"]
    cors_origins: list[str] = []
    session_seconds: int = Field(default=28800, ge=60, le=86400)
    session_cookie_secure: bool = False
    trusted_tls_proxy: bool = False
    max_request_mb: int = Field(default=102, ge=1, le=1024)

    def check_deployment(self) -> None:
        local = self.bind_host in ("127.0.0.1", "localhost", "::1")
        if not self.allowed_hosts or any("*" in host for host in self.allowed_hosts):
            raise ValueError("Configure explicit ALLOWED_HOSTS without wildcards")
        if any(origin == "*" for origin in self.cors_origins):
            raise ValueError("Configure explicit CORS_ORIGINS without wildcards")
        if self.access_token and len(self.access_token.get_secret_value()) < 32:
            raise ValueError("ACCESS_TOKEN must contain at least 32 characters")
        if self.deployment_profile == "local" and not local:
            raise ValueError("The local profile must bind to a loopback address")
        if self.deployment_profile == "authenticated" and not self.access_token:
            raise ValueError("The authenticated profile requires ACCESS_TOKEN")
        if not local and not (self.session_cookie_secure and self.trusted_tls_proxy):
            raise ValueError(
                "Network binding requires secure cookies and an explicit TLS proxy"
            )

    @property
    def retrieval_specification(self) -> dict[str, Any]:
        return {
            "text_model": self.text_model_name,
            "text_revision": self.text_model_revision,
            "text_dimensions": 384,
            "text_pooling": "cls-normalized-v1",
            "visual_model": self.embedding_model_name,
            "visual_revision": self.visual_model_revision,
            "visual_base_revision": self.visual_base_revision,
            "visual_dimensions": 128,
            "scoring": "unmasked-dot-maxsim-v1",
            "dpi": self.render_dpi,
            "extractor": "native-layout-v1",
            "chunk_limit": self.text_chunk_limit,
            "chunk_overlap": self.text_chunk_overlap,
        }

    @model_validator(mode="after")
    def check_chunk_budget(self) -> "Settings":
        if self.text_chunk_overlap >= self.text_chunk_limit:
            raise ValueError("TEXT_CHUNK_OVERLAP must be smaller than TEXT_CHUNK_LIMIT")
        return self

    @property
    def index_profile(self) -> str:
        specification = {
            "model": self.embedding_model_name,
            "pooling": "mean-v1",
            "dimensions": 128,
            "dpi": self.render_dpi,
        }
        return hashlib.sha256(
            json.dumps(specification, sort_keys=True).encode()
        ).hexdigest()

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Global settings instance
settings = Settings()
