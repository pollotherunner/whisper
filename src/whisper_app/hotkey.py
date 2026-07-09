"""Global hotkeys for X11 / XWayland / Wayland.

Primary: evdev (works everywhere if user can read /dev/input).
Fallback: pynput (best on X11).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

# Linux input event codes (subset)
KEY_CODES = {
    "esc": 1,
    "escape": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "minus": 12,
    "equal": 13,
    "backspace": 14,
    "tab": 15,
    "q": 16,
    "w": 17,
    "e": 18,
    "r": 19,
    "t": 20,
    "y": 21,
    "u": 22,
    "i": 23,
    "o": 24,
    "p": 25,
    "a": 30,
    "s": 31,
    "d": 32,
    "f": 33,
    "g": 34,
    "h": 35,
    "j": 36,
    "k": 37,
    "l": 38,
    "z": 44,
    "x": 45,
    "c": 46,
    "v": 47,
    "b": 48,
    "n": 49,
    "m": 50,
    "space": 57,
    "f1": 59,
    "f2": 60,
    "f3": 61,
    "f4": 62,
    "f5": 63,
    "f6": 64,
    "f7": 65,
    "f8": 66,
    "f9": 67,
    "f10": 68,
    "f11": 87,
    "f12": 88,
    "enter": 28,
    "return": 28,
}

# Modifier key codes
MOD_CODES = {
    "ctrl": {29, 97},  # LCTRL, RCTRL
    "control": {29, 97},
    "shift": {42, 54},
    "alt": {56, 100},
    "super": {125, 126},
    "meta": {125, 126},
    "win": {125, 126},
}


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: frozenset[str]
    key: str
    raw: str


def parse_hotkey(spec: str) -> HotkeySpec:
    parts = [p.strip().lower() for p in spec.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Empty hotkey: {spec!r}")
    key = parts[-1]
    mods = frozenset(parts[:-1])
    for m in mods:
        if m not in MOD_CODES:
            raise ValueError(f"Unknown modifier {m!r} in {spec!r}")
    if key not in KEY_CODES and key not in MOD_CODES:
        # allow single named keys
        if len(key) == 1 and key.isalnum():
            pass
        elif key not in KEY_CODES:
            raise ValueError(f"Unknown key {key!r} in {spec!r}")
    return HotkeySpec(modifiers=mods, key=key, raw=spec)


class HotkeyListener:
    """Background hotkey listener with pluggable backends."""

    def __init__(
        self,
        toggle: str,
        cancel: str,
        on_toggle: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self.toggle = parse_hotkey(toggle)
        self.cancel = parse_hotkey(cancel)
        self.on_toggle = on_toggle
        self.on_cancel = on_cancel
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backend = "none"

    @property
    def backend(self) -> str:
        return self._backend

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        if _try_start_evdev(self):
            self._backend = "evdev"
            log.info("Hotkeys via evdev (toggle=%s cancel=%s)", self.toggle.raw, self.cancel.raw)
            return
        if _try_start_pynput(self):
            self._backend = "pynput"
            log.info("Hotkeys via pynput (toggle=%s cancel=%s)", self.toggle.raw, self.cancel.raw)
            return
        raise RuntimeError(
            "Could not start global hotkeys. On Wayland, add your user to the 'input' group:\n"
            "  sudo usermod -aG input $USER && re-login\n"
            "Or install pynput and use an X11 session."
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None


def _try_start_evdev(listener: HotkeyListener) -> bool:
    try:
        from evdev import InputDevice, categorize, ecodes, list_devices
    except Exception as exc:
        log.debug("evdev unavailable: %s", exc)
        return False

    devices = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except Exception:
            continue
        caps = dev.capabilities().get(ecodes.EV_KEY, [])
        # keyboards typically have many keys including KEY_A / KEY_SPACE
        if ecodes.KEY_A in caps and ecodes.KEY_SPACE in caps:
            devices.append(dev)

    if not devices:
        log.debug("No readable keyboard devices for evdev")
        return False

    pressed: set[int] = set()
    toggle_latch = False
    cancel_latch = False

    def mods_satisfied(spec: HotkeySpec) -> bool:
        for m in spec.modifiers:
            if pressed.isdisjoint(MOD_CODES[m]):
                return False
        return True

    def key_code(spec: HotkeySpec) -> int:
        return KEY_CODES[spec.key]

    def loop() -> None:
        nonlocal toggle_latch, cancel_latch
        from select import select

        while not listener._stop.is_set():
            try:
                r, _, _ = select(devices, [], [], 0.25)
            except Exception as exc:
                log.debug("evdev select error: %s", exc)
                break
            for dev in r:
                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        code = event.code
                        if event.value == 1:  # down
                            pressed.add(code)
                        elif event.value == 0:  # up
                            pressed.discard(code)
                        else:
                            continue  # hold

                        # Toggle
                        t_key = key_code(listener.toggle)
                        if t_key in pressed and mods_satisfied(listener.toggle):
                            if not toggle_latch:
                                toggle_latch = True
                                try:
                                    listener.on_toggle()
                                except Exception:
                                    log.exception("on_toggle failed")
                        else:
                            toggle_latch = False

                        c_key = key_code(listener.cancel)
                        if c_key in pressed and mods_satisfied(listener.cancel):
                            if not cancel_latch:
                                cancel_latch = True
                                try:
                                    listener.on_cancel()
                                except Exception:
                                    log.exception("on_cancel failed")
                        else:
                            cancel_latch = False
                except OSError:
                    continue

    listener._thread = threading.Thread(target=loop, name="hotkey-evdev", daemon=True)
    listener._thread.start()
    return True


def _try_start_pynput(listener: HotkeyListener) -> bool:
    try:
        from pynput import keyboard
    except Exception as exc:
        log.debug("pynput unavailable: %s", exc)
        return False

    # Only reliable on X11; try anyway
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        log.debug("pynput on Wayland is often blocked; trying anyway as fallback")

    def parse_pynput_combo(spec: HotkeySpec):
        parts = []
        for m in sorted(spec.modifiers):
            if m in ("ctrl", "control"):
                parts.append("<ctrl>")
            elif m == "shift":
                parts.append("<shift>")
            elif m == "alt":
                parts.append("<alt>")
            elif m in ("super", "meta", "win"):
                parts.append("<cmd>")
        key = spec.key
        if key in ("esc", "escape"):
            parts.append("<esc>")
        elif key == "space":
            parts.append("<space>")
        elif len(key) == 1:
            parts.append(key)
        else:
            parts.append(f"<{key}>")
        return "+".join(parts)

    try:
        hotkeys = {
            parse_pynput_combo(listener.toggle): listener.on_toggle,
            parse_pynput_combo(listener.cancel): listener.on_cancel,
        }
        hk = keyboard.GlobalHotKeys(hotkeys)

        def run() -> None:
            with hk:
                while not listener._stop.is_set():
                    listener._stop.wait(0.25)
                hk.stop()

        listener._thread = threading.Thread(target=run, name="hotkey-pynput", daemon=True)
        listener._thread.start()
        return True
    except Exception as exc:
        log.debug("pynput start failed: %s", exc)
        return False
