"""Programmatic app icon (no binary assets required at import time)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

_ACCENT_TOP = QColor("#3b82f6")
_ACCENT_BOTTOM = QColor("#1d4ed8")


def _draw(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    radius = size * 0.24
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, _ACCENT_TOP)
    gradient.setColorAt(1.0, _ACCENT_BOTTOM)

    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.fillPath(path, QBrush(gradient))

    # Folder glyph
    margin = size * 0.20
    folder_w = size - margin * 2
    folder_h = folder_w * 0.72
    top = (size - folder_h) / 2 + size * 0.04
    tab_w = folder_w * 0.42
    tab_h = folder_h * 0.18

    glyph = QPainterPath()
    glyph.moveTo(margin, top + tab_h)
    glyph.lineTo(margin + tab_w * 0.55, top + tab_h)
    glyph.lineTo(margin + tab_w, top)
    glyph.lineTo(margin + folder_w, top)
    glyph.lineTo(margin + folder_w, top + folder_h)
    glyph.lineTo(margin, top + folder_h)
    glyph.closeSubpath()
    painter.fillPath(glyph, QBrush(QColor("#ffffff")))

    # Sorting arrow inside the folder
    arrow = QPainterPath()
    cx = margin + folder_w * 0.5
    cy = top + folder_h * 0.58
    w = folder_w * 0.22
    h = folder_h * 0.34
    arrow.moveTo(cx - w, cy - h * 0.55)
    arrow.lineTo(cx + w, cy - h * 0.55)
    arrow.lineTo(cx + w, cy + h * 0.1)
    arrow.lineTo(cx + w * 1.9, cy + h * 0.1)
    arrow.lineTo(cx, cy + h * 0.75)
    arrow.lineTo(cx - w * 1.9, cy + h * 0.1)
    arrow.lineTo(cx - w, cy + h * 0.1)
    arrow.closeSubpath()
    painter.setPen(QPen(QColor(_ACCENT_BOTTOM), max(1.0, size * 0.012)))
    painter.fillPath(arrow, QBrush(_ACCENT_BOTTOM))

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_draw(size))
    return icon


def tray_pixmap(size: int = 64) -> QPixmap:
    return _draw(size)
