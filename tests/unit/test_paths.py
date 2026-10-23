"""Where the application keeps its state."""

from __future__ import annotations

import sys
from pathlib import Path

from smartsort.app.config import paths


def _as_portable(monkeypatch, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / paths.PORTABLE_MARKER).write_text("SmartSort portable copy", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "SmartSort.exe"))
    monkeypatch.delenv("SMARTSORT_DATA_DIR", raising=False)
    return folder.resolve()


def test_portable_marker_keeps_state_beside_the_executable(tmp_path, monkeypatch) -> None:
    folder = _as_portable(monkeypatch, tmp_path / "SmartSort")

    assert paths.is_portable()
    assert paths.app_data_dir() == folder / "data"
    assert paths.db_path() == folder / "data" / "smartsort.db"
    assert paths.log_file() == folder / "data" / "logs" / "smartsort.log"


def test_without_the_marker_state_goes_to_localappdata(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "SmartSort"
    folder.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "SmartSort.exe"))
    monkeypatch.delenv("SMARTSORT_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert not paths.is_portable()
    assert paths.app_data_dir() == tmp_path / "Local" / "SmartSort"


def test_data_dir_override_wins_over_the_marker(tmp_path, monkeypatch) -> None:
    _as_portable(monkeypatch, tmp_path / "SmartSort")
    monkeypatch.setenv("SMARTSORT_DATA_DIR", str(tmp_path / "elsewhere"))

    assert paths.app_data_dir() == tmp_path / "elsewhere"


def test_a_source_checkout_is_never_portable(tmp_path, monkeypatch) -> None:
    """Running from source must not create a data folder in the repository."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    (tmp_path / paths.PORTABLE_MARKER).write_text("x", encoding="utf-8")
    monkeypatch.delenv("SMARTSORT_DATA_DIR", raising=False)

    assert paths.portable_dir() is None
