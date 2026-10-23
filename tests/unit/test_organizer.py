"""Organization engine behaviour."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from smartsort.app.core import fileops
from smartsort.app.core.organizer import Organizer
from smartsort.app.storage.models import OrganizeRequest
from tests.conftest import make_file


def request(path: Path, **kwargs) -> OrganizeRequest:
    kwargs.setdefault("origin", "browser")
    return OrganizeRequest(source_path=str(path), **kwargs)


def test_creates_date_and_category_folders(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "photo.jpg", b"jpeg-bytes")
    result = organizer.organize(request(source))

    assert result.status == "organized"
    assert result.category == "images"
    expected = destination / "2026-10-21" / "Images" / "photo.jpg"
    assert expected.is_file()
    assert expected.read_bytes() == b"jpeg-bytes"
    assert not source.exists()


def test_uses_completion_date_not_modification_date(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "report.pdf")
    old = datetime(2020, 1, 1, 10, 0).timestamp()
    os.utime(source, (old, old))

    result = organizer.organize(
        request(source, completed_at=datetime(2026, 10, 19, 23, 30))
    )
    assert result.status == "organized"
    assert (destination / "2026-10-19" / "Documents" / "report.pdf").is_file()


def test_timezone_aware_completion_time_is_converted_to_local_date(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "clip.mp4")
    completed = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    expected_day = completed.astimezone().date().isoformat()

    organizer.organize(request(source, completed_at=completed))
    assert (destination / expected_day / "Videos" / "clip.mp4").is_file()


def test_conflict_creates_numbered_copy(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    target_dir = destination / "2026-10-21" / "Images"
    target_dir.mkdir(parents=True)
    (target_dir / "photo.jpg").write_bytes(b"first")

    source = make_file(downloads_dir, "photo.jpg", b"second")
    result = organizer.organize(request(source))

    assert result.status == "organized"
    assert Path(result.final_path).name == "photo (1).jpg"
    assert (target_dir / "photo.jpg").read_bytes() == b"first"
    assert (target_dir / "photo (1).jpg").read_bytes() == b"second"


def test_refuses_file_still_downloading(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "movie.mp4.crdownload")
    result = organizer.organize(request(source))

    assert result.status == "skipped"
    assert result.message == "file_still_downloading"
    assert source.exists()
    assert list(destination.rglob("*")) == []


def test_skips_file_already_inside_destination(
    organizer: Organizer, configured, destination: Path
) -> None:
    nested = destination / "2026-10-21" / "Images"
    nested.mkdir(parents=True)
    source = make_file(nested, "photo.jpg")

    result = organizer.organize(request(source))
    assert result.status == "skipped"
    assert result.message == "already_in_destination"
    assert source.exists()


def test_skips_when_destination_is_the_source_directory(
    organizer: Organizer, settings, downloads_dir: Path
) -> None:
    settings.destination_dir = str(downloads_dir)
    source = make_file(downloads_dir, "photo.jpg")

    result = organizer.organize(request(source))
    assert result.status == "skipped"
    assert result.message == "already_in_destination"
    assert source.exists()


def test_missing_source_is_reported_without_creating_folders(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    result = organizer.organize(request(downloads_dir / "ghost.zip"))
    assert result.status == "failed"
    assert result.message == "source_missing"
    assert list(destination.iterdir()) == []


def test_zero_byte_file_is_skipped(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "empty.txt", b"")
    result = organizer.organize(request(source))
    assert result.status == "skipped"
    assert result.message == "empty_file"
    assert source.exists()


def test_duplicate_download_id_is_processed_once(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "setup.exe", b"MZ")
    first = organizer.organize(request(source, download_id="42", browser="chrome"))
    assert first.status == "organized"

    second = organizer.organize(request(source, download_id="42", browser="chrome"))
    assert second.status == "duplicate"
    assert second.message == "already_processed"


def test_watcher_does_not_reprocess_a_browser_download(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "song.mp3")
    first = organizer.organize(request(source, download_id="7", browser="edge"))
    assert first.status == "organized"

    # The watcher would report the same original path.
    second = organizer.organize(
        OrganizeRequest(source_path=str(source), origin="watcher")
    )
    assert second.status == "duplicate"


def test_browser_event_does_not_reprocess_a_watched_file(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "doc.pdf")
    first = organizer.organize(OrganizeRequest(source_path=str(source), origin="watcher"))
    assert first.status == "organized"

    second = organizer.organize(request(source, download_id="99", browser="chrome"))
    assert second.status == "duplicate"


def test_missing_destination_configuration(
    organizer: Organizer, settings, downloads_dir: Path
) -> None:
    settings.destination_dir = ""
    source = make_file(downloads_dir, "a.txt")
    result = organizer.organize(request(source))
    assert result.status == "failed"
    assert result.message == "destination_not_configured"


def test_auto_organize_disabled_skips_browser_events(
    organizer: Organizer, settings, destination: Path, downloads_dir: Path
) -> None:
    settings.destination_dir = str(destination)
    settings.set("auto_organize", False)
    source = make_file(downloads_dir, "a.txt")

    result = organizer.organize(request(source))
    assert result.status == "skipped"
    assert result.message == "auto_organize_disabled"
    assert source.exists()


def test_manual_organization_ignores_the_auto_flag(
    organizer: Organizer, settings, destination: Path, downloads_dir: Path
) -> None:
    settings.destination_dir = str(destination)
    settings.set("auto_organize", False)
    source = make_file(downloads_dir, "a.txt")

    result = organizer.organize(OrganizeRequest(source_path=str(source), origin="manual"))
    assert result.status == "organized"


def test_policy_can_block_moving_browser_downloads(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "a.txt")
    result = organizer.organize(request(source, allow_move=False))
    assert result.status == "skipped"
    assert result.message == "policy_disallows_move"
    assert source.exists()


def test_category_folders_can_be_disabled(
    organizer: Organizer, settings, destination: Path, downloads_dir: Path
) -> None:
    settings.destination_dir = str(destination)
    settings.set("use_category_folders", False)
    source = make_file(downloads_dir, "photo.png")

    result = organizer.organize(request(source))
    assert result.status == "organized"
    assert (destination / "2026-10-21" / "photo.png").is_file()


def test_date_folders_can_be_disabled(
    organizer: Organizer, settings, destination: Path, downloads_dir: Path
) -> None:
    settings.destination_dir = str(destination)
    settings.set("use_date_folders", False)
    source = make_file(downloads_dir, "photo.png")

    result = organizer.organize(request(source))
    assert result.status == "organized"
    assert (destination / "Images" / "photo.png").is_file()


def test_unknown_extension_lands_in_other(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "data.xyz")
    result = organizer.organize(request(source))
    assert result.category == "other"
    assert (destination / "2026-10-21" / "Other" / "data.xyz").is_file()


def test_operation_history_records_both_paths(
    organizer: Organizer, configured, downloads_dir: Path, repos
) -> None:
    source = make_file(downloads_dir, "file.zip", b"zip")
    result = organizer.organize(request(source, download_id="123", browser="chrome"))

    operation = repos.operations.get(result.operation_id)
    assert operation is not None
    assert operation.original_path == str(source)
    assert operation.final_path == result.final_path
    assert operation.category == "archives"
    assert operation.status == "organized"
    assert operation.size_bytes == 3
    assert operation.download_id == "123"
    assert operation.origin == "browser"


def test_failed_move_is_recorded_and_keeps_the_source(
    organizer: Organizer, configured, downloads_dir: Path, repos, monkeypatch
) -> None:
    source = make_file(downloads_dir, "locked.exe", b"MZ")
    real_rename = os.rename

    def failing_rename(src, dst):
        if str(src).endswith("locked.exe"):
            raise PermissionError(13, "in use")
        return real_rename(src, dst)

    monkeypatch.setattr(fileops.os, "rename", failing_rename)
    result = organizer.organize(request(source))

    assert result.status == "failed"
    assert result.message == "permission_denied"
    assert source.exists()
    operation = repos.operations.get(result.operation_id)
    assert operation is not None
    assert operation.status == "failed"
    assert "permission_denied" in (operation.error or "")


def test_cross_volume_move_is_used_when_needed(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path, monkeypatch
) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    source = make_file(downloads_dir, "big.iso", b"x" * 2048)

    result = organizer.organize(request(source))
    assert result.status == "organized"
    assert Path(result.final_path).read_bytes() == b"x" * 2048
    assert not source.exists()


def test_disk_full_during_cross_volume_move_preserves_source(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path, monkeypatch
) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    monkeypatch.setattr(fileops, "free_space", lambda path: 0)
    source = make_file(downloads_dir, "big.iso", b"x" * 4096)

    result = organizer.organize(request(source))
    assert result.status == "failed"
    assert result.message == "disk_full"
    assert source.exists()


def test_concurrent_moves_with_the_same_name_never_collide(
    organizer: Organizer, configured, tmp_path: Path, destination: Path
) -> None:
    results: list[str] = []
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            folder = tmp_path / f"src{index}"
            folder.mkdir()
            source = make_file(folder, "shared.txt", f"payload-{index}".encode())
            result = organizer.organize(request(source))
            results.append(result.final_path or "")
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors
    assert len(results) == 8
    assert len(set(results)) == 8
    target_dir = destination / "2026-10-21" / "Documents"
    assert len(list(target_dir.iterdir())) == 8


def test_sanitises_dangerous_filename_from_browser(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "payload.bin")
    result = organizer.organize(
        request(source, suggested_name="..\\..\\Windows\\evil.exe")
    )
    assert result.status == "organized"
    final = Path(result.final_path)
    assert final.name == "evil.exe"
    assert final.parent == destination / "2026-10-21" / "Installers"


def test_category_change_takes_effect_after_invalidation(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path, repos
) -> None:
    repos.categories.update("documents", extensions=["pdf", "md"])
    organizer.invalidate_classifier()

    source = make_file(downloads_dir, "notes.md")
    result = organizer.organize(request(source))
    assert result.category == "documents"
