"""Floating pill overlay inspired by Superwhisper-style recording UI."""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class OverlayWindow(QWidget):
    """Always-on-top frameless pill with waveform + status."""

    cancel_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, show_waveform: bool = True) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.show_waveform = show_waveform
        self._mode = "hidden"  # hidden | recording | processing
        self._levels: deque[float] = deque([0.05] * 48, maxlen=48)
        self._phase = 0.0
        self._hotkey_label = "Ctrl+Space"

        self._width = 520
        self._height = 120
        self.resize(self._width, self._height)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_hotkey_label(self, label: str) -> None:
        self._hotkey_label = label.replace("+", "+").title().replace("Ctrl", "Ctrl").replace("Space", "Space")
        # nicer: ctrl+space -> Ctrl+Space
        parts = [p.capitalize() if p.lower() != "ctrl" else "Ctrl" for p in label.replace("-", "+").split("+")]
        self._hotkey_label = "+".join(parts)
        self.update()

    def set_level(self, level: float) -> None:
        self._levels.append(max(0.02, min(1.0, float(level))))

    def show_recording(self) -> None:
        self._mode = "recording"
        self._position_bottom_center()
        self.show()
        self.raise_()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_processing(self) -> None:
        self._mode = "processing"
        self._position_bottom_center()
        self.show()
        self.raise_()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def hide_overlay(self) -> None:
        self._mode = "hidden"
        self._timer.stop()
        self.hide()

    def _position_bottom_center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self._width) // 2
        y = geo.y() + geo.height() - self._height - 48
        self.move(QPoint(x, y))

    def _tick(self) -> None:
        self._phase += 0.18
        if self._mode == "processing":
            # synthetic pulse while waiting for ASR
            t = self._phase
            level = 0.25 + 0.2 * (0.5 + 0.5 * math.sin(t))
            self._levels.append(level)
        elif self._mode == "recording" and max(self._levels) < 0.08:
            # gentle idle animation when silence
            t = self._phase
            self._levels.append(0.04 + 0.03 * (0.5 + 0.5 * math.sin(t + len(self._levels))))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._mode == "hidden":
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        margin = 8
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        radius = rect.height() / 2.0

        # Shadow-ish soft fill
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(245, 245, 247, 235))
        painter.setPen(QPen(QColor(0, 0, 0, 28), 1.0))
        painter.drawPath(path)

        # Waveform area
        wave_top = rect.top() + 14
        wave_bottom = rect.bottom() - 42
        wave_left = rect.left() + 36
        wave_right = rect.right() - 36
        mid_y = (wave_top + wave_bottom) / 2.0
        max_h = (wave_bottom - wave_top) / 2.0

        if self.show_waveform:
            levels = list(self._levels)
            n = len(levels)
            if n > 0:
                gap = 3.0
                total_gap = gap * (n - 1)
                bar_w = max(2.0, (wave_right - wave_left - total_gap) / n)
                color = QColor(55, 55, 58, 210) if self._mode == "recording" else QColor(90, 90, 100, 180)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                x = wave_left
                for i, lv in enumerate(levels):
                    # slight spatial wave for processing
                    amp = lv
                    if self._mode == "processing":
                        amp = 0.15 + 0.55 * abs(math.sin(self._phase + i * 0.35))
                    h = max(3.0, amp * max_h * 2.0)
                    painter.drawRoundedRect(
                        int(x),
                        int(mid_y - h / 2),
                        int(bar_w),
                        int(h),
                        1.5,
                        1.5,
                    )
                    x += bar_w + gap

        # Footer: recording indicator + hints
        footer_y = rect.bottom() - 28
        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)

        # Red record dot / spinner
        dot_x = rect.left() + 28
        dot_y = footer_y + 8
        if self._mode == "recording":
            painter.setBrush(QColor(220, 50, 47))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(int(dot_x), int(dot_y)), 6, 6)
            painter.setPen(QColor(40, 40, 42))
            painter.drawText(int(dot_x + 14), int(footer_y + 13), "Recording")
        else:
            # processing: animated arc
            painter.setPen(QPen(QColor(80, 80, 90), 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            start = int((self._phase * 40) % 360) * 16
            painter.drawArc(int(dot_x - 7), int(dot_y - 7), 14, 14, start, 270 * 16)
            painter.setPen(QColor(40, 40, 42))
            painter.drawText(int(dot_x + 14), int(footer_y + 13), "Transcribing…")

        # Right-side hints
        painter.setPen(QColor(110, 110, 115))
        font.setWeight(QFont.Weight.Normal)
        font.setPointSize(10)
        painter.setFont(font)
        right = f"Stop  {self._hotkey_label}    Cancel  Esc"
        if self._mode == "processing":
            right = "Please wait…"
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(right)
        painter.drawText(int(rect.right() - tw - 24), int(footer_y + 13), right)
