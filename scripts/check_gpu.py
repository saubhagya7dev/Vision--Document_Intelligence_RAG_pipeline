"""Check CUDA and optionally cached ColPali inference, without provider calls."""

import argparse
import json
import math
import os
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        action="store_true",
        help="Also test the configured ColPali model from local cache",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-downloads",
        action="store_true",
        help="Allow missing Hugging Face model/processor files to download",
    )
    args = parser.parse_args()
    # A smoke check should not implicitly download model weights or use credentials.
    if not args.allow_downloads:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import torch
    from PIL import Image, ImageDraw

    from vision_rag.config import settings
    from vision_rag.runtime import device_diagnostics

    report = {"diagnostics": device_diagnostics(), "checks": {}}
    encoder = None
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available; inspect diagnostics")
        left = torch.arange(16, device="cuda", dtype=torch.float32).reshape(4, 4)
        actual = (left @ left.T).cpu()
        expected = torch.arange(16, dtype=torch.float32).reshape(4, 4)
        torch.testing.assert_close(actual, expected @ expected.T)
        del left, actual, expected
        torch.cuda.empty_cache()
        report["checks"]["cuda_matrix_multiplication"] = "passed"
        if args.model:
            from vision_rag.models.colpali_embedder import ColPaliEmbeddingModel

            torch.cuda.reset_peak_memory_stats()
            started = perf_counter()
            encoder = ColPaliEmbeddingModel(
                model_name=settings.embedding_model_name,
                device="cuda",
                precision=settings.embedding_precision,
                batch_size=1,
            )
            torch.cuda.synchronize()
            report["model"] = settings.embedding_model_name
            report["model_load_seconds"] = round(perf_counter() - started, 3)
            report["parameter_devices"] = sorted(
                {str(parameter.device) for parameter in encoder.model.parameters()}
            )
            report["precision"] = str(encoder.model.dtype)
            report["after_load_allocated_bytes"] = torch.cuda.memory_allocated()
            report["after_load_reserved_bytes"] = torch.cuda.memory_reserved()
            report["meta_parameters"] = [
                name
                for name, parameter in encoder.model.named_parameters()
                if parameter.device.type == "meta"
            ]
            report["before_inference_reserved_bytes"] = torch.cuda.memory_reserved()
            with Image.new("RGB", (768, 1024), "white") as image:
                ImageDraw.Draw(image).text(
                    (32, 32), "Synthetic report: revenue 125 million", fill="black"
                )
                for name, operation in (
                    ("first_image", lambda: encoder.encode_images([image])),
                    ("warm_image", lambda: encoder.encode_images([image])),
                    (
                        "first_query",
                        lambda: encoder.encode_queries(["What is revenue?"]),
                    ),
                    (
                        "warm_query",
                        lambda: encoder.encode_queries(["What is revenue?"]),
                    ),
                ):
                    started = perf_counter()
                    vectors = operation()
                    torch.cuda.synchronize()
                    if (
                        len(vectors) != 1
                        or len(vectors[0]) != 128
                        or not all(math.isfinite(value) for value in vectors[0])
                    ):
                        raise RuntimeError(f"{name} returned invalid pooled embeddings")
                    report["checks"][name] = {
                        "status": "passed",
                        "dimensions": len(vectors[0]),
                        "seconds": round(perf_counter() - started, 3),
                    }
            report["peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            report["peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
            report["batch_size"] = 1
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
    finally:
        if encoder is not None:
            encoder.close()
        content = json.dumps(report, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content + "\n", encoding="utf-8")
        print(content)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
