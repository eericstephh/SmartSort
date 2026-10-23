"""Download event policy layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsort.app.core.download_manager import DownloadEvent, DownloadManager
from smartsort.app.core.organizer import Organizer
from tests.conftest import make_file


@pytest.fixture
def manager(organizer: Organizer, repos, settings) -> DownloadManager:
    return DownloadManager(organizer, repos, settings)


def completed(path: Path, **kwargs) -> DownloadEvent:
    kwargs.setdefault("download_id", "1")
    kwargs.setdefault("browser", "chrome")
    return DownloadEvent(kind="download_completed", filename=str(path), **kwargs)


@pytest.mark.parametrize(
    "kind",
    ["download_started", "download_progress", "download_interrupted", "download_cancelled"],
)
def test_unfinished_downloads_are_never_moved(
    manager: DownloadManager, configured, downloads_dir: Path, destination: Path, kind: str
) -> None:
    source = make_file(downloads_dir, "movie.mp4")
    result = manager.handle_event(
        DownloadEvent(kind=kind, download_id="1", browser="chrome", filename=str(source))
    )
    assert result.status == "skipped"
    assert source.exists()
    assert list(destination.rglob("*")) == []


def test_completed_download_is_organized(
    manager: DownloadManager, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "photo.jpg")
    result = manager.handle_event(completed(source))
    assert result.status == "organized"
    assert (destination / "2026-10-21" / "Images" / "photo.jpg").is_file()


def test_paused_manager_skips_events(
    manager: DownloadManager, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "photo.jpg")
    manager.pause()
    result = manager.handle_event(completed(source))
    assert result.status == "skipped"
    assert result.message == "paused"
    assert source.exists()


def test_resume_restores_processing(
    manager: DownloadManager, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "photo.jpg")
    manager.pause()
    manager.resume()
    result = manager.handle_event(completed(source))
    assert result.status == "organized"


def test_browser_reported_missing_file_is_skipped(
    manager: DownloadManager, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "photo.jpg")
    result = manager.handle_event(completed(source, exists=False))
    assert result.status == "skipped"
    assert result.message == "browser_reports_missing_file"
    assert source.exists()


def test_missing_filename_is_skipped(manager: DownloadManager, configured) -> None:
    result = manager.handle_event(
        DownloadEvent(kind="download_completed", download_id="5", browser="chrome")
    )
    assert result.status == "skipped"
    assert result.message == "missing_filename"


def test_unsupported_event_kind(manager: DownloadManager, configured) -> None:
    result = manager.handle_event(DownloadEvent(kind="something_else"))
    assert result.status == "skipped"
    assert result.message == "unsupported_event"


def test_watched_file_is_organized(
    manager: DownloadManager, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "notes.txt")
    result = manager.handle_watched_file(str(source))
    assert result.status == "organized"
    assert (destination / "2026-10-21" / "Documents" / "notes.txt").is_file()


def test_watcher_respects_pause(
    manager: DownloadManager, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "notes.txt")
    manager.pause()
    result = manager.handle_watched_file(str(source))
    assert result.status == "skipped"
    assert source.exists()


def test_manual_organization_works_when_auto_is_off(
    manager: DownloadManager, settings, destination: Path, downloads_dir: Path
) -> None:
    settings.destination_dir = str(destination)
    settings.set("auto_organize", False)
    source = make_file(downloads_dir, "x.pdf")
    result = manager.organize_manually(str(source))
    assert result.status == "organized"


def test_summary_reports_state(manager: DownloadManager, configured) -> None:
    summary = manager.summary()
    assert summary["paused"] is False
    assert summary["auto_organize"] is True
    assert summary["destination"].endswith("SmartSort")
