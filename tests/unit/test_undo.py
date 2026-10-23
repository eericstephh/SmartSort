"""Undo behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsort.app.core.organizer import Organizer
from smartsort.app.core.undo_manager import UndoManager
from smartsort.app.storage.models import OrganizeRequest
from tests.conftest import make_file


def organize_one(organizer: Organizer, downloads_dir: Path, name: str = "photo.jpg") -> tuple[int, Path, Path]:
    source = make_file(downloads_dir, name, b"payload")
    result = organizer.organize(
        OrganizeRequest(source_path=str(source), origin="browser", download_id="1", browser="chrome")
    )
    assert result.status == "organized"
    return result.operation_id, source, Path(result.final_path)


def test_undo_restores_the_file(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, original, organized = organize_one(organizer, downloads_dir)

    result = undo.undo(operation_id)
    assert result.status == "undone"
    assert original.exists()
    assert original.read_bytes() == b"payload"
    assert not organized.exists()
    assert result.restored_path == str(original)


def test_undo_marks_the_operation(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path, repos
) -> None:
    operation_id, _original, _organized = organize_one(organizer, downloads_dir)
    undo.undo(operation_id)

    operation = repos.operations.get(operation_id)
    assert operation is not None
    assert operation.status == "undone"
    assert operation.undo_state == "undone"
    assert operation.undo_at is not None


def test_cannot_undo_twice(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, _original, _organized = organize_one(organizer, downloads_dir)
    undo.undo(operation_id)

    ok, reason = undo.can_undo(operation_id)
    assert ok is False
    assert reason == "operation_not_undoable"


def test_undo_fails_when_organized_file_is_gone(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, _original, organized = organize_one(organizer, downloads_dir)
    organized.unlink()

    result = undo.undo(operation_id)
    assert result.status == "failed"
    assert result.message == "organized_file_missing"


def test_undo_reports_a_conflict_instead_of_overwriting(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, original, organized = organize_one(organizer, downloads_dir)
    original.write_bytes(b"a new download with the same name")

    result = undo.undo(operation_id)
    assert result.status == "conflict"
    assert result.conflict is True
    assert organized.exists()
    assert original.read_bytes() == b"a new download with the same name"


def test_undo_with_rename_policy_restores_beside_the_existing_file(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, original, organized = organize_one(organizer, downloads_dir)
    original.write_bytes(b"occupier")

    result = undo.undo(operation_id, on_conflict="rename")
    assert result.status == "undone"
    restored = Path(result.restored_path)
    assert restored.name == "photo (1).jpg"
    assert restored.read_bytes() == b"payload"
    assert original.read_bytes() == b"occupier"


def test_undo_fails_cleanly_when_original_directory_is_missing(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, original, organized = organize_one(organizer, downloads_dir)
    original.parent.rmdir()

    result = undo.undo(operation_id)
    assert result.status == "failed"
    assert result.message == "original_directory_missing"
    # The organized copy must never be deleted just because undo failed.
    assert organized.exists()


def test_can_undo_for_unknown_operation(undo: UndoManager) -> None:
    ok, reason = undo.can_undo(9999)
    assert ok is False
    assert reason == "operation_not_found"


def test_conflict_for_detects_occupied_target(
    organizer: Organizer, configured, undo: UndoManager, downloads_dir: Path
) -> None:
    operation_id, original, _organized = organize_one(organizer, downloads_dir)
    assert undo.conflict_for(operation_id) is False
    original.write_bytes(b"x")
    assert undo.conflict_for(operation_id) is True
