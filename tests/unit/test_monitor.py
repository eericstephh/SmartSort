"""Fallback folder watcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsort.app.services.filesystem_monitor import DownloadFolderWatcher
from tests.conftest import make_file


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def watcher_factory(tmp_path: Path, clock: Clock):
    def build(**kwargs) -> tuple[DownloadFolderWatcher, list[Path]]:
        ready: list[Path] = []
        watcher = DownloadFolderWatcher(
            kwargs.pop("directory", tmp_path),
            ready.append,
            clock=clock,
            **kwargs,
        )
        return watcher, ready

    return build


def test_file_is_reported_only_after_it_settles(
    tmp_path: Path, watcher_factory, clock: Clock
) -> None:
    watcher, ready = watcher_factory(settle_seconds=3.0)
    source = make_file(tmp_path, "a.txt", b"x")

    assert watcher.scan_once() == []
    clock.now = 1.0
    assert watcher.scan_once() == []
    clock.now = 4.0
    assert watcher.scan_once() == [source]
    assert ready == [source]


def test_growing_file_resets_the_timer(
    tmp_path: Path, watcher_factory, clock: Clock
) -> None:
    watcher, ready = watcher_factory(settle_seconds=3.0)
    source = make_file(tmp_path, "big.bin", b"x")

    watcher.scan_once()
    clock.now = 1.0
    source.write_bytes(b"x" * 5000)  # size changed
    assert watcher.scan_once() == []
    clock.now = 3.0
    assert watcher.scan_once() == []
    clock.now = 5.0
    assert watcher.scan_once() == [source]


def test_temporary_suffixes_are_ignored(tmp_path: Path, watcher_factory, clock: Clock) -> None:
    watcher, ready = watcher_factory(settle_seconds=0.0)
    make_file(tmp_path, "movie.mp4.crdownload")
    make_file(tmp_path, "archive.zip.part")
    clock.now = 10.0
    assert watcher.scan_once() == []
    assert ready == []


def test_zero_byte_files_are_ignored(tmp_path: Path, watcher_factory, clock: Clock) -> None:
    watcher, ready = watcher_factory(settle_seconds=0.0)
    make_file(tmp_path, "empty.txt", b"")
    clock.now = 10.0
    assert watcher.scan_once() == []
    assert ready == []


def test_files_in_the_destination_are_ignored(
    tmp_path: Path, watcher_factory, clock: Clock
) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    nested = destination / "2026-10-21" / "Images"
    nested.mkdir(parents=True)
    make_file(nested, "photo.jpg")

    watcher, ready = watcher_factory(settle_seconds=0.0, destination=destination)
    clock.now = 10.0
    assert watcher.scan_once() == []
    assert ready == []


def test_hidden_files_are_ignored(tmp_path: Path, watcher_factory, clock: Clock) -> None:
    watcher, ready = watcher_factory(settle_seconds=0.0)
    make_file(tmp_path, ".hidden")
    make_file(tmp_path, "~$lock.docx")
    clock.now = 10.0
    assert watcher.scan_once() == []
    assert ready == []


def test_a_file_is_reported_once(tmp_path: Path, watcher_factory, clock: Clock) -> None:
    watcher, ready = watcher_factory(settle_seconds=0.0)
    source = make_file(tmp_path, "a.txt", b"x")
    clock.now = 10.0
    assert watcher.scan_once() == []  # first sighting only records the file
    clock.now = 20.0
    assert watcher.scan_once() == [source]
    clock.now = 30.0
    assert watcher.scan_once() == []
    assert ready == [source]


def test_missing_directory_is_tolerated(tmp_path: Path, watcher_factory, clock: Clock) -> None:
    watcher, ready = watcher_factory(directory=tmp_path / "does-not-exist", settle_seconds=0.0)
    assert watcher.scan_once() == []
    assert ready == []


def test_reset_clears_state(tmp_path: Path, watcher_factory, clock: Clock) -> None:
    watcher, ready = watcher_factory(settle_seconds=0.0)
    source = make_file(tmp_path, "a.txt", b"x")
    clock.now = 10.0
    watcher.scan_once()
    clock.now = 20.0
    assert watcher.scan_once() == [source]
    watcher.reset()
    clock.now = 30.0
    assert watcher.scan_once() == []
    clock.now = 40.0
    assert watcher.scan_once() == [source]
