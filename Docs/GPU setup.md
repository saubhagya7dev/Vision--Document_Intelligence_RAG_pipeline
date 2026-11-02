# CUDA setup and verification

Follow-up completed on 2 November 2026, at the user's request. This stays within Phase 1.

## Installed and configured

- Project environment: .venv, Windows x86-64, Python 3.14.9.
- Torch: 2.13.0+cu130, replacing 2.13.0 CPU-only.
- TorchVision: 0.28.0+cu130, replacing its CPU build.
- CUDA runtime: 13.0; existing NVIDIA driver: 617.14.
- GPU: NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB.
- Local .env: EMBEDDING_DEVICE=auto and INGESTION_BATCH_SIZE=1. Existing credentials were preserved. .env is ignored by Git.
- The embedder now releases unused CUDA loading buffers once after successful model/processor initialization. This does not free weights or eliminate inference memory requirements.
- The running Vision development server was stopped to release locked Torch DLLs, then restarted. Its health endpoint returns ok; diagnostics reports CUDA available, automatic selection, and batch size 1. Model state remains not_loaded until an ingestion/query initializes components.

No system CUDA toolkit or NVIDIA driver was replaced. The package wheels came from the official PyTorch CUDA index. The interrupted Windows uninstall left stale CPU package metadata; that exact metadata directory was removed, and the installed environment passes uv pip check.

## Reproduce this named profile

Stop the running Vision server before replacing Torch on Windows.

```powershell
uv sync --extra dev --frozen
uv pip install --python .venv/Scripts/python.exe -r requirements/cuda-windows-py314.txt
.\.venv\Scripts\python.exe scripts/check_gpu.py
# Optional: exercise real ColPali, allowing missing supporting files to download.
.\.venv\Scripts\python.exe scripts/check_gpu.py --model --allow-downloads --output Docs/gpu-smoke.json
.\.venv\Scripts\python.exe -m vision_rag.api.main
```

The CUDA profile deliberately does not replace the platform-neutral uv.lock. Use .venv Python or uv run --no-sync after installation. A normal uv sync/run may restore the locked default Torch build; apply the CUDA profile again afterward.

This profile targets the inspected Windows/Python 3.14 environment. Other operating systems, Python versions, drivers and GPUs must be checked against the [official installer selector](https://pytorch.org/get-started/locally/) and [official CUDA wheel index](https://download.pytorch.org/whl/cu130/torch/).

## Real checks

The check script verifies a CUDA matrix multiplication against its CPU result. With --model it runs the existing ColPali adapter on one synthetic report page and a short query, checks for finite 128-dimensional pooled vectors, and records timing and allocator memory.

Final run with the application loading-buffer cleanup:

| Check | Result |
| --- | --- |
| torch.cuda.is_available() | true |
| CUDA matrix computation | passed |
| ColPali model | vidore/colpali-v1.3 |
| Precision and batch | float16, one page |
| Model initialization | 19.188 seconds |
| First image embedding | 7.246 seconds |
| Subsequent image embedding | 3.926 seconds |
| First query embedding | 0.191 seconds |
| Subsequent query embedding | 0.045 seconds |
| Image/query dimensions and finiteness | passed |

The final raw result is gpu-smoke.json. gpu-smoke-initial.json records the first successful check before the loading-buffer cleanup. Those runs are not a controlled performance comparison: driver/kernel caches, network metadata access, and other conditions differ.

The model weights were already cached. Supporting Hugging Face files/metadata required network access; strict offline model initialization failed and is not claimed to work. The script defaults to offline for model loading unless --allow-downloads is supplied. Its basic CUDA-only check makes no model download. No Gemini request was made.

## Memory and interpretation

After loading, Torch reported about 5.54 GiB allocated for the model. Peak allocated memory during the smoke check was about 8.11 GiB, exceeding the physical VRAM capacity. Windows may back CUDA allocations using shared system memory; physical residency/paging was not directly measured. Successful execution therefore does not establish that the workload fits wholly in 6 GB VRAM.

The raw report includes cuda:0 weights and a meta-resident model.lm_head.weight. The verified operation is the embedding forward path; no claim is made about language generation using that head.

Batch size 1 is a conservative local setting, not a guarantee against memory pressure on all documents or other machines. This is one synthetic smoke check, not a representative throughput benchmark, CPU/GPU speedup comparison, or retrieval-quality evaluation. Full model/provider workflow latency and real-corpus quality remain unverified.

PDF page rendering still uses CPU/PDFium. CUDA is used for ColPali embedding computation.

## Regression checks

After installation and the loading-buffer change:

- 38 tests passed, including two new checks for CUDA-only loading-cache cleanup.
- Ruff and strict mypy passed.
- Python compilation and frontend JavaScript syntax checks passed.
- uv pip check reports all 97 installed packages compatible.
- The restarted HTTP server reports health ok and CUDA enabled.
- Two previously documented dependency deprecation warnings remain.

The CPU-only environment recorded in Phase 1 results.md describes the initial baseline. This follow-up supersedes its GPU-unverified status for the single-machine smoke checks above. No later project phase was started.
