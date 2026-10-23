"""Scan an existing folder and organize what the user picks.

This is the answer to "what about the files already in my Downloads folder?".
The dialog is read-only until the user presses Organize: scanning builds a
preview table, and nothing on disk changes until a confirmation is accepted.

Everything that touches the filesystem runs on the background worker, so a
folder with thousands of files cannot freeze the window.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
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

from ..core.folder_scanner import ScanItem, ScanResult
from ..i18n import t
from .theme import Palette
from .widgets import MutedLabel, format_bytes
from .workers import TaskRunner

_COL_NAME = 0
_COL_SIZE = 1
_COL_MODIFIED = 2
_COL_CATEGORY = 3
_COL_TARGET = 4


class ScanDialog(QDialog):
    """Pick a folder, see what would happen, then decide."""

    def __init__(
        self, controller, parent: QWidget | None = None, *, directory: str | None = None
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._palette: Palette | None = None
        self._items: list[ScanItem] = []
        self._result: ScanResult | None = None
        self._task = ""
        self._organizing = False
        self._initial_directory = (
            directory if directory is not None else controller.default_scan_directory()
        )

        self._runner = TaskRunner(self)
        self._runner.succeeded.connect(self._on_task_succeeded)
        self._runner.failed.connect(self._on_task_failed)

        self.setWindowTitle(t("scan.title"))
        self.setMinimumSize(940, 620)
        self._build()
        self._auto_start()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        heading = QLabel(t("scan.title"))
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        layout.addWidget(MutedLabel(t("scan.subtitle")))

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self._folder_edit = QLineEdit(self._initial_directory)
        self._folder_edit.setPlaceholderText(t("scan.folder_placeholder"))
        self._folder_edit.returnPressed.connect(self._start_scan)
        folder_row.addWidget(self._folder_edit, 1)

        browse = QPushButton(t("scan.browse"))
        browse.clicked.connect(self._browse)
        self._browse_button = browse
        folder_row.addWidget(browse)

        self._scan_button = QPushButton(t("scan.button_scan"))
        self._scan_button.setObjectName("primary")
        self._scan_button.clicked.connect(self._start_scan)
        folder_row.addWidget(self._scan_button)
        layout.addLayout(folder_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(12)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(t("scan.filter_placeholder"))
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        options_row.addWidget(self._filter_edit, 1)

        self._recursive_box = QCheckBox(t("scan.include_subfolders"))
        self._recursive_box.toggled.connect(lambda _checked: self._start_scan())
        options_row.addWidget(self._recursive_box)
        layout.addLayout(options_row)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            [
                t("scan.col_name"),
                t("scan.col_size"),
                t("scan.col_modified"),
                t("scan.col_category"),
                t("scan.col_target"),
            ]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.itemChanged.connect(self._on_item_changed)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        for column in (_COL_SIZE, _COL_MODIFIED, _COL_CATEGORY):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_TARGET, QHeaderView.Interactive)
        self._table.setColumnWidth(_COL_TARGET, 260)
        # Header labels follow the alignment of their cells; the default centre
        # alignment reads as misaligned next to left-aligned file names.
        for column, alignment in (
            (_COL_NAME, Qt.AlignLeft),
            (_COL_SIZE, Qt.AlignRight),
            (_COL_MODIFIED, Qt.AlignLeft),
            (_COL_CATEGORY, Qt.AlignLeft),
            (_COL_TARGET, Qt.AlignLeft),
        ):
            entry = self._table.horizontalHeaderItem(column)
            if entry is not None:
                entry.setTextAlignment(alignment | Qt.AlignVCenter)
        layout.addWidget(self._table, 1)

        self._status = MutedLabel("")
        layout.addWidget(self._status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._select_all = QPushButton(t("scan.select_all"))
        self._select_all.clicked.connect(lambda: self._set_all_checked(True))
        actions.addWidget(self._select_all)

        self._select_none = QPushButton(t("scan.select_none"))
        self._select_none.clicked.connect(lambda: self._set_all_checked(False))
        actions.addWidget(self._select_none)
        actions.addStretch(1)

        self._close_button = QPushButton(t("scan.close"))
        self._close_button.clicked.connect(self.reject)
        actions.addWidget(self._close_button)

        self._organize_button = QPushButton(t("scan.organize_selected"))
        self._organize_button.setObjectName("primary")
        self._organize_button.setEnabled(False)
        self._organize_button.clicked.connect(self._organize)
        actions.addWidget(self._organize_button)
        layout.addLayout(actions)

    def _auto_start(self) -> None:
        if self._folder_edit.text().strip():
            self._start_scan()

    # -- palette -----------------------------------------------------------
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette

    # -- scanning ----------------------------------------------------------
    def _browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, t("scan.browse"), start)
        if chosen:
            self._folder_edit.setText(chosen)
            self._start_scan()

    def _start_scan(self) -> None:
        if self._organizing:
            return
        directory = self._folder_edit.text().strip()
        if not directory:
            return
        self._set_busy(True, t("scan.scanning"))
        self._task = "scan"
        self._runner.submit(
            self._controller.scan_folder,
            directory,
            recursive=self._recursive_box.isChecked(),
        )

    def _on_task_succeeded(self, payload) -> None:
        if self._task == "scan":
            self._populate(payload)
            self._set_busy(False, "")
        elif self._task == "organize":
            self._finish_organize(payload)

    def _on_task_failed(self, kind: str, message: str) -> None:
        self._task = ""
        self._organizing = False
        self._set_busy(False, t("scan.error", message=message))
        QMessageBox.warning(self, t("scan.title"), t("scan.error", message=message))

    def _populate(self, result: ScanResult) -> None:
        self._result = result
        self._items = list(result.items)
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        for row, item in enumerate(self._items):
            self._table.insertRow(row)
            self._fill_row(row, item)

        self._table.blockSignals(False)
        self._apply_filter()
        self._refresh_status()

    def _fill_row(self, row: int, item: ScanItem) -> None:
        name = QTableWidgetItem(item.name)
        name.setData(Qt.UserRole, row)
        name.setToolTip(str(item.path))
        if item.actionable:
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.Checked)
        else:
            # Not offerable: no checkbox, muted text, reason shown instead of a
            # target so the user can see why it was left out.
            name.setFlags(Qt.ItemIsEnabled)
        self._table.setItem(row, _COL_NAME, name)

        size = QTableWidgetItem(format_bytes(item.size_bytes))
        size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._table.setItem(row, _COL_SIZE, size)

        modified = QTableWidgetItem(item.modified_at.strftime("%Y-%m-%d %H:%M"))
        self._table.setItem(row, _COL_MODIFIED, modified)

        category = QTableWidgetItem(item.category_name)
        self._table.setItem(row, _COL_CATEGORY, category)

        if item.actionable:
            target_item = QTableWidgetItem(
                _relative_target(item.target_dir, self._controller.settings.destination_dir)
            )
            target_item.setToolTip(str(item.target_dir or ""))
        else:
            target_item = QTableWidgetItem(t(f"scan.reason.{item.reason}"))
        self._table.setItem(row, _COL_TARGET, target_item)

        if not item.actionable and self._palette is not None:
            muted = QColor(self._palette.text_muted)
            for column in (_COL_NAME, _COL_SIZE, _COL_MODIFIED, _COL_CATEGORY, _COL_TARGET):
                entry = self._table.item(row, column)
                if entry is not None:
                    entry.setForeground(muted)

    # -- filtering and selection ------------------------------------------
    def _apply_filter(self) -> None:
        needle = self._filter_edit.text().strip().lower()
        for row, item in enumerate(self._items):
            if not needle:
                visible = True
            else:
                haystack = f"{item.name} {item.category_name} {item.category}".lower()
                visible = needle in haystack
            self._table.setRowHidden(row, not visible)
        self._refresh_status()

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self._table.blockSignals(True)
        for row, item in enumerate(self._items):
            if not item.actionable or self._table.isRowHidden(row):
                continue
            entry = self._table.item(row, _COL_NAME)
            if entry is not None:
                entry.setCheckState(state)
        self._table.blockSignals(False)
        self._refresh_status()

    def _selected_items(self) -> list[ScanItem]:
        chosen: list[ScanItem] = []
        for row, item in enumerate(self._items):
            entry = self._table.item(row, _COL_NAME)
            if entry is None or not item.actionable:
                continue
            if entry.checkState() == Qt.Checked:
                chosen.append(item)
        return chosen

    def _on_item_changed(self, _item) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self._result is None:
            return
        visible = sum(1 for row in range(self._table.rowCount()) if not self._table.isRowHidden(row))
        selected = len(self._selected_items())
        total = len(self._items)
        skipped = total - len(self._result.actionable)

        parts = [t("scan.found", count=total)]
        if visible != total:
            parts.append(t("scan.showing", count=visible))
        if skipped:
            parts.append(t("scan.skipped_count", count=skipped))
        parts.append(t("scan.selected_count", count=selected))
        if self._result.truncated:
            parts.append(t("scan.truncated", count=total))
        self._status.setText("  ·  ".join(parts))

        if not self._organizing:
            self._organize_button.setEnabled(selected > 0)
            self._organize_button.setText(
                t("scan.organize_count", count=selected)
                if selected
                else t("scan.organize_selected")
            )

    # -- organizing --------------------------------------------------------
    def _organize(self) -> None:
        chosen = self._selected_items()
        if not chosen:
            return
        destination = self._controller.settings.destination_dir or ""
        if not destination:
            QMessageBox.warning(self, t("scan.title"), t("scan.no_destination"))
            return

        answer = QMessageBox.question(
            self,
            t("scan.confirm_title"),
            t("scan.confirm_body", count=len(chosen), destination=destination),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._organizing = True
        self._task = "organize"
        self._set_busy(True, t("scan.organizing", count=len(chosen)))
        self._runner.submit(self._controller.organize_scanned, chosen)

    def _finish_organize(self, summary: dict) -> None:
        self._organizing = False
        self._task = ""
        self._set_busy(False, "")
        QMessageBox.information(
            self,
            t("scan.done_title"),
            t(
                "scan.done_body",
                organized=summary.get("organized", 0),
                skipped=summary.get("skipped", 0),
                failed=summary.get("failed", 0),
            ),
        )
        self.accept()

    # -- state -------------------------------------------------------------
    def _set_busy(self, busy: bool, message: str) -> None:
        self._scan_button.setEnabled(not busy)
        self._folder_edit.setEnabled(not busy)
        self._browse_button.setEnabled(not busy)
        self._filter_edit.setEnabled(not busy)
        self._select_all.setEnabled(not busy)
        self._select_none.setEnabled(not busy)
        self._close_button.setEnabled(not busy)
        if busy:
            self._organize_button.setEnabled(False)
        if message:
            self._status.setText(message)
        elif not busy:
            self._refresh_status()

    def done(self, result: int) -> None:
        self._runner.shutdown()
        super().done(result)


def _relative_target(target_dir: Path | None, destination: str) -> str:
    """Show the target as ``date\\Category`` rather than a full path."""
    if target_dir is None:
        return ""
    base = str(destination or "").strip()
    if base:
        try:
            return str(Path(target_dir).relative_to(Path(base)))
        except (ValueError, OSError):
            pass
    return str(target_dir)
