"""Scanning an existing folder.

The scanner must be read-only, must explain why a file is not offered, and must
preview the same target the real move would use.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from smartsort.app.core.download_manager import DownloadManager
from smartsort.app.core.folder_scanner import (
    REASON_EMPTY,
    REASON_HIDDEN,
    REASON_IN_DESTINATION,
    REASON_PROTECTED,
    REASON_TEMPORARY,
    FolderScanner,
)
from smartsort.app.core.organizer import Organizer
from smartsort.app.storage.repositories import Repositories
from tests.conftest import make_file


@pytest.fixture
def scanner(
    organizer: Organizer, repos: Repositories, configured, destination: Path
) -> FolderScanner:
    return FolderScanner(organizer, repos, configured)


def _names(result) -> list[str]:
    return [item.name for item in result.items]


def test_system_folder_files_are_not_offered(
    scanner: FolderScanner, tmp_path: Path, monkeypatch
) -> None:
    """The preview must not promise a move the organizer will refuse."""
    fake_windows = tmp_path / "FakeWin"
    fake_windows.mkdir()
    make_file(fake_windows, "system32.dll")
    monkeypatch.setenv("SystemRoot", str(fake_windows))

    result = scanner.scan(fake_windows)

    item = result.items[0]
    assert item.actionable is False
    assert item.reason == REASON_PROTECTED


def test_scan_lists_files_with_category_and_target(
    scanner: FolderScanner, downloads_dir: Path, destination: Path
):
    make_file(downloads_dir, "photo.jpg")
    make_file(downloads_dir, "report.pdf")

    result = scanner.scan(downloads_dir)

    assert sorted(_names(result)) == ["photo.jpg", "report.pdf"]
    assert result.error is None
    by_name = {item.name: item for item in result.items}
    assert by_name["photo.jpg"].category == "images"
    assert by_name["report.pdf"].category == "documents"
    assert by_name["photo.jpg"].target_dir is not None
    assert str(by_name["photo.jpg"].target_dir).startswith(str(destination))
    assert all(item.actionable for item in result.items)


def test_unknown_extension_is_classified_as_other(
    scanner: FolderScanner, downloads_dir: Path
):
    make_file(downloads_dir, "mystery.zzz")

    result = scanner.scan(downloads_dir)

    assert result.items[0].category == "other"
    assert result.items[0].category_name == "Other"


@pytest.mark.parametrize("name", ["movie.mp4.crdownload", "archive.zip.part", "x.tmp"])
def test_temporary_files_are_not_offered(
    scanner: FolderScanner, downloads_dir: Path, name: str
):
    make_file(downloads_dir, name)

    result = scanner.scan(downloads_dir)

    assert result.actionable == []
    assert result.items[0].reason == REASON_TEMPORARY


@pytest.mark.parametrize("name", [".hidden.txt", "~$budget.xlsx"])
def test_hidden_files_are_not_offered(
    scanner: FolderScanner, downloads_dir: Path, name: str
):
    make_file(downloads_dir, name)

    result = scanner.scan(downloads_dir)

    assert result.items[0].reason == REASON_HIDDEN


def test_empty_files_are_not_offered(scanner: FolderScanner, downloads_dir: Path):
    make_file(downloads_dir, "empty.pdf", b"")

    result = scanner.scan(downloads_dir)

    assert result.items[0].reason == REASON_EMPTY


def test_files_inside_the_destination_are_not_offered(
    scanner: FolderScanner, destination: Path
):
    make_file(destination, "already-here.jpg")

    result = scanner.scan(destination)

    assert result.items[0].reason == REASON_IN_DESTINATION


def test_scan_never_moves_anything(
    scanner: FolderScanner,
    downloads_dir: Path,
    repos: Repositories,
    destination: Path,
):
    source = make_file(downloads_dir, "photo.jpg")

    scanner.scan(downloads_dir)

    assert source.exists(), "scanning must not touch the file"
    assert not any(destination.rglob("*.jpg")), "scanning must not copy the file"
    assert repos.operations.count() == 0, "scanning must not write history"


def test_scan_is_not_recursive_by_default(
    scanner: FolderScanner, downloads_dir: Path
):
    make_file(downloads_dir, "top.pdf")
    make_file(downloads_dir / "nested", "deep.pdf")

    result = scanner.scan(downloads_dir)

    assert _names(result) == ["top.pdf"]


def test_scan_can_include_subfolders(scanner: FolderScanner, downloads_dir: Path):
    make_file(downloads_dir, "top.pdf")
    make_file(downloads_dir / "nested", "deep.pdf")

    result = scanner.scan(downloads_dir, recursive=True)

    assert sorted(_names(result)) == ["deep.pdf", "top.pdf"]


def test_recursive_scan_skips_the_destination_subtree(
    organizer: Organizer, repos: Repositories, configured, downloads_dir: Path
):
    inner_destination = downloads_dir / "SmartSort"
    configured.destination_dir = str(inner_destination)
    make_file(downloads_dir, "real.pdf")
    make_file(inner_destination / "2026-03-04", "already-organized.jpg")

    scanner = FolderScanner(organizer, repos, configured)
    result = scanner.scan(downloads_dir, recursive=True)

    names = _names(result)
    assert "real.pdf" in names
    assert "already-organized.jpg" not in names, "the walk must not re-scan its own output"


def test_missing_folder_reports_an_error(
    scanner: FolderScanner, tmp_path: Path
):
    result = scanner.scan(tmp_path / "does-not-exist")

    assert result.error == "folder_missing"
    assert result.items == []


def test_results_are_sorted_newest_first(
    scanner: FolderScanner, downloads_dir: Path
):
    old = make_file(downloads_dir, "old.pdf")
    new = make_file(downloads_dir, "new.pdf")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_750_000_000, 1_750_000_000))

    result = scanner.scan(downloads_dir)

    assert _names(result) == ["new.pdf", "old.pdf"]


def test_preview_matches_the_real_organize_target(
    scanner: FolderScanner,
    organizer: Organizer,
    repos: Repositories,
    configured,
    downloads_dir: Path,
):
    source = make_file(downloads_dir, "photo.jpg")
    stamp = datetime(2026, 3, 4, 9, 30).timestamp()
    os.utime(source, (stamp, stamp))

    item = scanner.scan(downloads_dir).items[0]
    assert item.target_dir is not None

    manager = DownloadManager(organizer, repos, configured)
    outcome = manager.organize_manually(str(source), completed_at=item.modified_at)

    assert outcome.status == "organized"
    assert Path(outcome.final_path).parent == item.target_dir
    assert Path(outcome.final_path).name == "photo.jpg"
    # The date folder comes from the file's own timestamp, not from today.
    assert "2026-03-04" in str(outcome.final_path)


def test_without_a_destination_there_is_no_target(
    organizer: Organizer, repos: Repositories, settings, downloads_dir: Path
):
    make_file(downloads_dir, "photo.jpg")
    bare = FolderScanner(organizer, repos, settings)

    result = bare.scan(downloads_dir)

    assert result.items[0].target_dir is None
    assert result.items[0].actionable, "classification still works without a destination"
