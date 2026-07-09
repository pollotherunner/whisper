"""Parakeet TDT ASR via Hugging Face Transformers (offline after download)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch

from .config import ModelConfig
from .device import DeviceInfo, pick_device

log = logging.getLogger(__name__)

MODEL_MARKER = "config.json"


def model_is_ready(local_dir: Path) -> bool:
    return (local_dir / MODEL_MARKER).is_file()


def ensure_model(cfg: ModelConfig) -> Path:
    """Download model into program folder if missing. Afterwards works offline."""
    local_dir = cfg.local_dir()
    if model_is_ready(local_dir):
        log.info("Model present at %s", local_dir)
        return local_dir

    log.info("Model not found at %s — downloading %s (one-time, needs network)...", local_dir, cfg.repo_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required for first-time model download") from exc

    snapshot_download(
        repo_id=cfg.repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
    )
    if not model_is_ready(local_dir):
        raise RuntimeError(f"Download finished but {MODEL_MARKER} missing in {local_dir}")
    log.info("Model ready at %s", local_dir)
    return local_dir


class AsrEngine:
    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg
        self.device_info: DeviceInfo | None = None
        self.processor = None
        self.model = None

    def load(self) -> DeviceInfo:
        local_dir = ensure_model(self.cfg)
        info = pick_device(self.cfg.device, self.cfg.dtype)

        try:
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        except Exception:
            AutoModelForSpeechSeq2Seq = None  # type: ignore
            from transformers import AutoProcessor

        # Prefer AutoModelForTDT when available (Parakeet TDT)
        model_cls = None
        try:
            from transformers import AutoModelForTDT

            model_cls = AutoModelForTDT
        except Exception:
            model_cls = AutoModelForSpeechSeq2Seq

        if model_cls is None:
            raise RuntimeError(
                "Your transformers build has no AutoModelForTDT / suitable ASR class. "
                "Upgrade transformers (see README)."
            )

        log.info("Loading processor from %s", local_dir)
        self.processor = AutoProcessor.from_pretrained(str(local_dir), local_files_only=True)

        log.info("Loading model (%s / %s)...", info.backend, info.name)
        def _load(device_info: DeviceInfo):
            # transformers API: prefer torch_dtype (widely supported), fall back to dtype
            try:
                m = model_cls.from_pretrained(
                    str(local_dir),
                    torch_dtype=device_info.dtype,
                    local_files_only=True,
                )
            except TypeError:
                m = model_cls.from_pretrained(
                    str(local_dir),
                    dtype=device_info.dtype,
                    local_files_only=True,
                )
            m.to(device_info.device)
            m.eval()
            return m

        try:
            self.model = _load(info)
        except Exception as exc:
            if info.backend == "cpu":
                raise
            log.warning("Model load on GPU failed (%s); retrying on CPU", exc)
            info = pick_device("cpu", "float32")
            self.model = _load(info)

        self.device_info = info
        log.info("ASR ready on %s (%s)", info.name, info.backend)
        return info

    @torch.inference_mode()
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if self.model is None or self.processor is None or self.device_info is None:
            raise RuntimeError("ASR engine not loaded")

        if audio.ndim > 1:
            audio = np.mean(audio, axis=-1)
        audio = np.asarray(audio, dtype=np.float32)

        # Resample if needed
        if sample_rate != 16000:
            audio = _resample(audio, sample_rate, 16000)
            sample_rate = 16000

        inputs = self.processor(audio, sampling_rate=sample_rate, return_tensors="pt")
        # Move tensors
        move_kwargs = {}
        for k, v in list(inputs.items()):
            if hasattr(v, "to"):
                inputs[k] = v.to(self.device_info.device)
                if torch.is_floating_point(inputs[k]):
                    inputs[k] = inputs[k].to(dtype=self.device_info.dtype)

        try:
            # Parakeet TDT generate API
            output = self.model.generate(**inputs, return_dict_in_generate=True)
            sequences = getattr(output, "sequences", output)
            text = self.processor.decode(sequences, skip_special_tokens=True)
        except TypeError:
            # Fallback: pipeline-style or older generate
            output = self.model.generate(**inputs)
            text = self.processor.batch_decode(output, skip_special_tokens=True)

        if isinstance(text, list):
            text = text[0] if text else ""
        if isinstance(text, tuple):
            text = text[0]
        return str(text).strip()


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return audio
    try:
        import torchaudio

        wav = torch.from_numpy(audio).float().unsqueeze(0)
        res = torchaudio.functional.resample(wav, orig_sr, target_sr)
        return res.squeeze(0).numpy()
    except Exception:
        # Linear resample fallback
        duration = audio.shape[0] / float(orig_sr)
        target_len = int(duration * target_sr)
        x_old = np.linspace(0.0, 1.0, num=audio.shape[0], endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)
