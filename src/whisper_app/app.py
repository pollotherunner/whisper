"""Main application orchestration."""

from __future__ import annotations

import logging
import threading
from enum import Enum, auto

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor

from .asr import AsrEngine
from .audio import AudioRecorder
from .config import AppConfig
from .hotkey import HotkeyListener
from .overlay import OverlayWindow
from .paste import paste_text

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()


class Bridge(QObject):
    """Thread-safe signals into the Qt main thread."""

    level = Signal(float)
    show_recording = Signal()
    show_processing = Signal()
    hide_overlay = Signal()
    paste = Signal(str)
    error = Signal(str)
    status = Signal(str)


class WhisperApp(QObject):
    def __init__(self, qt_app: QApplication, cfg: AppConfig) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.cfg = cfg
        self.state = State.IDLE
        self._lock = threading.Lock()

        self.bridge = Bridge()
        self.overlay = OverlayWindow(show_waveform=cfg.ui.show_waveform)
        self.overlay.set_hotkey_label(cfg.hotkey.toggle)

        self.bridge.level.connect(self.overlay.set_level)
        self.bridge.show_recording.connect(self.overlay.show_recording)
        self.bridge.show_processing.connect(self.overlay.show_processing)
        self.bridge.hide_overlay.connect(self.overlay.hide_overlay)
        self.bridge.paste.connect(self._do_paste)
        self.bridge.error.connect(self._on_error)
        self.bridge.status.connect(lambda m: log.info("%s", m))

        self.recorder = AudioRecorder(
            sample_rate=cfg.audio.sample_rate,
            channels=cfg.audio.channels,
            device=cfg.audio.device or None,
            on_level=lambda lv: self.bridge.level.emit(lv),
        )
        self.engine = AsrEngine(cfg.model)
        self.hotkeys: HotkeyListener | None = None
        self._tray: QSystemTrayIcon | None = None

    def start(self) -> None:
        self._setup_tray("Loading model…")
        # Load model in background so the event loop is responsive
        threading.Thread(target=self._load_model, name="asr-load", daemon=True).start()

    def _load_model(self) -> None:
        try:
            info = self.engine.load()
            msg = f"Ready on {info.name} ({info.backend})"
            self.bridge.status.emit(msg)
            QTimer.singleShot(0, lambda: self._on_ready(msg))
        except Exception as exc:
            log.exception("Failed to load model")
            self.bridge.error.emit(f"Model load failed: {exc}")

    def _on_ready(self, msg: str) -> None:
        self._setup_tray(msg)
        try:
            self.hotkeys = HotkeyListener(
                toggle=self.cfg.hotkey.toggle,
                cancel=self.cfg.hotkey.cancel,
                on_toggle=self._on_toggle,
                on_cancel=self._on_cancel,
            )
            self.hotkeys.start()
            log.info("Hotkey backend: %s", self.hotkeys.backend)
            if self._tray:
                self._tray.showMessage(
                    "Whisper",
                    f"{msg}\n{self.cfg.hotkey.toggle} to dictate",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
        except Exception as exc:
            log.exception("Hotkey setup failed")
            self.bridge.error.emit(str(exc))

    def _setup_tray(self, tooltip: str) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray not available")
            return
        if self._tray is None:
            icon = self._make_icon()
            self._tray = QSystemTrayIcon(icon, self.qt_app)
            menu = QMenu()
            quit_action = QAction("Quit", menu)
            quit_action.triggered.connect(self.qt_app.quit)
            menu.addAction(quit_action)
            self._tray.setContextMenu(menu)
            self._tray.setIcon(icon)
            self._tray.show()
        self._tray.setToolTip(f"Whisper — {tooltip}")

    def _make_icon(self) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(220, 50, 47))
        p.setPen(QColor(40, 40, 42))
        p.drawEllipse(8, 8, 48, 48)
        p.end()
        return QIcon(pm)

    def _on_toggle(self) -> None:
        # Called from hotkey thread — keep short, hop to Qt if needed
        with self._lock:
            if self.state == State.IDLE:
                self._start_recording_locked()
            elif self.state == State.RECORDING:
                self._stop_and_transcribe_locked()
            else:
                log.info("Ignoring toggle while processing")

    def _on_cancel(self) -> None:
        with self._lock:
            if self.state == State.RECORDING:
                log.info("Cancel recording")
                self.recorder.cancel()
                self.state = State.IDLE
                self.bridge.hide_overlay.emit()
            # processing: cannot cancel mid-inference easily; ignore

    def _start_recording_locked(self) -> None:
        if self.engine.model is None:
            log.warning("Model not ready yet")
            return
        try:
            self.recorder.start()
        except Exception as exc:
            log.exception("Mic failed")
            self.bridge.error.emit(f"Microphone error: {exc}")
            return
        self.state = State.RECORDING
        self.bridge.show_recording.emit()

    def _stop_and_transcribe_locked(self) -> None:
        audio = self.recorder.stop()
        self.state = State.PROCESSING
        self.bridge.show_processing.emit()
        threading.Thread(
            target=self._transcribe_worker,
            args=(audio,),
            name="asr-infer",
            daemon=True,
        ).start()

    def _transcribe_worker(self, audio) -> None:
        try:
            if audio is None or len(audio) < int(self.cfg.audio.sample_rate * 0.15):
                log.info("Audio too short; skipping")
                self.bridge.hide_overlay.emit()
                with self._lock:
                    self.state = State.IDLE
                return
            text = self.engine.transcribe(audio, self.cfg.audio.sample_rate)
            log.info("Transcription: %s", text[:200] if text else "<empty>")
            self.bridge.hide_overlay.emit()
            if text:
                self.bridge.paste.emit(text)
        except Exception as exc:
            log.exception("Transcription failed")
            self.bridge.error.emit(f"Transcription failed: {exc}")
            self.bridge.hide_overlay.emit()
        finally:
            with self._lock:
                self.state = State.IDLE

    @Slot(str)
    def _do_paste(self, text: str) -> None:
        try:
            paste_text(text, delay_ms=self.cfg.paste.delay_ms)
        except Exception as exc:
            log.exception("Paste failed")
            self.bridge.error.emit(f"Paste failed: {exc}")

    @Slot(str)
    def _on_error(self, message: str) -> None:
        log.error("%s", message)
        if self._tray:
            self._tray.showMessage("Whisper", message, QSystemTrayIcon.MessageIcon.Critical, 6000)
