"""
EchoCap programmatic icon drawn with QPainter.
Bold geometric 'E' letterform on a teal rounded square.
Clean, professional, readable at all tray-icon sizes.
Generates .ico on first run.
"""

import logging
import os
import struct

from PyQt6.QtCore import Qt, QRectF, QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath, QIcon,
    QLinearGradient,
)

from paths import ICO_PATH

logger = logging.getLogger(__name__)

ICON_SIZES = [16, 24, 32, 48, 64, 256]

BG_TOP = QColor("#06B6D4")
BG_BOT = QColor("#0E7490")
FG = QColor("#F0FDFA")


def _build_E_path(s):
    """Build a QPainterPath for a bold geometric 'E' fitting inside an s×s square.

    The letter is constructed from a thick vertical stem + three horizontal bars.
    All strokes use rounded joins/caps for a friendly, modern look.
    """
    pad = s * 0.26           # padding from edges
    stem_w = s * 0.14        # width of vertical stem
    bar_h = s * 0.13         # height of each horizontal bar
    gap = s * 0.08           # gap between bars

    left = pad
    bar_right = s - pad
    top_bar_y = pad
    mid_bar_y = s / 2.0 - bar_h / 2.0
    bot_bar_y = s - pad - bar_h

    path = QPainterPath()

    # Vertical stem
    path.addRoundedRect(QRectF(left, pad, stem_w, s - pad * 2), stem_w * 0.35, stem_w * 0.35)

    # Top bar
    path.addRoundedRect(QRectF(left, top_bar_y, bar_right - left, bar_h), bar_h * 0.35, bar_h * 0.35)

    # Middle bar (slightly shorter for style)
    mid_right = bar_right - s * 0.06
    path.addRoundedRect(QRectF(left, mid_bar_y, mid_right - left, bar_h), bar_h * 0.35, bar_h * 0.35)

    # Bottom bar
    path.addRoundedRect(QRectF(left, bot_bar_y, bar_right - left, bar_h), bar_h * 0.35, bar_h * 0.35)

    return path.simplified()


def _draw_echo_pixmap(size):
    """Draw EchoCap icon: teal rounded-square + white geometric 'E'."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # --- Background ---
    corner_r = s * 0.22
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0.0, BG_TOP)
    grad.setColorAt(1.0, BG_BOT)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(0, 0, s, s), corner_r, corner_r)

    # --- Foreground geometric E ---
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(FG))
    path = _build_E_path(s)
    p.drawPath(path)

    p.end()
    return pm


def _write_ico(pixmaps_dict, path):
    """Write an .ico file from {size: QPixmap} using PNG encoding."""
    entries = []
    png_blobs = []
    offset = 6 + 16 * len(pixmaps_dict)

    for size, pm in pixmaps_dict.items():
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pm.save(buf, "PNG")
        buf.close()
        data = ba.data()
        png_blobs.append(data)
        w = size if size < 256 else 0
        h = size if size < 256 else 0
        entries.append(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32,
                                   len(data), offset))
        offset += len(data)

    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(pixmaps_dict)))
        for e in entries:
            f.write(e)
        for blob in png_blobs:
            f.write(blob)


def get_app_icon():
    """Return a QIcon. Generate .ico on disk on first call if missing."""
    if not os.path.exists(ICO_PATH):
        logger.info("Generating app icon...")
        pixmaps = {sz: _draw_echo_pixmap(sz) for sz in ICON_SIZES}
        _write_ico(pixmaps, ICO_PATH)
    return QIcon(ICO_PATH)


def get_tray_icon():
    """Return a QIcon suitable for the system tray (64px pixmap)."""
    return QIcon(_draw_echo_pixmap(64))
