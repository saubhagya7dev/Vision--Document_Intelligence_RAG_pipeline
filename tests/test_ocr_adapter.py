import subprocess
from unittest.mock import MagicMock

import pytest
from PIL import Image

from vision_rag.ingest.ocr import TesseractOCR


def test_local_ocr_tsv_geometry_and_deadline(monkeypatch):
    monkeypatch.setattr(
        "vision_rag.ingest.ocr.shutil.which", lambda _: "local-tesseract"
    )
    result = MagicMock(
        stdout=(
            b"level\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\ttext\n"
            b"5\t1\t1\t1\t10\t20\t30\t10\tRevenue\n"
            b"5\t1\t1\t1\t45\t20\t20\t10\t120\n"
        )
    )
    run = MagicMock(return_value=result)
    monkeypatch.setattr("vision_rag.ingest.ocr.subprocess.run", run)
    with Image.new("RGB", (100, 200)) as image:
        blocks = TesseractOCR(timeout=12).extract(image, 200, 400)
    assert blocks[0].text == "Revenue 120"
    assert blocks[0].bbox == (20, 340, 130, 360)
    assert run.call_args.kwargs["timeout"] == 12
    assert run.call_args.args[0][-1] == "tsv"


def test_missing_ocr_and_invalid_language_are_explicit(monkeypatch):
    monkeypatch.setattr("vision_rag.ingest.ocr.shutil.which", lambda _: None)
    with Image.new("RGB", (100, 100)) as image:
        with pytest.raises(RuntimeError, match="OCR unavailable"):
            TesseractOCR().extract(image, 100, 100)
    with pytest.raises(ValueError):
        TesseractOCR(language="eng --shell-command")


def test_ocr_timeout_propagates_for_visual_fallback(monkeypatch):
    monkeypatch.setattr(
        "vision_rag.ingest.ocr.shutil.which", lambda _: "local-tesseract"
    )
    monkeypatch.setattr(
        "vision_rag.ingest.ocr.subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired("local-tesseract", 1)),
    )
    with Image.new("RGB", (100, 100)) as image:
        with pytest.raises(subprocess.TimeoutExpired):
            TesseractOCR(timeout=1).extract(image, 100, 100)
