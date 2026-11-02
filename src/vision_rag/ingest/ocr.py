"""Optional bounded local Tesseract OCR. Never sends document data to a provider."""

import csv
import io
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from vision_rag.ingest.text import Block


class TesseractOCR:
    def __init__(
        self, executable: str = "tesseract", language: str = "eng", timeout: float = 60
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_+.-]+", language):
            raise ValueError("Invalid OCR language")
        self.executable, self.language, self.timeout = executable, language, timeout

    def extract(self, image: Image.Image, width: float, height: float) -> list[Block]:
        executable = shutil.which(self.executable)
        if executable is None:
            raise RuntimeError("OCR unavailable: configure TESSERACT_EXECUTABLE")
        with TemporaryDirectory(prefix="vision-ocr-") as folder:
            path = Path(folder) / "page.png"
            image.save(path)
            output = subprocess.run(
                [executable, str(path), "stdout", "-l", self.language, "tsv"],
                capture_output=True,
                timeout=self.timeout,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if len(output.stdout) > 8_000_000:
            raise ValueError("OCR output exceeds limit")
        lines: dict[tuple[str, ...], list[dict[str, str]]] = {}
        for row in csv.DictReader(
            io.StringIO(output.stdout.decode("utf-8")), delimiter="\t"
        ):
            if row.get("level") == "5" and row.get("text", "").strip():
                key = tuple(row[k] for k in ("block_num", "par_num", "line_num"))
                lines.setdefault(key, []).append(row)
        blocks = []
        sx, sy = width / image.width, height / image.height
        for words in lines.values():
            left = min(int(w["left"]) for w in words) * sx
            right = max(int(w["left"]) + int(w["width"]) for w in words) * sx
            top = height - min(int(w["top"]) for w in words) * sy
            bottom = height - max(int(w["top"]) + int(w["height"]) for w in words) * sy
            blocks.append(
                Block(" ".join(w["text"] for w in words), (left, bottom, right, top))
            )
        return blocks
