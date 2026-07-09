"""Modern dark floating pill — always visible, draggable, expands while active."""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Dark palette
_BG = QColor(20, 20, 24, 242)
_BG_IDLE = QColor(24, 24, 30, 235)
_BORDER = QColor(255, 255, 255, 28)
_BORDER_ACTIVE = QColor(255, 255, 255, 40)
_TEXT = QColor(236, 236, 240)
_MUTED = QColor(120, 120, 132)
_WAVE = QColor(230, 230, 238, 220)
_WAVE_DIM = QColor(150, 150, 165, 150)
_ACCENT = QColor(255, 90, 90)
_ACCENT_SOFT = QColor(255, 90, 90, 70)
_PROCESS = QColor(150, 170, 255)


class OverlayWindow(QWidget):
    """Always-on-top frameless pill: mini idle pill ↔ expanded recording UI."""

    cancel_clicked = Signal()
    stop_clicked = Signal()

    # Content sizes (window adds margin for soft shadow)
    _IDLE_W, _IDLE_H = 72, 28
    _ACTIVE_W, _ACTIVE_H = 380, 68
    _MARGIN = 12

    def __init__(self, show_waveform: bool = True) -> None:
        # Framed as a normal always-on-top window (Tool flag breaks mouse drag on some Wayland setups).
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.show_waveform = show_waveform
        self._mode = "idle"  # idle | recording | processing
        # Rolling history drawn left→right (oldest→newest). No heavy EMA on the buffer.
        self._levels: deque[float] = deque([0.06] * 48, maxlen=48)
        # Single live envelope (fast attack / medium release) drives new samples
        self._envelope = 0.0
        self._phase = 0.0
        self._hotkey_label = "Ctrl+Space"
        self._font = self._pick_font()

        self._cur_w = float(self._IDLE_W + self._MARGIN * 2)
        self._cur_h = float(self._IDLE_H + self._MARGIN * 2)
        self._target_w = self._cur_w
        self._target_h = self._cur_h
        self._anchor: QPoint | None = None
        self._dragging = False
        self._drag_offset = QPoint()
        self._user_moved = False
        self._use_system_move = False

        self.setFixedSize(int(self._cur_w), int(self._cur_h))

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ── public API ──────────────────────────────────────────────

    def set_hotkey_label(self, label: str) -> None:
        parts = []
        for p in label.replace("-", "+").split("+"):
            p = p.strip()
            if not p:
                continue
            low = p.lower()
            if low in ("ctrl", "control"):
                parts.append("Ctrl")
            elif low == "space":
                parts.append("Space")
            elif low in ("esc", "escape"):
                parts.append("Esc")
            else:
                parts.append(p[:1].upper() + p[1:].lower())
        self._hotkey_label = "+".join(parts)
        self.update()

    def set_level(self, level: float) -> None:
        """Update live envelope only (called from audio thread via signal).

        History is sampled in `_tick` at display rate so the wave stays in
        lockstep with the UI — no delayed queue of old samples.
        """
        raw = max(0.0, min(1.0, float(level)))
        # Fast attack / medium-short release
        if raw >= self._envelope:
            self._envelope = self._envelope * 0.15 + raw * 0.85
        else:
            self._envelope = self._envelope * 0.78 + raw * 0.22

    def show_idle(self) -> None:
        self._mode = "idle"
        self._set_target_size(self._IDLE_W, self._IDLE_H)
        self._ensure_visible()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_recording(self) -> None:
        self._mode = "recording"
        self._set_target_size(self._ACTIVE_W, self._ACTIVE_H)
        self._ensure_visible()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_processing(self) -> None:
        self._mode = "processing"
        self._set_target_size(self._ACTIVE_W, self._ACTIVE_H)
        self._ensure_visible()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def hide_overlay(self) -> None:
        self.show_idle()

    # ── interaction (Wayland-safe drag) ─────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Prefer compositor-native move (works on Wayland/KDE)
        handle = self.windowHandle()
        if handle is not None:
            try:
                self._use_system_move = bool(handle.startSystemMove())
            except Exception:
                self._use_system_move = False
        else:
            self._use_system_move = False

        if not self._use_system_move:
            # Manual fallback (X11 / if system move unavailable)
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

        self._user_moved = True
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging and not self._use_system_move:
            if event.buttons() & Qt.MouseButton.LeftButton:
                top_left = event.globalPosition().toPoint() - self._drag_offset
                self.move(top_left)
                self._anchor = self._center_from_geometry()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging or self._use_system_move:
                self._anchor = self._center_from_geometry()
                self._user_moved = True
            self._dragging = False
            self._use_system_move = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        # Keep anchor in sync when compositor moves the window (system drag)
        if self._dragging or self._use_system_move or self._user_moved:
            self._anchor = self._center_from_geometry()
        super().moveEvent(event)

    # ── internals ───────────────────────────────────────────────

    def _pick_font(self) -> QFont:
        preferred = ["Inter", "SF Pro Text", "Segoe UI", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans"]
        available = set(QFontDatabase.families())
        for name in preferred:
            if name in available:
                f = QFont(name)
                f.setStyleHint(QFont.StyleHint.SansSerif)
                return f
        f = QFont()
        f.setStyleHint(QFont.StyleHint.SansSerif)
        return f

    def _set_target_size(self, content_w: int, content_h: int) -> None:
        self._target_w = float(content_w + self._MARGIN * 2)
        self._target_h = float(content_h + self._MARGIN * 2)

    def _ensure_visible(self) -> None:
        if not self.isVisible():
            if self._anchor is None and not self._user_moved:
                self._place_default()
            else:
                self._apply_anchor()
            self.show()
        self.raise_()

    def _place_default(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self._anchor = QPoint(geo.x() + geo.width() // 2, geo.y() + geo.height() - 64)
        self._apply_anchor()

    def _center_from_geometry(self) -> QPoint:
        g = self.frameGeometry()
        return QPoint(g.x() + g.width() // 2, g.y() + g.height() // 2)

    def _apply_anchor(self) -> None:
        if self._anchor is None or self._dragging:
            return
        x = self._anchor.x() - int(self._cur_w) // 2
        y = self._anchor.y() - int(self._cur_h) // 2
        self.move(x, y)

    def _tick(self) -> None:
        self._phase += 0.07

        # Size animation — skip re-anchoring while user is dragging
        aw = self._target_w - self._cur_w
        ah = self._target_h - self._cur_h
        if abs(aw) > 0.4 or abs(ah) > 0.4:
            self._cur_w += aw * 0.28
            self._cur_h += ah * 0.28
            if self._anchor is None:
                self._anchor = self._center_from_geometry()
            self.setFixedSize(max(1, int(round(self._cur_w))), max(1, int(round(self._cur_h))))
            if not self._dragging and not self._use_system_move:
                self._apply_anchor()

        # While recording, if mic is quiet for a moment, keep a tiny resting pulse
        # (only inject when envelope already low — never lags real speech).
        if self._mode == "recording" and self._envelope < 0.04:
            idle = 0.045 + 0.02 * (0.5 + 0.5 * math.sin(self._phase * 1.2))
            self._envelope *= 0.9
            self._levels.append(idle)
        elif self._mode == "processing":
            # synthetic soft wave while ASR runs
            n = self._levels.maxlen or 48
            t = self._phase
            self._levels = deque(
                (
                    0.14 + 0.16 * (0.5 + 0.5 * math.sin(t * 1.3 + i * 0.28))
                    for i in range(n)
                ),
                maxlen=n,
            )
        elif self._mode == "idle":
            self._envelope = 0.0

        self.update()

    def _content_rect(self) -> QRectF:
        m = self._MARGIN
        return QRectF(m, m, self.width() - m * 2, self.height() - m * 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = self._content_rect()
        if rect.width() < 8 or rect.height() < 8:
            return

        radius = rect.height() / 2.0

        # shadow
        shadow = QPainterPath()
        shadow.addRoundedRect(rect.translated(0, 1.5), radius, radius)
        painter.fillPath(shadow, QColor(0, 0, 0, 80))

        # body pill
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        painter.fillPath(body, _BG if self._mode != "idle" else _BG_IDLE)
        painter.setPen(QPen(_BORDER_ACTIVE if self._mode != "idle" else _BORDER, 1.0))
        painter.drawPath(body)

        # Clip ALL content to pill so nothing spills out
        painter.setClipPath(body)

        # Expanded only when wide enough for the full layout
        ready = rect.width() >= self._ACTIVE_W * 0.72
        if self._mode == "idle" or not ready:
            self._paint_idle(painter, rect)
        else:
            self._paint_active(painter, rect)

    def _paint_idle(self, painter: QPainter, rect: QRectF) -> None:
        """Mini horizontal pill: soft bar + status dot — not a circle."""
        cy = rect.center().y()
        # left status dot
        breath = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase * 0.85))
        dot_x = rect.left() + 14
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, int(28 + 20 * breath)))
        painter.drawEllipse(QPoint(int(dot_x), int(cy)), 5, 5)
        painter.setBrush(QColor(255, 255, 255, int(170 + 50 * breath)))
        painter.drawEllipse(QPoint(int(dot_x), int(cy)), 2, 2)

        # quiet mini waveform ticks (decorative idle life)
        left = dot_x + 12
        right = rect.right() - 12
        if right - left < 16:
            return
        mid = cy
        bars = 9
        gap = 2.5
        bar_w = max(2.0, (right - left - gap * (bars - 1)) / bars)
        painter.setBrush(QColor(255, 255, 255, int(40 + 25 * breath)))
        x = left
        for i in range(bars):
            h = 3.0 + 4.0 * (0.45 + 0.55 * math.sin(self._phase * 1.1 + i * 0.7))
            h = min(h, rect.height() - 10)
            painter.drawRoundedRect(
                QRectF(x, mid - h / 2, bar_w, h),
                bar_w / 2,
                bar_w / 2,
            )
            x += bar_w + gap

    def _paint_active(self, painter: QPainter, rect: QRectF) -> None:
        """Single clean row: [dot] Label | waveform | hint — all inside padding."""
        pad_x = 16.0
        pad_y = 14.0
        inner = rect.adjusted(pad_x, pad_y, -pad_x, -pad_y)
        if inner.width() < 40 or inner.height() < 10:
            return

        cy = inner.center().y()

        # —— left status ——
        status_x = inner.left()
        if self._mode == "recording":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_ACCENT_SOFT)
            painter.drawEllipse(QPoint(int(status_x + 5), int(cy)), 8, 8)
            pulse = 1.0 + 0.1 * (0.5 + 0.5 * math.sin(self._phase * 2.0))
            r = 3.6 * pulse
            painter.setBrush(_ACCENT)
            painter.drawEllipse(QPoint(int(status_x + 5), int(cy)), int(round(r)), int(round(r)))
            label = "Listening"
        else:
            painter.setPen(QPen(_PROCESS, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            start = int((self._phase * 50) % 360) * 16
            painter.drawArc(int(status_x - 1), int(cy - 6), 12, 12, start, 240 * 16)
            label = "Transcribing"

        font = QFont(self._font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(_TEXT)
        metrics = painter.fontMetrics()
        label_x = status_x + 16
        # vertical center via bounding rect (avoids baseline overflow)
        label_rect = QRectF(
            label_x,
            inner.top(),
            metrics.horizontalAdvance(label) + 2,
            inner.height(),
        )
        painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
        label_right = label_x + metrics.horizontalAdvance(label)

        # —— right hint ——
        hint_font = QFont(self._font)
        hint_font.setPixelSize(11)
        hint_font.setWeight(QFont.Weight.Normal)
        painter.setFont(hint_font)
        painter.setPen(_MUTED)
        hint = self._hotkey_label if self._mode == "recording" else "…"
        h_metrics = painter.fontMetrics()
        hint_w = h_metrics.horizontalAdvance(hint)
        hint_rect = QRectF(inner.right() - hint_w, inner.top(), hint_w, inner.height())
        painter.drawText(hint_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), hint)

        # —— waveform band between label and hint ——
        if not self.show_waveform:
            return

        wave_left = label_right + 14
        wave_right = inner.right() - hint_w - 14
        if wave_right - wave_left < 48:
            return

        # Strict vertical band inside inner rect
        max_half = max(4.0, inner.height() * 0.42)
        mid = cy
        levels = list(self._levels)
        if not levels:
            return

        # Draw history as-is (newest on the right). Light 3-tap blur for
        # cosmetics only — does not delay new samples at the edge.
        n = len(levels)
        display = levels[:]
        if n >= 3:
            display = [levels[0]] + [
                levels[i - 1] * 0.15 + levels[i] * 0.70 + levels[i + 1] * 0.15
                for i in range(1, n - 1)
            ] + [levels[-1]]  # keep newest sample unblurred for instant feel

        target_bars = 32
        step = max(1, len(display) // target_bars)
        samples = display[::step][:target_bars]
        # ensure the last sample is always the freshest level
        if samples and display:
            samples[-1] = display[-1]
        count = len(samples)
        if count == 0:
            return

        gap = 2.0
        bar_w = max(2.0, (wave_right - wave_left - gap * (count - 1)) / count)
        total = count * bar_w + (count - 1) * gap
        if total > (wave_right - wave_left):
            bar_w = max(1.8, (wave_right - wave_left - gap * (count - 1)) / count)

        grad = QLinearGradient(wave_left, 0, wave_right, 0)
        grad.setColorAt(0.0, _WAVE_DIM)
        grad.setColorAt(0.55, _WAVE)
        grad.setColorAt(1.0, _WAVE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)

        x = wave_left
        for lv in samples:
            amp = max(0.08, min(1.0, float(lv)))
            h = max(3.0, amp * max_half * 2.0)
            h = min(h, inner.height() - 2.0)
            rr = min(bar_w * 0.5, 2.5)
            painter.drawRoundedRect(
                QRectF(x, mid - h / 2.0, bar_w, h),
                rr,
                rr,
            )
            x += bar_w + gap
            if x > wave_right:
                break
