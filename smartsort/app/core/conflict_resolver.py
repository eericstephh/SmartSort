"""Filename sanitising and non-destructive conflict resolution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

# Characters that are illegal in Windows file names.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
MAX_NAME_LENGTH = 255
_DEFAULT_STEM = "download"


def sanitize_filename(name: str, fallback: str = _DEFAULT_STEM) -> str:
    """Return a file name that is safe to create on Windows.

    This treats the incoming name as untrusted: path separators, control
    characters, reserved device names and trailing dots/spaces are all removed
    so that a crafted browser message cannot escape the destination directory.
    """
    if not name:
        return fallback
    # Keep only the last path component regardless of separator style.
    candidate = str(name).replace("\\", "/").split("/")[-1]
    candidate = _ILLEGAL_CHARS.sub("_", candidate).strip()
    candidate = candidate.rstrip(". ")
    if not candidate or candidate in {".", ".."}:
        return fallback
    stem, suffix = split_name(candidate)
    if stem.lower() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    if len(stem) + len(suffix) > MAX_NAME_LENGTH:
        keep = max(1, MAX_NAME_LENGTH - len(suffix))
        stem = stem[:keep]
    return f"{stem}{suffix}"


def split_name(name: str) -> tuple[str, str]:
    """Split ``name`` into (stem, suffix) keeping dotfiles intact."""
    if not name:
        return "", ""
    if name in {".", ".."}:
        return name, ""
    dot = name.rfind(".")
    if dot <= 0:  # no dot, or a leading dot such as ".gitignore"
        return name, ""
    stem, suffix = name[:dot], name[dot:]
    if not stem:
        return name, ""
    return stem, suffix


def candidate_names(name: str, limit: int = 2000) -> Iterator[str]:
    """Yield ``name``, ``name (1)``, ``name (2)`` ... in order."""
    yield name
    stem, suffix = split_name(name)
    for index in range(1, limit + 1):
        yield f"{stem} ({index}){suffix}"


def iter_candidates(directory: Path, name: str, limit: int = 2000) -> Iterator[Path]:
    directory = Path(directory)
    for candidate in candidate_names(name, limit):
        yield directory / candidate


def unique_path(directory: Path, name: str, limit: int = 2000) -> Path:
    """Return the first non-existing candidate path (does not create it)."""
    directory = Path(directory)
    for candidate in candidate_names(name, limit):
        path = directory / candidate
        if not path.exists():
            return path
    raise FileExistsError(f"no free name for {name} in {directory}")


class ConflictResolver:
    """Thin object wrapper so the organizer can be given a policy."""

    def __init__(self, limit: int = 2000) -> None:
        self._limit = limit

    def resolve(self, directory: Path, name: str) -> Path:
        return unique_path(directory, name, self._limit)

    def candidates(self, directory: Path, name: str) -> Iterator[Path]:
        return iter_candidates(directory, name, self._limit)
