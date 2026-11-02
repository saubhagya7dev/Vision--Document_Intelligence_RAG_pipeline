"""Bounded PDF rendering and content-addressed page artifacts."""

import hashlib
import math
import os
import threading
from pathlib import Path
from typing import Generator
from uuid import uuid4

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

from vision_rag.telemetry import stage

# PDFium is not thread safe, including across separate documents.
PDFIUM_LOCK = threading.RLock()


class DocumentLoader:
    def __init__(
        self,
        dpi: int = 300,
        fmt: str = "jpeg",
        cache_dir: str | Path | None = None,
        max_render_pixels: int = 40_000_000,
    ) -> None:
        if dpi <= 0 or max_render_pixels < 1:
            raise ValueError("DPI and render pixel limit must be positive")
        self.dpi = dpi
        self.max_render_pixels = max_render_pixels
        self.fmt = fmt
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._hashes: dict[tuple[str, int, int, int], str] = {}
        self._cache_lock = threading.RLock()

    def _path(self, file_path: str | Path) -> Path:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF not found at: {path}")
        return path

    def content_hash(self, file_path: str | Path) -> str:
        path = self._path(file_path)
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        with self._cache_lock:
            if key not in self._hashes:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if len(self._hashes) >= 256:
                    self._hashes.clear()
                self._hashes[key] = digest.hexdigest()
            return self._hashes[key]

    def page_count(self, file_path: str | Path) -> int:
        path = self._path(file_path)
        with stage("page_inspection"), PDFIUM_LOCK:
            with pdfium.PdfDocument(str(path)) as pdf:
                return len(pdf)

    def _artifact(
        self, path: str | Path, page_number: int, thumbnail: bool = False
    ) -> Path | None:
        if self.cache_dir is None:
            return None
        kind = "thumb" if thumbnail else "page"
        return (
            self.cache_dir
            / self.content_hash(path)
            / f"{self.dpi}-v1-{kind}-{page_number}.png"
        )

    def _save_artifact(self, image: Image.Image, artifact: Path) -> None:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        temporary = artifact.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with stage("page_cache_write"):
                image.save(temporary, format="PNG")
                os.replace(temporary, artifact)
        finally:
            temporary.unlink(missing_ok=True)

    def load_page(
        self, file_path: str | Path, page_number: int, thumbnail: bool = False
    ) -> Image.Image:
        """Return an owned RGB image. Page numbers are one-based."""
        path = self._path(file_path)
        if page_number < 1:
            raise IndexError("Page numbers start at 1")
        artifact = self._artifact(path, page_number, thumbnail)
        with self._cache_lock:
            if artifact is not None and artifact.exists():
                try:
                    with stage("page_cache_read"), Image.open(artifact) as cached:
                        return cached.convert("RGB")
                except (OSError, UnidentifiedImageError):
                    artifact.unlink(missing_ok=True)
            with stage("rendering", page=page_number), PDFIUM_LOCK:
                with pdfium.PdfDocument(str(path)) as pdf:
                    if page_number > len(pdf):
                        raise IndexError("Page is outside the document")
                    page = pdf[page_number - 1]
                    bitmap = None
                    try:
                        dpi = min(self.dpi, 96) if thumbnail else self.dpi
                        width, height = page.get_size()
                        pixels = math.ceil(width * dpi / 72) * math.ceil(
                            height * dpi / 72
                        )
                        if pixels > self.max_render_pixels:
                            raise ValueError(
                                "Page exceeds MAX_RENDER_PIXELS at the configured DPI"
                            )
                        bitmap = page.render(scale=dpi / 72)
                        image: Image.Image = bitmap.to_pil().convert("RGB")
                    finally:
                        if bitmap is not None:
                            bitmap.close()
                        page.close()
            if thumbnail:
                image.thumbnail((240, 320))
            if artifact is not None:
                try:
                    self._save_artifact(image, artifact)
                except BaseException:
                    image.close()
                    raise
            return image

    def iter_batches(
        self, file_path: str | Path, batch_size: int = 2
    ) -> Generator[tuple[int, list[Image.Image]], None, None]:
        if batch_size < 1:
            raise ValueError("Batch size must be positive")
        count = self.page_count(file_path)
        for start in range(1, count + 1, batch_size):
            images = []
            try:
                for number in range(start, min(start + batch_size, count + 1)):
                    images.append(self.load_page(file_path, number))
                    if self.cache_dir is not None:
                        # Reuse the owned page instead of rendering it again.
                        with self._cache_lock, images[-1].copy() as thumbnail:
                            thumbnail.thumbnail((240, 320))
                            artifact = self._artifact(file_path, number, True)
                            if artifact is not None and not artifact.exists():
                                self._save_artifact(thumbnail, artifact)
                yield start, images
            finally:
                for image in images:
                    image.close()

    def load_pdf(self, file_path: str | Path) -> list[Image.Image]:
        """Compatibility helper; application workflows use bounded batches."""
        images = []
        try:
            for number in range(1, self.page_count(file_path) + 1):
                images.append(self.load_page(file_path, number))
            return images
        except BaseException:
            for image in images:
                image.close()
            raise
