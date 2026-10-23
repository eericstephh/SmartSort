"""Rules & categories editor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from .theme import Palette
from .widgets import Card, MutedLabel, title_block


class CategoriesPage(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._palette: Palette | None = None
        self._build()
        self.reload()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self._layout = layout

        layout.addWidget(title_block(t("categories.title"), t("categories.subtitle")))

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            [
                t("categories.col_category"),
                t("categories.col_enabled"),
                t("categories.col_extensions"),
                t("categories.col_count"),
            ]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self._table.horizontalHeader()
        # Column 0 is sized manually in reload(): ResizeToContents measures the
        # cell widget before it has been laid out and clips long names such as
        # "Documents" / "Installers".
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self._table, 1)

        note = Card(padding=14, spacing=4)
        note.add(MutedLabel(t("categories.help")))
        layout.addWidget(note)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        save = QPushButton(t("categories.save"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        actions.addWidget(save)

        reset = QPushButton(t("categories.reset"))
        reset.clicked.connect(self._reset)
        actions.addWidget(reset)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._rows: list[tuple[str, QCheckBox, QLineEdit]] = []

    # -- data --------------------------------------------------------------
    def reload(self) -> None:
        categories = self._controller.categories()
        counts = self._controller.repos.operations.count_by_category()
        self._table.setRowCount(0)
        self._rows = []
        for row, category in enumerate(categories):
            self._table.insertRow(row)
            name_item = QLabel(category.name)
            name_item.setContentsMargins(8, 0, 8, 0)
            self._table.setCellWidget(row, 0, name_item)

            checkbox = QCheckBox()
            checkbox.setChecked(category.enabled)
            if category.id == "other":
                checkbox.setEnabled(False)
                checkbox.setToolTip(t("categories.help"))
            wrapper = QWidget()
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(8, 0, 8, 0)
            wrapper_layout.setAlignment(Qt.AlignCenter)
            wrapper_layout.addWidget(checkbox)
            self._table.setCellWidget(row, 1, wrapper)

            editor = QLineEdit(", ".join(category.extensions))
            editor.setPlaceholderText("—")
            if category.id == "other":
                editor.setEnabled(False)
            self._table.setCellWidget(row, 2, editor)

            count_label = QLabel(str(counts.get(category.id, 0)))
            count_label.setContentsMargins(8, 0, 8, 0)
            count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setCellWidget(row, 3, count_label)

            self._rows.append((category.id, checkbox, editor))
        self._table.resizeRowsToContents()
        self._size_name_column([category.name for category in categories])

    def _size_name_column(self, names: list[str]) -> None:
        """Give the category column enough room for the longest label."""
        metrics = QFontMetrics(self._table.font())
        header_item = self._table.horizontalHeaderItem(0)
        widest = metrics.horizontalAdvance(header_item.text()) if header_item else 0
        for name in names:
            widest = max(widest, metrics.horizontalAdvance(name))
        # 8px cell margin on each side plus slack for the bold table header.
        self._table.setColumnWidth(0, max(132, widest + 40))

    def _save(self) -> None:
        updates: list[tuple[str, bool, list[str]]] = []
        for category_id, checkbox, editor in self._rows:
            extensions = [part for part in editor.text().replace(";", ",").split(",")]
            updates.append((category_id, checkbox.isChecked(), extensions))
        self._controller.save_categories(updates)
        self.reload()
        QMessageBox.information(self, t("categories.title"), t("categories.saved"))

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            t("categories.reset"),
            t("categories.reset_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._controller.reset_categories()
        self.reload()

    # -- theming -----------------------------------------------------------
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette

    def retranslate(self) -> None:
        self.reload()
