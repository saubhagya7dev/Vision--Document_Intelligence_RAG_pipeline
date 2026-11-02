"""Native PDF inspection and bounded, page-local text chunks.

Geometry uses unrotated PDF coordinates (origin bottom-left), in points.
Heuristics deliberately escalate ambiguous layouts instead of claiming certainty.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from vision_rag.ingest.document_loader import PDFIUM_LOCK
from vision_rag.telemetry import stage

PROCESSING_VERSION = "native-layout-v1"
MODES = ("auto", "text", "visual", "ocr", "skip")


@dataclass
class Block:
    text: str
    bbox: tuple[float, float, float, float]
    size: float = 0
    heading: str | None = None


@dataclass
class Inspection:
    number: int
    width: float
    height: float
    rotation: int
    native_text: str
    blocks: list[Block]
    features: dict[str, Any]
    quality: str
    reasons: list[str]
    visual: bool
    ocr: bool
    warnings: list[str] = field(default_factory=list)

    def data(self) -> dict[str, Any]:
        return asdict(self)


def quality(text: str) -> tuple[str, list[str]]:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return "missing", ["no_native_text"]
    bad = sum(
        c == "\ufffd" or unicodedata.category(c) in ("Cc", "Co", "Cs") for c in chars
    )
    if bad / len(chars) > 0.02:
        return "poor", ["corrupted_characters"]
    if len(chars) < 40:
        return "uncertain", ["sparse_text"]
    if sum(c.isalnum() for c in chars) / len(chars) < 0.45:
        return "poor", ["low_readable_character_ratio"]
    if max(Counter(chars).values()) / len(chars) > 0.45:
        return "poor", ["repeated_characters"]
    return "usable", ["usable_native_text"]


def inspect_page(path: Path, number: int) -> Inspection:
    with stage("native_extraction", page=number), PDFIUM_LOCK:
        with pdfium.PdfDocument(str(path)) as pdf:
            page = pdf[number - 1]
            textpage = None
            try:
                width, height = page.get_size()
                rotation = page.get_rotation()
                textpage = page.get_textpage()
                if textpage.count_chars() > 200_000:
                    raise ValueError("Page exceeds native extraction character limit")
                text = textpage.get_text_bounded(errors="replace").replace("\r\n", "\n")
                blocks: list[Block] = []
                images: list[float] = []
                paths = 0
                large_paths = 0
                rules = 0
                invisible = False
                area = max(width * height, 1)
                for count, obj in enumerate(page.get_objects(textpage=textpage)):
                    if count >= 20_000:
                        raise ValueError("Page exceeds object inspection limit")
                    left, bottom, right, top = obj.get_bounds()
                    fraction = max(0, right - left) * max(0, top - bottom) / area
                    if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        value = obj.extract().strip()
                        if value:
                            size = float(obj.get_font_size())
                            blocks.append(
                                Block(value, (left, bottom, right, top), size)
                            )
                            # Invisible OCR layers may be useful but need visual review.
                            invisible |= raw.FPDFTextObj_GetTextRenderMode(obj) == 3
                    elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                        images.append(fraction)
                    elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                        paths += 1
                        large_paths += fraction > 0.025
                        rules += (right - left > width * 0.1 and top - bottom < 3) or (
                            top - bottom > height * 0.1 and right - left < 3
                        )
            finally:
                if textpage is not None:
                    textpage.close()
                page.close()

    state, reasons = quality(text)
    # A small isolated logo does not select vision. Vector rules/large shapes do.
    significant_image = max(images, default=0) >= 0.06 or sum(images) >= 0.12
    vector_content = rules >= 4 or large_paths >= 1 or paths >= 15
    # Detect a vertical gutter from text-object centers; conservative ambiguity flag.
    left_column = [b for b in blocks if b.bbox[2] < width * 0.52]
    right_column = [b for b in blocks if b.bbox[0] > width * 0.48]
    columns = len(left_column) >= 4 and len(right_column) >= 4
    if significant_image:
        reasons.append("substantial_raster_content")
    if vector_content:
        reasons.append("vector_graphics_or_table_rules")
    if columns:
        reasons.append("multiple_columns")
    if rotation:
        reasons.append("rotated_page")
    if invisible:
        reasons.append("invisible_text_layer_requires_verification")
    empty = not text.strip() and not images and not paths
    if empty:
        reasons = ["empty_page"]
    visual = not empty and (
        state != "usable"
        or significant_image
        or vector_content
        or columns
        or bool(rotation)
        or invisible
    )
    # Preserve extraction order for ambiguous columns and flag it; never promise
    # correct table cells or reading order. Ordinary blocks use top-to-bottom order.
    if not columns and not rotation:
        blocks.sort(key=lambda b: (-round(b.bbox[3] / 3), b.bbox[0]))
    sizes = sorted(b.size for b in blocks if b.size > 0)
    median = sizes[len(sizes) // 2] if sizes else 12
    heading = None
    for block in blocks:
        if len(block.text) < 150 and block.size >= median * 1.25:
            heading = block.text
        block.heading = heading
    return Inspection(
        number,
        width,
        height,
        rotation,
        text,
        blocks,
        {
            "image_area_fraction": min(sum(images), 1),
            "path_count": paths,
            "rule_count": rules,
            "multiple_columns": columns,
            "invisible_text": invisible,
            "coordinate_system": "pdf-bottom-left-points",
        },
        state,
        reasons,
        visual,
        not empty and state in ("missing", "poor"),
        ["reading_order_uncertain"] if columns or rotation else [],
    )


def tokens(text: str) -> list[int]:
    """UTF-8 bytes give a conservative budget for byte-backed tokenizers.

    This is an ingestion budget, not a claim to use a particular model tokenizer.
    Encoder-specific special tokens and limits must be checked by Phase 4.
    """
    return list(text.encode("utf-8"))


def chunks(
    blocks: list[Block], limit: int = 1200, overlap: int = 120
) -> list[dict[str, Any]]:
    if limit < 32 or not 0 <= overlap < limit:
        raise ValueError("Require chunk limit >=32 and 0 <= overlap < limit")
    sections: list[list[Block]] = []
    for block in blocks:
        if not sections or sections[-1][-1].heading != block.heading:
            sections.append([])
        sections[-1].append(block)
    result: list[dict[str, Any]] = []
    for section in sections:
        text = "\n".join(b.text for b in section)
        ranges = []
        offset = 0
        for block in section:
            ranges.append((offset, offset + len(block.text), block.bbox))
            offset += len(block.text) + 1
        start = 0
        while start < len(text):
            piece = (
                text[start:].encode("utf-8")[:limit].decode("utf-8", errors="ignore")
            )
            if start + len(piece) < len(text):
                split = max(piece.rfind("\n"), piece.rfind(" "))
                if split > len(piece) // 2:
                    piece = piece[: split + 1]
            end = start + len(piece)
            if piece.strip():
                result.append(
                    {
                        "text": piece,
                        "units": len(tokens(piece)),
                        "heading": section[0].heading,
                        "boxes": [
                            box
                            for left, right, box in ranges
                            if left < end and right > start
                        ],
                        "section_start": start,
                        "section_end": end,
                    }
                )
            if end == len(text):
                break
            tail = (
                piece.encode("utf-8")[-overlap:].decode("utf-8", errors="ignore")
                if overlap
                else ""
            )
            start = max(start + 1, end - len(tail))
    return result


def lexical_terms(query: str) -> list[str]:
    return re.findall(r"[^\W_]+", query, re.UNICODE)[:32]
