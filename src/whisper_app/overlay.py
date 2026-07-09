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

# Dark palette — low contrast chrome, soft accent
_BG = QColor(18, 18, 22, 235)
_BG_IDLE = QColor(22, 22, 28, 220)
_BORDER = QColor(255, 255, 255, 22)
_BORDER_ACTIVE = QColor(255, 255, 255, 36)
_TEXT = QColor(232, 232, 237)
_MUTED = QColor(130, 130, 142)
_WAVE = QColor(220, 220, 230, 210)
_WAVE_SOFT = QColor(160, 160, 175, 140)
_ACCENT = QColor(255, 82, 82)  # soft record red
_ACCENT_GLOW = QColor(255, 82, 82, 55)
_PROCESS = QColor(140, 160, 255)


class OverlayWindow(QWidget):
    """Always-on-top frameless pill: tiny idle dot ↔ expanded recording UI."""

    cancel_clicked = Signal()
    stop_clicked = Signal()

    # Layout sizes (content + soft margin for shadow)
    _IDLE_W, _IDLE_H = 44, 44
    _ACTIVE_W, _ACTIVE_H = 360, 72
    _MARGIN = 10

    def __init__(self, show_waveform: bool = True) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.show_waveform = show_waveform
        self._mode = "idle"  # idle | recording | processing
        self._levels: deque[float] = deque([0.0] * 56, maxlen=56)
        self._smooth: deque[float] = deque([0.04] * 56, maxlen=56)
        self._phase = 0.0
        self._hotkey_label = "Ctrl+Space"
        self._font = self._pick_font()

        # animated size (lerp toward target)
        self._cur_w = float(self._IDLE_W + self._MARGIN * 2)
        self._cur_h = float(self._IDLE_H + self._MARGIN * 2)
        self._target_w = self._cur_w
        self._target_h = self._cur_h
        self._anchor: QPoint | None = None  # center of pill in screen coords
        self._drag_offset: QPoint | None = None
        self._user_moved = False

        self.resize(int(self._cur_w), int(self._cur_h))

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60fps for smooth waves/resize
        self._timer.timeout.connect(self._tick)

    # ── public API ──────────────────────────────────────────────

    def set_hotkey_label(self, label: str) -> None:
        parts = []
        for p in label.replace("-", "+").split("+"):
            p = p.strip()
            if not p:
                continue
            if p.lower() in ("ctrl", "control"):
                parts.append("Ctrl")
            elif p.lower() == "space":
                parts.append("Space")
            elif p.lower() in ("esc", "escape"):
                parts.append("Esc")
            else:
                parts.append(p[:1].upper() + p[1:].lower())
        self._hotkey_label = "+".join(parts)
        self.update()

    def set_level(self, level: float) -> None:
        raw = max(0.0, min(1.0, float(level)))
        self._levels.append(raw)

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
        """Back-compat: return to idle mini indicator (never fully hide)."""
        self.show_idle()

    # ── interaction ─────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            top_left = event.globalPosition().toPoint() - self._drag_offset
            self.move(top_left)
            self._anchor = self._center_from_geometry()
            self._user_moved = True
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()

    # ── internals ───────────────────────────────────────────────

    def _pick_font(self) -> QFont:
        preferred = [
            "Inter",
            "SF Pro Text",
            "Segoe UI",
            "Noto Sans",
            "Ubuntu",
            "Cantarell",
            "DejaVu Sans",
        ]
        available = set(QFontDatabase.families())
        for name in preferred:
            if name in available:
                f = QFont(name)
                f.setStyleHint(QFont.StyleHint.SansSerif)
                f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
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
        # bottom-center-ish, a bit above the edge
        cx = geo.x() + geo.width() // 2
        cy = geo.y() + geo.height() - 56
        self._anchor = QPoint(cx, cy)
        self._apply_anchor()

    def _center_from_geometry(self) -> QPoint:
        g = self.frameGeometry()
        return QPoint(g.x() + g.width() // 2, g.y() + g.height() // 2)

    def _apply_anchor(self) -> None:
        if self._anchor is None:
            return
        x = self._anchor.x() - int(self._cur_w) // 2
        y = self._anchor.y() - int(self._cur_h) // 2
        self.move(x, y)

    def _tick(self) -> None:
        self._phase += 0.07

        # smooth size lerp (snappy ease)
        aw = self._target_w - self._cur_w
        ah = self._target_h - self._cur_h
        if abs(aw) > 0.3 or abs(ah) > 0.3:
            self._cur_w += aw * 0.22
            self._cur_h += ah * 0.22
            # keep center fixed while resizing
            if self._anchor is None:
                self._anchor = self._center_from_geometry()
            self.resize(max(1, int(round(self._cur_w))), max(1, int(round(self._cur_h))))
            self._apply_anchor()

        # smooth waveform levels (EMA)
        raw = list(self._levels)
        if self._mode == "processing":
            # soft breathing wave
            for i in range(len(raw)):
                raw[i] = 0.18 + 0.22 * (0.5 + 0.5 * math.sin(self._phase * 1.4 + i * 0.22))
        elif self._mode == "idle":
            raw = [0.0] * len(raw)
        elif self._mode == "recording" and (not raw or max(raw) < 0.04):
            # gentle resting pulse while silent
            for i in range(len(raw)):
                raw[i] = 0.05 + 0.03 * (0.5 + 0.5 * math.sin(self._phase + i * 0.18))

        smooth = list(self._smooth)
        alpha = 0.28
        for i, r in enumerate(raw):
            if i < len(smooth):
                smooth[i] = smooth[i] * (1 - alpha) + r * alpha
            else:
                smooth.append(r)
        # light spatial blur for creamier bars
        blurred = smooth[:]
        for i in range(1, len(smooth) - 1):
            blurred[i] = smooth[i - 1] * 0.2 + smooth[i] * 0.6 + smooth[i + 1] * 0.2
        self._smooth = deque(blurred, maxlen=self._smooth.maxlen)

        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        m = self._MARGIN
        rect = QRectF(m, m, self.width() - m * 2, self.height() - m * 2)
        if rect.width() < 4 or rect.height() < 4:
            return

        # soft drop shadow
        shadow = QPainterPath()
        shadow.addRoundedRect(rect.translated(0, 2), rect.height() / 2, rect.height() / 2)
        painter.fillPath(shadow, QColor(0, 0, 0, 70))

        # body
        path = QPainterPath()
        radius = rect.height() / 2.0
        path.addRoundedRect(rect, radius, radius)
        bg = _BG if self._mode != "idle" else _BG_IDLE
        painter.fillPath(path, bg)
        painter.setPen(QPen(_BORDER_ACTIVE if self._mode != "idle" else _BORDER, 1.0))
        painter.drawPath(path)

        # While expanding/collapsing, only draw full chrome once wide enough
        expanded_enough = rect.width() > (self._IDLE_W + self._ACTIVE_W) * 0.35
        if self._mode == "idle" or not expanded_enough:
            self._paint_idle(painter, rect)
            if self._mode != "idle" and expanded_enough is False:
                # accent pulse while growing into active state
                cx, cy = rect.center().x(), rect.center().y()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_ACCENT if self._mode == "recording" else _PROCESS)
                painter.drawEllipse(QPoint(int(cx), int(cy)), 3, 3)
        else:
            self._paint_active(painter, rect)

    def _paint_idle(self, painter: QPainter, rect: QRectF) -> None:
        # subtle outer ring + soft center glow + accent core
        cx = rect.center().x()
        cy = rect.center().y()

        # breathing glow
        breath = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase * 0.9))
        glow_r = 9 + 2 * breath
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, int(12 + 10 * breath)))
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(glow_r + 4), int(glow_r + 4))

        painter.setBrush(QColor(255, 255, 255, 28))
        painter.drawEllipse(QPoint(int(cx), int(cy)), 7, 7)

        # tiny ready dot
        painter.setBrush(QColor(255, 255, 255, int(160 + 60 * breath)))
        painter.drawEllipse(QPoint(int(cx), int(cy)), 3, 3)

    def _paint_active(self, painter: QPainter, rect: QRectF) -> None:
        # left status chip
        pad = 14.0
        chip_x = rect.left() + pad
        mid_y = rect.center().y()

        if self._mode == "recording":
            # soft glow under record dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_ACCENT_GLOW)
            painter.drawEllipse(QPoint(int(chip_x + 5), int(mid_y)), 9, 9)
            # pulse scale
            pulse = 1.0 + 0.12 * (0.5 + 0.5 * math.sin(self._phase * 2.2))
            r = 4.2 * pulse
            painter.setBrush(_ACCENT)
            painter.drawEllipse(QPoint(int(chip_x + 5), int(mid_y)), int(r), int(r))
            label = "Listening"
            accent = _TEXT
        else:
            # processing spinner arc
            painter.setPen(QPen(_PROCESS, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            start = int((self._phase * 55) % 360) * 16
            painter.drawArc(int(chip_x - 2), int(mid_y - 7), 14, 14, start, 220 * 16)
            label = "Transcribing"
            accent = _TEXT

        font = QFont(self._font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
        painter.setFont(font)
        painter.setPen(accent)
        text_x = chip_x + 18
        metrics = painter.fontMetrics()
        painter.drawText(
            int(text_x),
            int(mid_y + metrics.ascent() / 2 - 1),
            label,
        )
        label_w = metrics.horizontalAdvance(label)

        # right-side hint (minimal)
        hint_font = QFont(self._font)
        hint_font.setPixelSize(11)
        hint_font.setWeight(QFont.Weight.Normal)
        painter.setFont(hint_font)
        painter.setPen(_MUTED)
        if self._mode == "recording":
            hint = self._hotkey_label
        else:
            hint = "…"
        hint_w = painter.fontMetrics().horizontalAdvance(hint)
        hint_x = rect.right() - pad - hint_w
        painter.drawText(
            int(hint_x),
            int(mid_y + painter.fontMetrics().ascent() / 2 - 1),
            hint,
        )

        # waveform between label and hint
        if not self.show_waveform:
            return

        wave_left = text_x + label_w + 16
        wave_right = hint_x - 16
        if wave_right - wave_left < 40:
            return

        wave_top = rect.top() + 16
        wave_bottom = rect.bottom() - 16
        mid = (wave_top + wave_bottom) / 2.0
        max_h = (wave_bottom - wave_top) / 2.0 * 0.92

        levels = list(self._smooth)
        n = len(levels)
        if n == 0:
            return

        # fewer visual bars, wider + softer
        step = max(1, n // 36)
        samples = levels[::step] or levels
        count = len(samples)
        gap = 2.6
        total_gap = gap * (count - 1)
        bar_w = max(2.4, (wave_right - wave_left - total_gap) / count)

        # gradient along wave (subtle depth)
        grad = QLinearGradient(wave_left, 0, wave_right, 0)
        grad.setColorAt(0.0, QColor(_WAVE_SOFT))
        grad.setColorAt(0.5, QColor(_WAVE))
        grad.setColorAt(1.0, QColor(_WAVE_SOFT))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)

        x = wave_left
        for i, lv in enumerate(samples):
            # floor so silence still reads as a calm line
            amp = max(0.08, min(1.0, lv))
            h = max(3.0, amp * max_h * 2.0)
            # slight vertical breathing on low energy for life
            if amp < 0.2:
                h += 1.2 * math.sin(self._phase * 1.1 + i * 0.4)
            rr = min(bar_w / 2.0, 3.0)
            painter.drawRoundedRect(
                QRectF(x, mid - h / 2, bar_w, h),
                rr,
                rr,
            )
            x += bar_w + gap
