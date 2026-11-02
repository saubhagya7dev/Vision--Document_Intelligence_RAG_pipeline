"""Hardware diagnostics do not download or initialize models."""

import importlib.metadata
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch


def device_diagnostics() -> dict[str, Any]:
    import torch

    cuda = torch.cuda.is_available()
    nvidia = None
    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            result = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                nvidia = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    mps = bool(
        getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
    )
    accelerator = None
    if cuda:
        properties = torch.cuda.get_device_properties(0)
        free_bytes, _ = torch.cuda.mem_get_info(0)
        accelerator = {
            "name": properties.name,
            "total_memory_bytes": properties.total_memory,
            "free_memory_bytes": free_bytes,
            "compute_capability": list(torch.cuda.get_device_capability(0)),
            "bfloat16_supported": torch.cuda.is_bf16_supported(),
            "compiled_architectures": torch.cuda.get_arch_list(),
        }
    action = None
    if nvidia and torch.version.cuda is None:
        action = (
            "NVIDIA hardware detected, but this PyTorch installation has no "
            "CUDA support. Install a compatible CUDA build using "
            "https://pytorch.org/get-started/locally/"
        )
    elif nvidia and not cuda:
        action = (
            "A CUDA build is installed but CUDA cannot initialize. Check the "
            "NVIDIA driver, device visibility, and PyTorch/GPU compatibility. "
            "Auto selection currently falls back to CPU."
        )
    return {
        "torch_version": importlib.metadata.version("torch"),
        "cuda_build": torch.version.cuda,
        "cuda_available": cuda,
        "mps_available": mps,
        "nvidia_hardware": nvidia,
        "accelerator": accelerator,
        "recommended_device": "cuda" if cuda else "mps" if mps else "cpu",
        "action": action,
    }


def select_device(
    requested: str = "auto", precision: str = "auto"
) -> tuple[str, "torch.dtype"]:
    import torch

    if requested == "auto":
        requested = (
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
    if requested not in {"cuda", "mps", "cpu"}:
        raise ValueError("Device must be auto, cuda, mps, or cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA requested but unavailable; inspect /api/v1/diagnostics"
        )
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS requested but unavailable")
    if precision == "auto":
        precision = "float32" if requested == "cpu" else "float16"
    if precision not in {"float16", "float32", "bfloat16"}:
        raise ValueError("Precision must be auto, float16, bfloat16, or float32")
    if requested == "cpu" and precision != "float32":
        raise ValueError("The CPU profile requires float32")
    if precision == "bfloat16" and (
        requested != "cuda" or not torch.cuda.is_bf16_supported()
    ):
        raise ValueError("bfloat16 requires a compatible CUDA accelerator")
    return requested, getattr(torch, precision)
