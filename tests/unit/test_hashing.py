"""The SHA-256 helper behind duplicate detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

from smartsort.app.core.hashing import sha256_file


def test_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    payload = b"hello world"
    path.write_bytes(payload)
    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_empty_file_hashes_the_empty_string(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()


def test_reads_across_chunk_boundaries(tmp_path: Path) -> None:
    # A chunk size that does not divide the file length exercises the partial
    # final block, which is where a naive implementation loses bytes.
    payload = bytes(range(256)) * 40
    path = tmp_path / "chunked.bin"
    path.write_bytes(payload)
    assert sha256_file(path, chunk_size=7) == hashlib.sha256(payload).hexdigest()


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert sha256_file(tmp_path / "absent.bin") is None


def test_a_directory_returns_none(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    assert sha256_file(folder) is None


def test_identical_content_hashes_identically(tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")
    assert sha256_file(first) == sha256_file(second)


def test_different_content_hashes_differently(tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytez")
    assert sha256_file(first) != sha256_file(second)
