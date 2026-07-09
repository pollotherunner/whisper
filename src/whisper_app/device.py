"""Pick inference device: NVIDIA CUDA / AMD ROCm (via torch CUDA API) → CPU."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import torch

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    device: torch.device
    dtype: torch.dtype
    name: str
    backend: str  # cuda | rocm | cpu


def _gpu_name() -> str:
    try:
        return torch.cuda.get_device_name(0)
    except Exception:
        return "GPU"


def _is_rocm() -> bool:
    hip = getattr(torch.version, "hip", None)
    return bool(hip)


def resolve_dtype(requested: str, device: torch.device) -> torch.dtype:
    req = (requested or "auto").lower()
    if req == "float32" or req == "fp32":
        return torch.float32
    if req == "float16" or req == "fp16":
        return torch.float16
    if req == "bfloat16" or req == "bf16":
        return torch.bfloat16
    # auto
    if device.type == "cuda":
        # GTX 16-series prefers float16; bfloat16 needs Ampere+
        major, _ = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
        if major >= 8:
            return torch.bfloat16
        return torch.float16
    return torch.float32


def pick_device(preference: str = "auto", dtype_pref: str = "auto") -> DeviceInfo:
    """
    preference:
      - auto: try GPU first, then CPU
      - cuda: try GPU, fall back to CPU if unavailable/fails
      - cpu: force CPU
    """
    pref = (preference or "auto").lower()

    if pref == "cpu":
        device = torch.device("cpu")
        return DeviceInfo(
            device=device,
            dtype=resolve_dtype(dtype_pref, device),
            name="CPU",
            backend="cpu",
        )

    # auto | cuda → attempt GPU
    if torch.cuda.is_available():
        try:
            # Smoke-test a tiny allocation so we fail early on broken drivers
            t = torch.zeros(1, device="cuda")
            del t
            torch.cuda.empty_cache()
            device = torch.device("cuda")
            backend = "rocm" if _is_rocm() else "cuda"
            name = _gpu_name()
            dtype = resolve_dtype(dtype_pref, device)
            log.info("Using GPU backend=%s name=%s dtype=%s", backend, name, dtype)
            return DeviceInfo(device=device, dtype=dtype, name=name, backend=backend)
        except Exception as exc:
            log.warning("GPU init failed (%s); falling back to CPU", exc)

    if pref == "cuda":
        log.warning("CUDA/ROCm requested but unavailable; falling back to CPU")

    device = torch.device("cpu")
    return DeviceInfo(
        device=device,
        dtype=resolve_dtype("float32", device),
        name="CPU",
        backend="cpu",
    )
