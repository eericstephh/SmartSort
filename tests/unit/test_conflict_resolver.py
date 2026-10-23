"""Filename sanitising and conflict resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsort.app.core.conflict_resolver import (
    ConflictResolver,
    candidate_names,
    sanitize_filename,
    split_name,
    unique_path,
)


def test_candidate_names_sequence() -> None:
    names = list(candidate_names("photo.jpg"))[:4]
    assert names == ["photo.jpg", "photo (1).jpg", "photo (2).jpg", "photo (3).jpg"]


def test_candidate_names_without_suffix() -> None:
    names = list(candidate_names("README"))[:3]
    assert names == ["README", "README (1)", "README (2)"]


def test_candidate_names_multi_suffix() -> None:
    names = list(candidate_names("backup.tar.gz"))[:2]
    assert names == ["backup.tar.gz", "backup.tar (1).gz"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("photo.jpg", "photo.jpg"),
        ("with space.txt", "with space.txt"),
        ("a<b>c.txt", "a_b_c.txt"),
        ("pipe|name.txt", "pipe_name.txt"),
        ("question?.txt", "question_.txt"),
        ('quote"x.txt', "quote_x.txt"),
        ("trailing.  ", "trailing"),
        ("", "download"),
        ("..", "download"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_strips_directories() -> None:
    assert sanitize_filename(r"..\..\windows\system32\evil.dll") == "evil.dll"
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_reserved_device_names() -> None:
    assert sanitize_filename("CON.txt") == "_CON.txt"
    assert sanitize_filename("nul") == "_nul"


def test_sanitize_truncates_long_names() -> None:
    result = sanitize_filename("a" * 400 + ".txt")
    assert len(result) <= 255
    assert result.endswith(".txt")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("photo.jpg", ("photo", ".jpg")),
        ("archive.tar.gz", ("archive.tar", ".gz")),
        ("README", ("README", "")),
        (".bashrc", (".bashrc", "")),
    ],
)
def test_split_name(name: str, expected: tuple[str, str]) -> None:
    assert split_name(name) == expected


def test_unique_path_skips_existing(tmp_path: Path) -> None:
    (tmp_path / "photo.jpg").write_text("a")
    (tmp_path / "photo (1).jpg").write_text("b")
    assert unique_path(tmp_path, "photo.jpg").name == "photo (2).jpg"


def test_unique_path_returns_first_when_free(tmp_path: Path) -> None:
    assert unique_path(tmp_path, "photo.jpg").name == "photo.jpg"


def test_conflict_resolver_wrapper(tmp_path: Path) -> None:
    resolver = ConflictResolver()
    (tmp_path / "a.txt").write_text("x")
    assert resolver.resolve(tmp_path, "a.txt").name == "a (1).txt"
    assert len(list(resolver.candidates(tmp_path, "a.txt"))) > 1
