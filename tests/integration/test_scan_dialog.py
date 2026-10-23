"""The scan dialog and the batch organize behind it.

The dialog is driven directly (no ``exec()``) so the test can inspect the table
and the selection without a human clicking anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from smartsort.app.bootstrap import create_context  # noqa: E402
from tests.conftest import make_file  # noqa: E402


@pytest.fixture
def controller(tmp_path: Path, monkeypatch, qapp):
    from smartsort.app.ui.controller import AppController

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("SMARTSORT_DATA_DIR", str(data_dir))
    context = create_context(data_dir, setup_logs=False)
    context.settings.destination_dir = str(tmp_path / "SmartSort")
    context.settings.set("auto_organize", True)
    instance = AppController(context)
    try:
        yield instance
    finally:
        instance.shutdown()
        context.close()


@pytest.fixture
def source_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    make_file(folder, "photo.jpg")
    make_file(folder, "report.pdf")
    make_file(folder, "song.mp3")
    make_file(folder, "movie.mp4.crdownload")
    return folder


def build_dialog(controller, folder: Path):
    """An empty ``directory`` keeps the dialog from auto-scanning on construction."""
    from smartsort.app.ui.scan_dialog import ScanDialog

    dialog = ScanDialog(controller, directory="")
    dialog._folder_edit.setText(str(folder))
    dialog._populate(controller.scan_folder(str(folder)))
    return dialog


def test_dialog_lists_files_and_preselects_the_organizable_ones(
    controller, source_folder: Path
):
    dialog = build_dialog(controller, source_folder)
    try:
        assert dialog._table.rowCount() == 4

        checked = 0
        for row in range(dialog._table.rowCount()):
            entry = dialog._table.item(row, 0)
            if entry.checkState() == Qt.Checked:
                checked += 1
        assert checked == 3, "the .crdownload file must not be pre-selected"

        assert dialog._organize_button.isEnabled()
        assert "3" in dialog._organize_button.text()
    finally:
        dialog.reject()


def test_in_progress_file_has_no_checkbox(controller, source_folder: Path):
    dialog = build_dialog(controller, source_folder)
    try:
        for row in range(dialog._table.rowCount()):
            entry = dialog._table.item(row, 0)
            if entry.text() == "movie.mp4.crdownload":
                assert not (entry.flags() & Qt.ItemIsUserCheckable)
                assert dialog._table.item(row, 4).text() == "Still downloading"
                break
        else:  # pragma: no cover - the fixture always creates the file
            pytest.fail("the in-progress file was not listed")
    finally:
        dialog.reject()


def test_filter_hides_non_matching_rows(controller, source_folder: Path):
    dialog = build_dialog(controller, source_folder)
    try:
        dialog._filter_edit.setText("photo")
        visible = [
            row
            for row in range(dialog._table.rowCount())
            if not dialog._table.isRowHidden(row)
        ]
        assert len(visible) == 1
        assert dialog._table.item(visible[0], 0).text() == "photo.jpg"
    finally:
        dialog.reject()


def test_select_none_disables_the_organize_button(controller, source_folder: Path):
    dialog = build_dialog(controller, source_folder)
    try:
        dialog._set_all_checked(False)
        assert not dialog._organize_button.isEnabled()
    finally:
        dialog.reject()


def test_organize_scanned_moves_files_and_records_history(
    controller, source_folder: Path, tmp_path: Path
):
    destination = tmp_path / "SmartSort"
    result = controller.organize_scanned(controller.scan_folder(str(source_folder)).actionable)

    assert result["organized"] == 3
    assert result["failed"] == 0
    assert (source_folder / "movie.mp4.crdownload").exists(), "leftover temp file untouched"
    assert not (source_folder / "photo.jpg").exists()

    moved = list(destination.rglob("*.*"))
    assert {path.name for path in moved} == {"photo.jpg", "report.pdf", "song.mp3"}
    assert controller.repos.operations.count() == 3


def test_organize_scanned_is_idempotent(controller, source_folder: Path):
    items = controller.scan_folder(str(source_folder)).actionable
    controller.organize_scanned(items)

    # A second pass over the same paths must not duplicate history.
    second = controller.organize_scanned(items)

    assert second["organized"] == 0
    assert controller.repos.operations.count() == 3
