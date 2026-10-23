"""Crash-safe move primitives."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from smartsort.app.core import fileops
from smartsort.app.core.fileops import (
    MoveError,
    is_within,
    restore_move,
    safe_move,
    same_volume,
)


def test_is_within_true_for_child(tmp_path: Path) -> None:
    child = tmp_path / "a" / "b" / "file.txt"
    assert is_within(child, tmp_path) is True


def test_is_within_true_for_same_path(tmp_path: Path) -> None:
    assert is_within(tmp_path, tmp_path) is True


def test_is_within_false_for_sibling(tmp_path: Path) -> None:
    other = tmp_path.parent / "elsewhere"
    assert is_within(other, tmp_path) is False


def test_is_within_resolves_dotdot(tmp_path: Path) -> None:
    escaped = tmp_path / "a" / ".." / ".." / "outside"
    assert is_within(escaped, tmp_path / "a") is False


def test_same_volume_for_files_in_one_directory(tmp_path: Path) -> None:
    assert same_volume(tmp_path / "x.txt", tmp_path) is True


def test_safe_move_renames_without_copy(tmp_path: Path) -> None:
    source = tmp_path / "in" / "file.txt"
    source.parent.mkdir()
    source.write_bytes(b"hello")
    target_dir = tmp_path / "out"
    target_dir.mkdir()

    outcome = safe_move(source, target_dir, "file.txt")
    assert outcome.mode == "rename"
    assert outcome.final_path.read_bytes() == b"hello"
    assert not source.exists()


def test_safe_move_never_overwrites(tmp_path: Path) -> None:
    target_dir = tmp_path / "out"
    target_dir.mkdir()
    (target_dir / "file.txt").write_bytes(b"original")

    source = tmp_path / "file.txt"
    source.write_bytes(b"new")

    outcome = safe_move(source, target_dir, "file.txt")
    assert outcome.final_path.name == "file (1).txt"
    assert (target_dir / "file.txt").read_bytes() == b"original"
    assert outcome.final_path.read_bytes() == b"new"


def test_safe_move_cross_volume_copies_then_removes_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    source = tmp_path / "in" / "movie.bin"
    source.parent.mkdir()
    payload = os.urandom(1024 * 300)
    source.write_bytes(payload)
    target_dir = tmp_path / "out"
    target_dir.mkdir()

    outcome = safe_move(source, target_dir, "movie.bin")
    assert outcome.mode == "copy"
    assert outcome.final_path.read_bytes() == payload
    assert not source.exists()


def test_cross_volume_conflict_keeps_both_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    target_dir = tmp_path / "out"
    target_dir.mkdir()
    (target_dir / "movie.bin").write_bytes(b"existing")

    source = tmp_path / "movie.bin"
    source.write_bytes(b"incoming")

    outcome = safe_move(source, target_dir, "movie.bin")
    assert outcome.final_path.name == "movie (1).bin"
    assert (target_dir / "movie.bin").read_bytes() == b"existing"
    assert not source.exists()


def test_cross_volume_disk_full_preserves_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    monkeypatch.setattr(fileops, "free_space", lambda path: 0)
    source = tmp_path / "big.bin"
    source.write_bytes(b"x" * 1024)
    target_dir = tmp_path / "out"
    target_dir.mkdir()

    with pytest.raises(MoveError) as info:
        safe_move(source, target_dir, "big.bin")
    assert info.value.code == "disk_full"
    assert source.exists()
    assert list(target_dir.iterdir()) == []


def test_permission_error_preserves_source(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "locked.txt"
    source.write_bytes(b"data")
    target_dir = tmp_path / "out"
    target_dir.mkdir()

    real_rename = os.rename

    def failing_rename(src, dst):
        if str(src).endswith("locked.txt"):
            raise PermissionError(13, "access denied")
        return real_rename(src, dst)

    monkeypatch.setattr(fileops.os, "rename", failing_rename)
    with pytest.raises(MoveError) as info:
        safe_move(source, target_dir, "locked.txt")
    assert info.value.code == "permission_denied"
    assert source.exists()


def test_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(MoveError) as info:
        safe_move(tmp_path / "nope.txt", tmp_path, "nope.txt")
    assert info.value.code == "source_missing"


def test_cross_volume_leaves_no_temp_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    source = tmp_path / "partial.bin"
    source.write_bytes(b"12345")
    target_dir = tmp_path / "out"
    target_dir.mkdir()

    safe_move(source, target_dir, "partial.bin")
    leftovers = [p.name for p in target_dir.iterdir() if p.name.startswith(".smartsort-")]
    assert leftovers == []
    assert (target_dir / "partial.bin").read_bytes() == b"12345"


def test_copy_failure_midway_removes_temp_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fileops, "same_volume", lambda a, b: False)
    source = tmp_path / "boom.bin"
    source.write_bytes(b"x" * 4096)
    target_dir = tmp_path / "out"
    target_dir.mkdir()

    class Exploding:
        def __init__(self, handle):
            self._handle = handle

        def read(self, size=-1):
            raise OSError(28, "No space left on device")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._handle.close()

    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if "b" in mode and "x" not in mode and str(path).endswith("boom.bin"):
            return Exploding(handle)
        return handle

    monkeypatch.setattr(fileops, "open", fake_open, raising=False)
    with pytest.raises(MoveError) as info:
        safe_move(source, target_dir, "boom.bin")
    assert info.value.code == "disk_full"
    assert source.exists()
    leftovers = [p.name for p in target_dir.iterdir() if p.name.startswith(".smartsort-")]
    assert leftovers == []


def test_restore_move_returns_file(tmp_path: Path) -> None:
    original = tmp_path / "Downloads" / "file.txt"
    original.parent.mkdir()
    organized = tmp_path / "SmartSort" / "2026-10-21" / "Documents" / "file.txt"
    organized.parent.mkdir(parents=True)
    organized.write_bytes(b"payload")

    outcome = restore_move(organized, original)
    assert outcome.final_path == original
    assert original.read_bytes() == b"payload"
    assert not organized.exists()


def test_restore_move_refuses_to_overwrite(tmp_path: Path) -> None:
    original = tmp_path / "Downloads" / "file.txt"
    original.parent.mkdir()
    original.write_bytes(b"already here")
    organized = tmp_path / "SmartSort" / "file.txt"
    organized.parent.mkdir()
    organized.write_bytes(b"payload")

    with pytest.raises(MoveError) as info:
        restore_move(organized, original)
    assert info.value.code == "target_exists"
    assert organized.exists()
    assert original.read_bytes() == b"already here"


def test_long_path_helper_prefixes_when_needed() -> None:
    long = "C:\\" + "a" * 300 + "\\file.txt"
    result = fileops.long_path(long)
    assert result.startswith("\\\\?\\")


def test_long_path_helper_leaves_short_paths() -> None:
    assert fileops.long_path("C:\\temp\\file.txt") == "C:\\temp\\file.txt"
