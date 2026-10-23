"""Download history with undo support."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from .theme import Palette, pill_colors
from .widgets import Card, MutedLabel, title_block
from .workers import TaskRunner

STATUS_FILTERS = ("", "organized", "failed", "skipped", "duplicate", "undone")


class HistoryPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._palette: Palette | None = None
        self._operations: list = []
        self._runner = TaskRunner(self)
        self._runner.succeeded.connect(self._on_undo_finished)
        self._runner.failed.connect(self._on_undo_error)
        self._build()
        self.reload()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self._layout = layout

        header = QHBoxLayout()
        header.addWidget(title_block(t("history.title"), t("history.subtitle")), 1)
        self._count_label = MutedLabel("")
        header.addWidget(self._count_label, 0, Qt.AlignBottom)
        layout.addLayout(header)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("history.search"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.reload)
        filters.addWidget(self._search, 2)

        self._status_filter = QComboBox()
        for value in STATUS_FILTERS:
            self._status_filter.addItem(
                t("history.filter_status") if not value else t(f"status.{value}"), value
            )
        self._status_filter.currentIndexChanged.connect(self.reload)
        filters.addWidget(self._status_filter, 1)

        self._category_filter = QComboBox()
        self._category_filter.addItem(t("history.filter_category"), "")
        for category in self._controller.categories():
            self._category_filter.addItem(category.name, category.id)
        self._category_filter.currentIndexChanged.connect(self.reload)
        filters.addWidget(self._category_filter, 1)

        refresh = QPushButton(t("common.refresh"))
        refresh.clicked.connect(self.reload)
        filters.addWidget(refresh)
        layout.addLayout(filters)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            [
                t("history.col_time"),
                t("history.col_file"),
                t("history.col_category"),
                t("history.col_status"),
                t("history.col_from"),
                t("history.col_to"),
            ]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._open_selected_location)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.Stretch)
        header_view.setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._undo_button = QPushButton(t("history.undo"))
        self._undo_button.setObjectName("primary")
        self._undo_button.setToolTip(t("history.undo_tooltip"))
        self._undo_button.setEnabled(False)
        self._undo_button.clicked.connect(self._undo_selected)
        actions.addWidget(self._undo_button)

        self._open_button = QPushButton(t("history.open_location"))
        self._open_button.setEnabled(False)
        self._open_button.clicked.connect(self._open_selected_location)
        actions.addWidget(self._open_button)

        self._copy_button = QPushButton(t("common.copy_path"))
        self._copy_button.setEnabled(False)
        self._copy_button.clicked.connect(self._copy_selected_path)
        actions.addWidget(self._copy_button)

        actions.addStretch(1)
        layout.addLayout(actions)

        self._details = Card(padding=14, spacing=6)
        self._details_title = QLabel("")
        self._details_title.setObjectName("sectionTitle")
        self._details.add(self._details_title)
        self._details_text = MutedLabel("")
        self._details_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._details.add(self._details_text)
        layout.addWidget(self._details)

    # -- data --------------------------------------------------------------
    def reload(self) -> None:
        text = self._search.text().strip()
        status = self._status_filter.currentData() or ""
        category = self._category_filter.currentData() or ""
        try:
            operations = self._controller.history(
                limit=300, text=text, status=status, category=category
            )
        except Exception:  # pragma: no cover - defensive
            operations = []
        self._operations = list(operations)
        self._populate()
        self._count_label.setText(t("history.count", count=len(self._operations)))

    def _populate(self) -> None:
        self._table.setRowCount(0)
        for row, operation in enumerate(self._operations):
            self._table.insertRow(row)
            name = Path(operation.final_path).name or Path(operation.original_path).name
            values = [
                _format_time(operation.organized_at),
                name,
                operation.category,
                t(f"status.{operation.status}"),
                operation.original_path,
                operation.final_path or "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column == 3:
                    fg, bg = pill_colors(operation.status, self._palette) if self._palette else ("#333", "#eee")
                    item.setForeground(QColor(fg))
                    item.setBackground(QColor(bg))
                self._table.setItem(row, column, item)
        self._table.resizeRowsToContents()
        self._on_selection_changed()

    # -- selection ---------------------------------------------------------
    def _selected_operation(self):
        row = self._table.currentRow()
        if 0 <= row < len(self._operations):
            return self._operations[row]
        return None

    def _on_selection_changed(self) -> None:
        operation = self._selected_operation()
        has_selection = operation is not None
        self._open_button.setEnabled(has_selection)
        self._copy_button.setEnabled(has_selection)

        can_undo = False
        if operation is not None:
            can_undo, _reason = self._controller.context.undo.can_undo(operation.id)
        self._undo_button.setEnabled(can_undo)

        if operation is None:
            self._details_title.setText(t("history.details"))
            self._details_text.setText(t("history.select_row"))
            return

        name = Path(operation.final_path).name or Path(operation.original_path).name
        self._details_title.setText(name)
        lines = [
            f"{t('history.col_from')}: {operation.original_path}",
            f"{t('history.col_to')}: {operation.final_path or '—'}",
        ]
        if operation.message:
            lines.append(f"{t('history.note')}: {operation.message}")
        if operation.error:
            lines.append(f"{t('common.error')}: {operation.error}")
        if operation.completed_at:
            lines.append(
                f"{t('history.download_completed')}: {_format_time(operation.completed_at)}"
            )
        self._details_text.setText("\n".join(lines))

    # -- actions -----------------------------------------------------------
    def _undo_selected(self) -> None:
        operation = self._selected_operation()
        if operation is None:
            QMessageBox.information(self, t("history.undo"), t("history.select_row"))
            return
        answer = QMessageBox.question(
            self,
            t("history.undo_confirm_title"),
            t("history.undo_confirm_body", path=operation.original_path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._pending_operation_id = operation.id
        self._undo_button.setEnabled(False)
        self._runner.submit(self._controller.undo_operation, operation.id, "cancel")

    def _on_undo_finished(self, result) -> None:
        if getattr(result, "conflict", False):
            operation = self._controller.repos.operations.get(
                getattr(self, "_pending_operation_id", 0)
            )
            name = Path(operation.original_path).name if operation else ""
            answer = QMessageBox.question(
                self,
                t("history.undo_conflict_title"),
                t("history.undo_conflict_body", name=name),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes and operation is not None:
                self._runner.submit(self._controller.undo_operation, operation.id, "rename")
            else:
                self.reload()
            return

        if result.status == "undone":
            QMessageBox.information(
                self, t("history.undo"), t("history.undo_done", path=result.restored_path or "")
            )
        elif result.status == "failed":
            QMessageBox.warning(
                self,
                t("common.error"),
                t("history.undo_failed", reason=result.error or result.message),
            )
        self.reload()

    def _on_undo_error(self, kind: str, message: str) -> None:
        QMessageBox.warning(self, t("common.error"), t("history.undo_failed", reason=f"{kind}: {message}"))
        self.reload()

    def _open_selected_location(self) -> None:
        operation = self._selected_operation()
        if operation is None:
            return
        target = operation.final_path or operation.original_path
        if target:
            self._controller.open_path(Path(target).parent)

    def _copy_selected_path(self) -> None:
        operation = self._selected_operation()
        if operation is None:
            return
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(operation.final_path or operation.original_path)

    # -- theming -----------------------------------------------------------
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._populate()

    def retranslate(self) -> None:
        """Kept for completeness: the main window rebuilds pages instead."""
        self.reload()

    def shutdown(self) -> None:
        self._runner.shutdown()


def _format_time(value: str | None) -> str:
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    return moment.strftime("%Y-%m-%d %H:%M")
