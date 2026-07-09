"""Microphone capture at 16 kHz mono."""

from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device: str | int | None = None,
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = _parse_device(device)
        self.on_level = on_level
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        import sounddevice as sd

        self._frames = []
        self._recording = True

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                log.debug("audio status: %s", status)
            chunk = np.copy(indata[:, 0] if indata.ndim > 1 else indata)
            with self._lock:
                self._frames.append(chunk.astype(np.float32, copy=False))
            if self.on_level is not None:
                # RMS level 0..1-ish for waveform
                rms = float(np.sqrt(np.mean(np.square(chunk))) + 1e-12)
                self.on_level(min(1.0, rms * 8.0))

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=callback,
            blocksize=1024,
        )
        self._stream.start()
        log.info("Recording started (sr=%s device=%s)", self.sample_rate, self.device)

    def stop(self) -> np.ndarray:
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        self._recording = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            if not self._frames:
                audio = np.zeros(0, dtype=np.float32)
            else:
                audio = np.concatenate(self._frames, axis=0)
            self._frames = []
        log.info("Recording stopped (%s samples, %.2fs)", audio.shape[0], audio.shape[0] / self.sample_rate)
        return audio

    def cancel(self) -> None:
        self.stop()


def _parse_device(device: str | int | None) -> int | str | None:
    if device is None or device == "":
        return None
    if isinstance(device, int):
        return device
    s = str(device).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    return s
