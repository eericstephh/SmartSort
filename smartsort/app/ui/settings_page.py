"""Settings screen."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import LANGUAGES, t
from .theme import Palette
from .widgets import Card, MutedLabel, SectionTitle, SwitchRow, title_block


class SettingsPage(QWidget):
    theme_changed = Signal(str)

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._palette: Palette | None = None
        self._loading = False
        self._build()
        self.load()

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
        scroll.setWidget(container)

        self._layout.addWidget(title_block(t("settings.title"), t("settings.subtitle")))
        self._layout.addWidget(self._destination_card())
        self._layout.addWidget(self._automation_card())
        self._layout.addWidget(self._watch_card())
        self._layout.addWidget(self._startup_card())
        self._layout.addWidget(self._appearance_card())
        self._layout.addStretch(1)

    def _destination_card(self) -> QWidget:
        card = Card(padding=20, spacing=12)
        card.add(SectionTitle(t("settings.destination_label")))
        card.add(MutedLabel(t("settings.destination_help")))

        row = QHBoxLayout()
        row.setSpacing(8)
        self._dest_edit = QLineEdit()
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setPlaceholderText(t("dashboard.destination_none"))
        row.addWidget(self._dest_edit, 1)

        browse = QPushButton(t("common.browse"))
        browse.clicked.connect(self._choose_destination)
        row.addWidget(browse)

        self._open_dest = QPushButton(t("common.open"))
        self._open_dest.clicked.connect(self._open_destination)
        row.addWidget(self._open_dest)
        card.add_layout(row)
        return card

    def _automation_card(self) -> QWidget:
        card = Card(padding=20, spacing=14)
        card.add(SectionTitle(t("settings.section_automation")))

        self._auto = SwitchRow(
            t("settings.auto_organize"), t("settings.auto_organize_help")
        )
        self._auto.toggled.connect(self._on_auto_toggled)
        card.add(self._auto)

        self._date_folders = SwitchRow(t("settings.date_folders"))
        self._date_folders.toggled.connect(
            lambda value: self._update({"use_date_folders": value})
        )
        card.add(self._date_folders)

        self._category_folders = SwitchRow(t("settings.category_folders"))
        self._category_folders.toggled.connect(
            lambda value: self._update({"use_category_folders": value})
        )
        card.add(self._category_folders)

        self._allow_browser_move = SwitchRow(
            t("settings.allow_browser_move"), t("settings.allow_browser_move_help")
        )
        self._allow_browser_move.toggled.connect(
            lambda value: self._update({"allow_move_from_browser_default": value})
        )
        card.add(self._allow_browser_move)

        self._skip_duplicates = SwitchRow(
            t("settings.skip_duplicates"), t("settings.skip_duplicates_help")
        )
        self._skip_duplicates.toggled.connect(
            lambda value: self._update({"skip_duplicate_content": value})
        )
        card.add(self._skip_duplicates)
        return card

    def _watch_card(self) -> QWidget:
        card = Card(padding=20, spacing=12)
        card.add(SectionTitle(t("settings.section_watch")))

        self._watch_enabled = SwitchRow(
            t("settings.watch_enabled"), t("settings.watch_help")
        )
        self._watch_enabled.toggled.connect(self._on_watch_toggled)
        card.add(self._watch_enabled)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._watch_edit = QLineEdit()
        self._watch_edit.setReadOnly(True)
        self._watch_edit.setPlaceholderText(t("settings.watch_dir"))
        row.addWidget(self._watch_edit, 1)
        watch_browse = QPushButton(t("common.browse"))
        watch_browse.clicked.connect(self._choose_watch_dir)
        row.addWidget(watch_browse)
        card.add_layout(row)

        numbers = QHBoxLayout()
        numbers.setSpacing(18)

        poll_column = QVBoxLayout()
        poll_column.setSpacing(4)
        poll_column.addWidget(QLabel(t("settings.watch_poll")))
        self._poll_spin = QDoubleSpinBox()
        self._poll_spin.setRange(0.5, 60.0)
        self._poll_spin.setSingleStep(0.5)
        self._poll_spin.setDecimals(1)
        self._poll_spin.valueChanged.connect(
            lambda value: self._update({"watch_poll_seconds": float(value)})
        )
        poll_column.addWidget(self._poll_spin)
        numbers.addLayout(poll_column)

        settle_column = QVBoxLayout()
        settle_column.setSpacing(4)
        settle_column.addWidget(QLabel(t("settings.watch_settle")))
        self._settle_spin = QDoubleSpinBox()
        self._settle_spin.setRange(0.0, 600.0)
        self._settle_spin.setSingleStep(1.0)
        self._settle_spin.setDecimals(1)
        self._settle_spin.valueChanged.connect(
            lambda value: self._update({"watch_settle_seconds": float(value)})
        )
        settle_column.addWidget(self._settle_spin)
        numbers.addLayout(settle_column)
        numbers.addStretch(1)
        card.add_layout(numbers)
        return card

    def _startup_card(self) -> QWidget:
        card = Card(padding=20, spacing=14)
        card.add(SectionTitle(t("settings.section_startup")))

        self._startup = SwitchRow(t("settings.start_with_windows"))
        self._startup.toggled.connect(self._on_startup_toggled)
        card.add(self._startup)

        self._minimize = SwitchRow(t("settings.minimize_to_tray"))
        self._minimize.toggled.connect(lambda value: self._update({"minimize_to_tray": value}))
        card.add(self._minimize)

        self._close_tray = SwitchRow(t("settings.close_to_tray"))
        self._close_tray.toggled.connect(lambda value: self._update({"close_to_tray": value}))
        card.add(self._close_tray)
        return card

    def _appearance_card(self) -> QWidget:
        card = Card(padding=20, spacing=12)
        card.add(SectionTitle(t("settings.section_appearance")))

        language_row = QHBoxLayout()
        language_row.setSpacing(12)
        language_row.addWidget(QLabel(t("settings.language")), 0)
        self._language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self._language_combo.addItem(label, code)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_row.addWidget(self._language_combo, 1)
        card.add_layout(language_row)
        card.add(MutedLabel(t("settings.language_help")))

        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_row.addWidget(QLabel(t("settings.theme")), 0)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem(t("settings.theme_light"), "light")
        self._theme_combo.addItem(t("settings.theme_dark"), "dark")
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self._theme_combo, 1)
        card.add_layout(theme_row)
        return card

    # -- data --------------------------------------------------------------
    def load(self) -> None:
        self._loading = True
        settings = self._controller.settings
        self._dest_edit.setText(settings.destination_dir)
        self._auto.set_checked(settings.auto_organize)
        self._date_folders.set_checked(settings.use_date_folders)
        self._category_folders.set_checked(bool(settings.get("use_category_folders", True)))
        self._allow_browser_move.set_checked(settings.allow_move_from_browser_default)
        self._skip_duplicates.set_checked(settings.skip_duplicate_content)
        self._watch_enabled.set_checked(settings.watch_enabled)
        self._watch_edit.setText(settings.watch_directory or self._controller.default_downloads_dir())
        self._poll_spin.setValue(settings.watch_poll_seconds)
        self._settle_spin.setValue(settings.watch_settle_seconds)
        self._startup.set_checked(settings.start_with_windows)
        self._minimize.set_checked(settings.minimize_to_tray)
        self._close_tray.set_checked(settings.close_to_tray)
        self._select_data(self._language_combo, settings.language)
        self._select_data(self._theme_combo, settings.theme)
        self._loading = False
        self._update_enabled_states()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        for row in (
            self._auto,
            self._date_folders,
            self._category_folders,
            self._allow_browser_move,
            self._skip_duplicates,
            self._watch_enabled,
            self._startup,
            self._minimize,
            self._close_tray,
        ):
            row.apply_palette(palette)

    def retranslate(self) -> None:
        """Kept for completeness: the main window rebuilds pages instead."""
        self.load()

    # -- handlers ----------------------------------------------------------
    def _update(self, values: dict) -> None:
        if self._loading:
            return
        self._controller.update_settings(values)

    def _update_enabled_states(self) -> None:
        watching = self._watch_enabled.is_checked()
        self._watch_edit.setEnabled(watching)
        self._poll_spin.setEnabled(watching)
        self._settle_spin.setEnabled(watching)

    def _on_auto_toggled(self, value: bool) -> None:
        if self._loading:
            return
        self._controller.set_auto_organize(value)

    def _on_watch_toggled(self, value: bool) -> None:
        if self._loading:
            return
        directory = self._watch_edit.text().strip()
        if value and not Path(directory).is_dir():
            chosen = self._pick_directory(t("settings.watch_dir"), directory)
            if not chosen:
                self._watch_enabled.set_checked(False)
                self._update_enabled_states()
                return
            self._watch_edit.setText(chosen)
            directory = chosen
        self._update({"watch_enabled": value, "watch_directory": directory})
        self._update_enabled_states()

    def _on_startup_toggled(self, value: bool) -> None:
        if self._loading:
            return
        from ..services import startup_service

        ok = startup_service.apply(value)
        if not ok and value:
            self._startup.set_checked(False)
            QMessageBox.warning(self, t("common.warning"), t("errors.operation_failed", reason="registry"))
            return
        self._update({"start_with_windows": value})

    def _on_language_changed(self) -> None:
        if self._loading:
            return
        language = self._language_combo.currentData()
        if language:
            self._controller.set_language(str(language))

    def _on_theme_changed(self) -> None:
        if self._loading:
            return
        theme = self._theme_combo.currentData()
        if not theme:
            return
        self._update({"theme": str(theme)})
        self.theme_changed.emit(str(theme))

    def _choose_destination(self) -> None:
        start = self._controller.settings.destination_dir or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, t("settings.destination_label"), start)
        if not chosen:
            return
        ok, payload = self._controller.set_destination(chosen)
        if ok:
            self._dest_edit.setText(str(payload))
        else:
            QMessageBox.warning(self, t("common.warning"), t("settings.destination_invalid"))

    def _choose_watch_dir(self) -> None:
        chosen = self._pick_directory(t("settings.watch_dir"), self._watch_edit.text())
        if chosen:
            self._watch_edit.setText(chosen)
            self._update({"watch_directory": chosen})

    def _pick_directory(self, title: str, start: str) -> str:
        return QFileDialog.getExistingDirectory(self, title, start or str(Path.home()))

    def _open_destination(self) -> None:
        destination = self._controller.settings.destination_dir
        if destination:
            self._controller.open_path(destination)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())
