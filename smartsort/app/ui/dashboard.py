"""Dashboard: the at-a-glance screen."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from .theme import Palette
from .widgets import Card, MutedLabel, Pill, SectionTitle, StatTile, format_bytes, title_block


class DashboardPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._palette: Palette | None = None
        self._build()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(28, 24, 28, 28)
        self._layout.setSpacing(16)
        # Tell the scroll area how small the page may get. Without this the
        # layout happily compresses the cards below their content when the
        # window is short, and the bottom rows are clipped instead of the page
        # scrolling.
        self._layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)
        scroll.setWidget(container)

        self._layout.addWidget(title_block(t("dashboard.title"), t("dashboard.subtitle")))

        self._layout.addWidget(self._build_status_card())
        self._layout.addLayout(self._build_stats_row())
        self._layout.addWidget(self._build_destination_card())
        self._layout.addWidget(self._build_scan_card())

        columns = QHBoxLayout()
        columns.setSpacing(16)
        self._recent_card = self._build_recent_card()
        columns.addWidget(self._recent_card, 3)
        columns.addWidget(self._build_browser_card(), 2)
        self._layout.addLayout(columns)
        self._layout.addStretch(1)

    def _build_status_card(self) -> QWidget:
        card = Card(padding=20, spacing=0)
        row = QHBoxLayout()
        row.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        self._status_title = QLabel(t("dashboard.auto_title"))
        self._status_title.setObjectName("sectionTitle")
        self._status_subtitle = MutedLabel(t("dashboard.auto_on"))
        text_column.addWidget(self._status_title)
        text_column.addWidget(self._status_subtitle)
        row.addLayout(text_column, 1)

        self._status_pill = Pill(t("status.off"), "skipped")
        row.addWidget(self._status_pill, 0, Qt.AlignVCenter)

        self._pause_button = QPushButton(t("dashboard.btn_pause"))
        self._pause_button.clicked.connect(self._on_pause_clicked)
        row.addWidget(self._pause_button, 0, Qt.AlignVCenter)

        card.add_layout(row)
        return card

    def _build_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        self._tile_today = StatTile(t("dashboard.stat_today"))
        self._tile_total = StatTile(t("dashboard.stat_total"))
        self._tile_size = StatTile(t("dashboard.stat_size"))
        self._tile_failed = StatTile(t("dashboard.stat_failed"))
        for tile in (self._tile_today, self._tile_total, self._tile_size, self._tile_failed):
            row.addWidget(tile)
        return row

    def _build_destination_card(self) -> QWidget:
        card = Card(padding=18, spacing=10)
        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("dashboard.destination")), 1)

        self._open_dest_button = QPushButton(t("dashboard.open_folder"))
        self._open_dest_button.setObjectName("link")
        self._open_dest_button.clicked.connect(self._on_open_destination)
        header.addWidget(self._open_dest_button)

        self._change_dest_button = QPushButton(t("dashboard.change"))
        self._change_dest_button.clicked.connect(lambda: self.navigate_requested.emit("settings"))
        header.addWidget(self._change_dest_button)
        card.add_layout(header)

        self._dest_label = QLabel(t("dashboard.destination_none"))
        self._dest_label.setWordWrap(True)
        self._dest_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(self._dest_label)
        return card

    def _build_scan_card(self) -> QWidget:
        card = Card(padding=18, spacing=10)
        row = QHBoxLayout()
        row.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        title = QLabel(t("dashboard.scan_title"))
        title.setObjectName("sectionTitle")
        text_column.addWidget(title)
        text_column.addWidget(MutedLabel(t("dashboard.scan_hint")))
        row.addLayout(text_column, 1)

        self._scan_button = QPushButton(t("dashboard.btn_scan"))
        self._scan_button.clicked.connect(self._on_scan_clicked)
        row.addWidget(self._scan_button, 0, Qt.AlignVCenter)

        card.add_layout(row)
        return card

    def _build_recent_card(self) -> QWidget:
        card = Card(padding=18, spacing=12)
        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("dashboard.recent")), 1)
        view_all = QPushButton(t("nav.history"))
        view_all.setObjectName("link")
        view_all.clicked.connect(lambda: self.navigate_requested.emit("history"))
        header.addWidget(view_all)
        card.add_layout(header)

        self._recent_container = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(2)
        card.add(self._recent_container)
        self._recent_empty = MutedLabel(t("dashboard.recent_empty"))
        card.add(self._recent_empty)
        return card

    def _build_browser_card(self) -> QWidget:
        card = Card(padding=18, spacing=10)
        card.add(SectionTitle(t("dashboard.browsers")))
        self._browser_pills: dict[str, Pill] = {}
        self._browser_rows: dict[str, QLabel] = {}
        for browser in ("chrome", "edge"):
            row = QHBoxLayout()
            label = QLabel(t(f"about.browser_{browser}"))
            self._browser_rows[browser] = label
            row.addWidget(label, 1)
            pill = Pill(t("dashboard.browser_disconnected"), "skipped")
            self._browser_pills[browser] = pill
            row.addWidget(pill, 0, Qt.AlignRight)
            card.add_layout(row)
        self._browser_note = MutedLabel("")
        self._browser_note.setWordWrap(True)
        card.add(self._browser_note)
        return card

    # -- state -------------------------------------------------------------
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        for pill in self._browser_pills.values():
            pill.set_status("skipped", pill.text(), palette)
        self.refresh()

    def retranslate(self) -> None:
        """Kept for completeness: the main window rebuilds pages instead."""
        self._status_title.setText(t("dashboard.auto_title"))
        self.refresh()

    def refresh(self) -> None:
        stats = self._controller.stats()
        paused = bool(stats.get("paused"))
        destination = str(stats.get("destination") or "").strip()
        auto = bool(stats.get("auto_organize"))

        if not destination:
            self._status_pill.set_status("skipped", t("common.not_configured"), self._palette)
            self._status_subtitle.setText(t("dashboard.auto_nodest"))
        elif paused:
            self._status_pill.set_status("undone", t("status.paused"), self._palette)
            self._status_subtitle.setText(t("dashboard.auto_off"))
        elif auto:
            self._status_pill.set_status("organized", t("status.active"), self._palette)
            self._status_subtitle.setText(t("dashboard.auto_on"))
        else:
            self._status_pill.set_status("skipped", t("status.off"), self._palette)
            self._status_subtitle.setText(t("dashboard.auto_off"))

        self._pause_button.setText(
            t("dashboard.btn_resume") if paused else t("dashboard.btn_pause")
        )
        self._pause_button.setEnabled(bool(destination))

        self._tile_today.set_value(str(stats.get("organized_today", 0)))
        self._tile_total.set_value(str(stats.get("organized_total", 0)))
        self._tile_size.set_value(format_bytes(int(stats.get("bytes_today", 0))))
        self._tile_failed.set_value(str(stats.get("failed_total", 0)))

        self._dest_label.setText(destination or t("dashboard.destination_none"))
        self._open_dest_button.setEnabled(bool(destination) and Path(destination).is_dir())

        self._refresh_browsers()
        self._refresh_recent()

    def _refresh_browsers(self) -> None:
        status = self._controller.browser_status()
        for browser, pill in self._browser_pills.items():
            connected = status.get(browser, {}).get("connected", False)
            if connected:
                pill.set_status("organized", t("dashboard.browser_connected"), self._palette)
            else:
                pill.set_status("skipped", t("dashboard.browser_disconnected"), self._palette)
        if not self._controller.bridge_running:
            self._browser_note.setText(t("dashboard.bridge_down"))
        else:
            self._browser_note.setText("")

    def _refresh_recent(self) -> None:
        _clear_layout(self._recent_layout)
        operations = self._controller.recent(5)
        self._recent_empty.setVisible(not operations)
        for operation in operations:
            self._recent_layout.addWidget(self._recent_row(operation))

    def _recent_row(self, operation) -> QWidget:
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(10)

        name = Path(operation.final_path).name or Path(operation.original_path).name
        title = QLabel(name)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setToolTip(operation.final_path or operation.original_path)
        layout.addWidget(title, 1)

        category = QLabel(operation.category)
        category.setObjectName("muted")
        layout.addWidget(category, 0)

        pill = Pill(
            t(f"status.{operation.status}"),
            operation.status,
            palette=self._palette,
        )
        layout.addWidget(pill, 0)

        when = QLabel(_short_time(operation.organized_at))
        when.setObjectName("muted")
        layout.addWidget(when, 0)
        return row

    # -- events ------------------------------------------------------------
    def _on_pause_clicked(self) -> None:
        self._controller.toggle_paused()
        self.refresh()

    def _on_open_destination(self) -> None:
        destination = self._controller.settings.destination_dir
        if destination:
            self._controller.open_path(destination)

    def _on_scan_clicked(self) -> None:
        from .scan_dialog import ScanDialog

        dialog = ScanDialog(self._controller, self)
        if self._palette is not None:
            dialog.apply_palette(self._palette)
        dialog.exec()
        self.refresh()


def _short_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    now = datetime.now(timezone.utc).astimezone()
    if moment.date() == now.date():
        return moment.strftime("%H:%M")
    return moment.strftime("%m-%d %H:%M")


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())
