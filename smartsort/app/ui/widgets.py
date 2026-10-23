"""Reusable UI primitives."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from .theme import Palette, pill_colors


class Card(QFrame):
    """A rounded surface used to group related controls."""

    def __init__(self, parent: QWidget | None = None, *, padding: int = 18, spacing: int = 12):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(spacing)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class StatTile(Card):
    def __init__(self, caption: str, value: str = "0", parent: QWidget | None = None):
        super().__init__(parent, padding=16, spacing=4)
        self._value = QLabel(value)
        self._value.setObjectName("statValue")
        self._caption = QLabel(caption)
        self._caption.setObjectName("statCaption")
        self._caption.setWordWrap(True)
        self._layout.addWidget(self._value)
        self._layout.addWidget(self._caption)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_caption(self, caption: str) -> None:
        self._caption.setText(caption)


class SectionTitle(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("sectionTitle")


class MutedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("muted")
        self.setWordWrap(True)


class Pill(QLabel):
    """Small rounded status label."""

    def __init__(
        self,
        text: str = "",
        status: str = "skipped",
        parent: QWidget | None = None,
        *,
        palette: Palette | None = None,
    ):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._status = status
        self.set_status(status, text, palette)

    def set_status(self, status: str, text: str | None = None, palette: Palette | None = None) -> None:
        self._status = status
        if text is not None:
            self.setText(text)
        fg, bg = pill_colors(status, palette) if palette else ("#5b6472", "#eef0f3")
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:9px;"
            "padding:2px 10px; font-size:8.5pt; font-weight:600;"
        )


class ToggleSwitch(QAbstractButton):
    """A painted iOS-style switch (QCheckBox indicators cannot animate)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._offset = 0.0
        self._on_color = QColor("#2563eb")
        self._off_color = QColor("#c9ced6")
        self._knob_color = QColor("#ffffff")
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.toggled.connect(self._animate)

    # -- palette -----------------------------------------------------------
    def apply_palette(self, palette: Palette) -> None:
        self._on_color = QColor(palette.accent)
        self._off_color = QColor("#3a4150" if palette.is_dark else "#c9ced6")
        self._knob_color = QColor("#ffffff" if not palette.is_dark else "#e8eaee")
        self.update()

    # -- animation ---------------------------------------------------------
    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt naming
        # Move the knob first so the toggled handler starts its animation from
        # the final position (programmatic changes should not animate).
        self._offset = 1.0 if checked else 0.0
        super().setChecked(checked)
        self.update()

    # -- geometry ----------------------------------------------------------
    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, 24)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = self.width()
        height = self.height()
        track = QRectF(1, 1, width - 2, height - 2)

        color = QColor(self._off_color)
        if self._offset > 0:
            ratio = self._offset
            color = QColor(
                int(self._off_color.red() + (self._on_color.red() - self._off_color.red()) * ratio),
                int(self._off_color.green() + (self._on_color.green() - self._off_color.green()) * ratio),
                int(self._off_color.blue() + (self._on_color.blue() - self._off_color.blue()) * ratio),
            )
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, (height - 2) / 2, (height - 2) / 2)

        knob_diameter = height - 8
        travel = width - knob_diameter - 8
        x = 4 + travel * self._offset
        painter.setBrush(self._knob_color)
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        painter.drawEllipse(QRectF(x, 4, knob_diameter, knob_diameter))
        painter.end()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)


class SwitchRow(QWidget):
    """A labelled toggle with an explanatory subtitle."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        checked: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self._title = QLabel(title)
        self._title.setObjectName("sectionTitle")
        self._title.setWordWrap(True)
        text_column.addWidget(self._title)
        self._subtitle = MutedLabel(subtitle)
        if subtitle:
            text_column.addWidget(self._subtitle)
        layout.addLayout(text_column, 1)

        self.switch = ToggleSwitch()
        self.switch.setChecked(checked)
        self.switch.toggled.connect(self.toggled.emit)
        layout.addWidget(self.switch, 0, Qt.AlignVCenter)

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, value: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(value)
        self.switch.blockSignals(False)

    def apply_palette(self, palette: Palette) -> None:
        self.switch.apply_palette(palette)


def horizontal_line(palette: Palette) -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background:{palette.border}; border:none;")
    return line


def title_block(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    label = QLabel(title)
    label.setObjectName("pageTitle")
    layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("pageSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return container


def bold(label: QLabel, size: float | None = None, weight: int = QFont.DemiBold) -> QLabel:
    font = label.font()
    font.setWeight(weight)
    if size is not None:
        font.setPointSizeF(size)
    label.setFont(font)
    return label


def format_bytes(count: int) -> str:
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def status_text(status: str) -> str:
    return t(f"status.{status}") if status else ""
