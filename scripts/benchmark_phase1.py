"""Reproduce Phase 1 PDF timings without model weights or provider calls.

Run: python scripts/benchmark_phase1.py --output Docs/phase1-benchmark.json
Each case runs in a fresh process. Synthetic pages are deliberately not a
retrieval quality dataset. Cold cases bypass the app cache, not the OS cache.
"""

import argparse
import gc
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import median
from time import perf_counter

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from vision_rag.ingest.document_loader import DocumentLoader


def processor_name():
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0]
    return platform.processor()


def create_fixture(path, pages=8):
    images = []
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=12)
    try:
        for number in range(pages):
            image = Image.new("RGB", (1224, 1584), "white")
            draw = ImageDraw.Draw(image)
            draw.text(
                (70, 60),
                f"Synthetic report - page {number + 1}",
                fill="black",
                font=font,
            )
            for row in range(28):
                draw.text(
                    (70, 120 + row * 22),
                    f"Section {row + 1}: example observations and identifier "
                    f"R-{number:02}-{row:03}. Values require source verification.",
                    fill="black",
                    font=small,
                )
            for row in range(7):
                for col in range(5):
                    x, y = 70 + col * 200, 800 + row * 48
                    draw.rectangle((x, y, x + 200, y + 48), outline="black")
                    draw.text(
                        (x + 10, y + 10),
                        f"{(number + 1) * (row + 1) * (col + 1)}",
                        fill="black",
                        font=small,
                    )
            draw.line([(80, 1450), (80, 1200), (1100, 1200)], fill="black", width=3)
            draw.line(
                [
                    (80 + i * 90, 1430 - ((i * 37 + number * 13) % 200))
                    for i in range(12)
                ],
                fill="blue",
                width=3,
            )
            draw.text(
                (80, 1510),
                "Synthetic fixture; no real financial claims.",
                fill="black",
                font=small,
            )
            images.append(image)
        images[0].save(
            path, format="PDF", save_all=True, append_images=images[1:], resolution=144
        )
    finally:
        for image in images:
            image.close()


def baseline_render(path):
    # Historical full-document approach, with explicit cleanup for a fair comparison.
    images = []
    with pdfium.PdfDocument(str(path)) as pdf:
        for page in pdf:
            bitmap = page.render(scale=300 / 72)
            try:
                images.append(bitmap.to_pil().convert("RGB"))
            finally:
                bitmap.close()
                page.close()
    return images


def worker(path, operation):
    loader = DocumentLoader(dpi=300, cache_dir=path.parent / operation)
    if operation == "cached_page":
        loader.load_page(path, 4).close()
    times = []
    for iteration in range(3):
        started = perf_counter()
        if operation in {"baseline_count", "baseline_preview"}:
            images = baseline_render(path)
            _ = len(images) if operation == "baseline_count" else images[3].size
            for image in images:
                image.close()
        elif operation == "direct_count":
            assert loader.page_count(path) == 8
        elif operation == "single_page":
            DocumentLoader(dpi=300).load_page(path, 4).close()
        elif operation == "cached_page":
            loader.load_page(path, 4).close()
        elif operation == "bounded_render":
            for _, images in DocumentLoader(dpi=300).iter_batches(path, 2):
                assert len(images) <= 2
        elif operation == "populate_artifacts":
            fresh = DocumentLoader(
                dpi=300, cache_dir=path.parent / f"artifacts-{iteration}"
            )
            for _, images in fresh.iter_batches(path, 2):
                assert len(images) <= 2
        times.append(round((perf_counter() - started) * 1000, 3))
        gc.collect()
    result = {"median_ms": median(times), "samples_ms": times}
    try:
        import psutil

        memory = psutil.Process().memory_info()
        result["process_peak_working_set_bytes"] = getattr(memory, "peak_wset", None)
    except ImportError:
        result["process_peak_working_set_bytes"] = None
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker")
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.pdf, args.worker)))
        return
    with tempfile.TemporaryDirectory(prefix="vision-phase1-") as directory:
        path = Path(directory) / "synthetic.pdf"
        create_fixture(path)
        results = {}
        for operation in (
            "baseline_count",
            "direct_count",
            "baseline_preview",
            "single_page",
            "cached_page",
            "bounded_render",
            "populate_artifacts",
        ):
            result = subprocess.run(
                [sys.executable, __file__, "--worker", operation, "--pdf", str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            results[operation] = json.loads(result.stdout)
        report = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": processor_name(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ("pypdfium2", "pillow")
            },
            "pages": 8,
            "dpi": 300,
            "fixture": (
                "Synthetic raster pages with prose, tables, small labels "
                "and a line chart"
            ),
            "notes": [
                "Three wall-clock samples per case; separate process per case.",
                "Cold means no application artifact cache; OS caches are uncontrolled.",
                "Peak working set includes interpreter, imports and three samples.",
                "Optional peak memory uses psutil; no model or provider calls.",
                "PDF operations do not use the GPU or establish retrieval quality.",
                "Bounded render bypasses artifacts to isolate batching memory.",
            ],
            "results": results,
        }
        content = json.dumps(report, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content + "\n", encoding="utf-8")
        print(content)


if __name__ == "__main__":
    main()
