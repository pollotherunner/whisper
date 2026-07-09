"""Resolve paths relative to the application root (folder that contains ./whisper)."""

from __future__ import annotations

from pathlib import Path


def app_root() -> Path:
    """Directory that owns the `whisper` launcher and `config.toml`."""
    # src/whisper_app/paths.py -> parents: whisper_app, src, app_root
    return Path(__file__).resolve().parents[2]


def resolve_path(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return (app_root() / p).resolve()
