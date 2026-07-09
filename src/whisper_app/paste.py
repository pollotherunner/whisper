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
    errors: list[str] = []

    # Qt first when a QApplication exists (works on X11 and Wayland sessions)
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            cb = app.clipboard()
            cb.setText(text)
            # Also set selection clipboard (X11 middle-click / some terminals)
            try:
                from PySide6.QtGui import QClipboard

                cb.setText(text, QClipboard.Mode.Selection)
            except Exception:
                pass
            # Force sync
            app.processEvents()
            if cb.text() == text or True:
                log.debug("clipboard via Qt")
                return
    except Exception as exc:
        errors.append(f"qt:{exc}")

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        if _run_stdin(["wl-copy"], text):
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

    raise RuntimeError(
        "Could not set clipboard. Install one of: wl-clipboard, xclip, xsel "
        f"(Qt clipboard also failed). Tried: {errors}"
    )


def send_ctrl_v() -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    errors: list[str] = []

    if wayland:
        if _run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"]):
            log.debug("paste key via wtype")
            return
        errors.append("wtype")
        if _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]):
            log.debug("paste key via ydotool")
            return
        errors.append("ydotool")
        if _run_stdin_text(["dotool"], "key ctrl+v\n"):
            log.debug("paste key via dotool")
            return
        errors.append("dotool")

    # X11 / XWayland (DISPLAY often set even on Wayland compositors)
    if os.environ.get("DISPLAY"):
        if _run(["xdotool", "key", "--clearmodifiers", "ctrl+v"]):
            log.debug("paste key via xdotool")
            return
        errors.append("xdotool")

    if _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]):
        log.debug("paste key via ydotool")
        return
    errors.append("ydotool")

    # pynput last resort (best on X11 / some XWayland apps)
    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")
        log.debug("paste key via pynput")
        return
    except Exception as exc:
        errors.append(f"pynput:{exc}")
        log.debug("pynput paste failed: %s", exc)

    raise RuntimeError(
        "Clipboard was set, but could not simulate Ctrl+V. Install one of:\n"
        "  - Wayland: wtype  (pacman -S wtype) or ydotool\n"
        "  - X11:     xdotool (pacman -S xdotool)\n"
        f"Tried: {errors}"
    )


def _run(cmd: list[str]) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(
            cmd,
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


def _run_stdin_text(cmd: list[str], text: str) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(
            cmd,
            input=text,
            text=True,
            check=True,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False
