"""Load and validate config.toml."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from .paths import app_root, resolve_path


@dataclass
class HotkeyConfig:
    toggle: str = "ctrl+space"
    cancel: str = "escape"


@dataclass
class ModelConfig:
    repo_id: str = "nvidia/parakeet-tdt-0.6b-v3"
    path: str = "models/parakeet-tdt-0.6b-v3"
    device: str = "auto"  # auto | cuda | cpu
    language: str = "auto"
    dtype: str = "auto"  # auto | float16 | float32 | bfloat16

    def local_dir(self) -> Path:
        return resolve_path(self.path)


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    device: str = ""
    channels: int = 1


@dataclass
class PasteConfig:
    delay_ms: int = 80


@dataclass
class UiConfig:
    show_waveform: bool = True


@dataclass
class AppConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    paste: PasteConfig = field(default_factory=PasteConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    config_path: Path | None = None


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or (app_root() / "config.toml")
    raw: dict[str, Any] = {}
    if cfg_path.is_file():
        with cfg_path.open("rb") as f:
            raw = tomllib.load(f)

    hot = _section(raw, "hotkey")
    model = _section(raw, "model")
    audio = _section(raw, "audio")
    paste = _section(raw, "paste")
    ui = _section(raw, "ui")

    return AppConfig(
        hotkey=HotkeyConfig(
            toggle=str(hot.get("toggle", "ctrl+space")),
            cancel=str(hot.get("cancel", "escape")),
        ),
        model=ModelConfig(
            repo_id=str(model.get("repo_id", "nvidia/parakeet-tdt-0.6b-v3")),
            path=str(model.get("path", "models/parakeet-tdt-0.6b-v3")),
            device=str(model.get("device", "auto")).lower(),
            language=str(model.get("language", "auto")).lower(),
            dtype=str(model.get("dtype", "auto")).lower(),
        ),
        audio=AudioConfig(
            sample_rate=int(audio.get("sample_rate", 16000)),
            device=str(audio.get("device", "") or ""),
            channels=int(audio.get("channels", 1)),
        ),
        paste=PasteConfig(delay_ms=int(paste.get("delay_ms", 80))),
        ui=UiConfig(show_waveform=bool(ui.get("show_waveform", True))),
        config_path=cfg_path if cfg_path.is_file() else None,
    )
