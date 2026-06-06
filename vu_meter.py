"""Micro VU meter — real-time microphone level indicator for settings dialog."""
import math
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget


class VUMeterWidget(QWidget):
    """Compact horizontal VU bar. Green = normal, yellow = loud, red = clip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0
        self._peak = 0.0
        self._enabled = True
        self.setFixedHeight(22)
        self.setMinimumWidth(150)

    def set_level(self, fraction):
        self._level = max(0.0, min(1.0, fraction))
        if self._level > self._peak:
            self._peak = self._level
        else:
            self._peak = max(0.0, self._peak - 0.006)
        self.update()

    def set_enabled(self, enabled):
        self._enabled = enabled
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad_x, pad_y = 30, 4
        bar_w, bar_h = w - pad_x - 8, h - pad_y * 2

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(60, 60, 60))
        p.drawRoundedRect(pad_x, pad_y, bar_w, bar_h, 3, 3)

        if not self._enabled:
            p.end()
            return

        if self._level < 0.02:
            colour = QColor(100, 100, 100)
        elif self._level < 0.55:
            t = self._level / 0.55
            colour = QColor(int(50 * t), int(200 + 55 * t), int(80 * t))
        elif self._level < 0.75:
            colour = QColor(255, 200, 0)
        else:
            colour = QColor(240, 50, 50)

        fill_w = int(bar_w * self._level)
        p.setBrush(colour)
        p.drawRoundedRect(pad_x, pad_y, fill_w, bar_h, 3, 3)

        peak_x = pad_x + int(bar_w * self._peak)
        p.setPen(QColor(255, 255, 255, 180))
        p.drawLine(peak_x, pad_y, peak_x, pad_y + bar_h)

        p.setPen(QColor(200, 200, 200))
        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        db = -60.0 if self._level < 0.0001 else 20.0 * math.log10(max(self._level, 0.0001))
        p.drawText(2, 0, pad_x - 4, h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{db:.0f} dB")
        p.end()


class VUMeterPollWorker:
    """Polls pipeline.current_rms and feeds VUMeterWidget."""

    def __init__(self):
        self._timer = None
        self._widget = None
        self._pipeline = None

    def start(self, widget, pipeline):
        self._widget = widget
        self._pipeline = pipeline
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._poll)
        self._timer.start(40)

    def stop(self):
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._widget = None
        self._pipeline = None

    def _poll(self):
        if self._pipeline and self._widget:
            try:
                self._widget.set_level(self._pipeline.current_rms)
            except Exception:
                pass
