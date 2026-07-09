"""Copy text to clipboard and paste into the focused window (Ctrl+V)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)


def paste_text(text: str, delay_ms: int = 80) -> None:
    if not text:
        log.info("Nothing to paste (empty transcription)")
        return
    set_clipboard(text)
    time.sleep(max(0, delay_ms) / 1000.0)
    send_ctrl_v()


def set_clipboard(text: str) -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    errors: list[str] = []

    # Prefer native clipboard tools for the session
    if session == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        if _run_stdin(["wl-copy", "--"], text):
            log.debug("clipboard via wl-copy")
            return
        errors.append("wl-copy")

    if _run_stdin(["xclip", "-selection", "clipboard"], text):
        log.debug("clipboard via xclip")
        return
    errors.append("xclip")

    if _run_stdin(["xsel", "--clipboard", "--input"], text):
        log.debug("clipboard via xsel")
        return
    errors.append("xsel")

    # Qt fallback (works in GUI thread context if QApp exists)
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(text)
            log.debug("clipboard via Qt")
            return
    except Exception as exc:
        errors.append(f"qt:{exc}")

    raise RuntimeError(
        "Could not set clipboard. Install one of: wl-copy (wl-clipboard), xclip, xsel. "
        f"Tried: {errors}"
    )


def send_ctrl_v() -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

    if wayland:
        if _run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]):
            log.debug("paste key via wtype")
            return
        if _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]):  # ctrl+v
            log.debug("paste key via ydotool")
            return
        if _run(["dotool"], input_text="key ctrl+v\n"):
            log.debug("paste key via dotool")
            return

    # X11 / XWayland
    if _run(["xdotool", "key", "--clearmodifiers", "ctrl+v"]):
        log.debug("paste key via xdotool")
        return

    # ydotool works on X11 too if daemon is up
    if _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]):
        log.debug("paste key via ydotool")
        return

    # pynput last resort (X11)
    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")
        log.debug("paste key via pynput")
        return
    except Exception as exc:
        log.debug("pynput paste failed: %s", exc)

    raise RuntimeError(
        "Could not simulate Ctrl+V. Install one of: wtype (Wayland), xdotool (X11), ydotool."
    )


def _run(cmd: list[str], input_text: str | None = None) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(
            cmd,
            input=input_text,
            text=True if input_text is not None else None,
            check=True,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _run_stdin(cmd: list[str], text: str) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            check=True,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False
