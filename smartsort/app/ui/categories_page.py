"""Rules & categories editor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import has_key, t
from ..storage.repositories import CategoryError
from .theme import Palette
from .widgets import Card, MutedLabel, title_block


class _CategoryDialog(QDialog):
    """Name and extensions for a new category."""

    def __init__(self, parent: QWidget, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(QLabel(t("categories.dialog_name")))
        self._name = QLineEdit()
        layout.addWidget(self._name)

        layout.addWidget(QLabel(t("categories.dialog_extensions")))
        self._extensions = QLineEdit()
        self._extensions.setPlaceholderText("psd, ai, sketch")
        layout.addWidget(self._extensions)

        hint = MutedLabel(t("categories.dialog_extensions_help"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._name.setFocus()

    def values(self) -> tuple[str, list[str]]:
        raw = self._extensions.text().replace(";", ",")
        return self._name.text(), [part for part in raw.split(",")]


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

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            [
                t("categories.col_category"),
                t("categories.col_enabled"),
                t("categories.col_extensions"),
                t("categories.col_count"),
                "",
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
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self._table, 1)

        note = Card(padding=14, spacing=4)
        note.add(MutedLabel(t("categories.help")))
        layout.addWidget(note)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        add = QPushButton(t("categories.add"))
        add.clicked.connect(self._add_category)
        actions.addWidget(add)

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

            if not category.builtin:
                self._table.setCellWidget(
                    row, 4, self._row_actions(category.id, category.name)
                )

            self._rows.append((category.id, checkbox, editor))
        self._table.resizeRowsToContents()
        self._size_name_column([category.name for category in categories])

    def _row_actions(self, category_id: str, name: str) -> QWidget:
        """Rename and delete, offered only for categories the user created."""
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        rename = QPushButton(t("categories.rename"))
        rename.clicked.connect(
            lambda _checked=False, cid=category_id: self._rename_category(cid)
        )
        layout.addWidget(rename)

        delete = QPushButton(t("categories.delete"))
        delete.clicked.connect(
            lambda _checked=False, cid=category_id, n=name: self._delete_category(cid, n)
        )
        layout.addWidget(delete)
        return holder

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

    # -- user categories ---------------------------------------------------
    def _add_category(self) -> None:
        dialog = _CategoryDialog(self, t("categories.add"))
        if dialog.exec() != QDialog.Accepted:
            return
        name, extensions = dialog.values()
        try:
            category_id = self._controller.add_category(name, extensions)
        except CategoryError as exc:
            QMessageBox.warning(self, t("categories.add"), self._error_text(exc))
            return
        self.reload()

        # A new category is appended after the built-in ones, so an extension
        # that another category already claims will keep going there. Say so
        # now instead of letting the user wonder why the folder stays empty.
        conflicts = self._controller.category_conflicts(
            extensions, exclude_id=category_id
        )
        if conflicts:
            lines = "\n".join(
                f"- {ext} — {owner}" for ext, owner in sorted(conflicts.items())
            )
            QMessageBox.warning(
                self,
                t("categories.add"),
                f"{t('categories.conflict_warning')}\n\n{lines}",
            )

    def _rename_category(self, category_id: str) -> None:
        current = next(
            (c for c in self._controller.categories() if c.id == category_id), None
        )
        if current is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            t("categories.rename"),
            t("categories.dialog_name"),
            text=current.name,
        )
        if not accepted:
            return
        try:
            self._controller.rename_category(category_id, name)
        except CategoryError as exc:
            QMessageBox.warning(self, t("categories.rename"), self._error_text(exc))
            return
        self.reload()

    def _delete_category(self, category_id: str, name: str) -> None:
        count = self._controller.repos.operations.count_by_category().get(category_id, 0)
        answer = QMessageBox.question(
            self,
            t("categories.delete"),
            t("categories.delete_confirm", name=name, count=count),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._controller.delete_category(category_id)
        except CategoryError as exc:
            QMessageBox.warning(self, t("categories.delete"), self._error_text(exc))
            return
        self.reload()

    @staticmethod
    def _error_text(exc: CategoryError) -> str:
        key = f"categories.error_{exc.code}"
        return t(key) if has_key(key) else str(exc)

    # -- theming -----------------------------------------------------------
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette

    def retranslate(self) -> None:
        self.reload()
