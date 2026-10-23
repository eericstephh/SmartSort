"""Filesystem locations used by SmartSort.

All mutable state lives under the per-user local application data directory so
that the application never needs administrator rights.

A **portable** copy is the exception: when ``portable.txt`` sits next to the
executable, state is kept in a ``data`` folder beside it, so the whole directory
can be moved to a USB stick and carry its history with it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .defaults import APP_NAME

_ENV_DATA_DIR = "SMARTSORT_DATA_DIR"
PORTABLE_MARKER = "portable.txt"


def executable_dir() -> Path | None:
    """The folder holding the running executable, when frozen."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except (OSError, RuntimeError):  # pragma: no cover - environmental
        return None


def portable_dir() -> Path | None:
    """The data folder for a portable copy, or ``None`` when not portable."""
    folder = executable_dir()
    if folder is None:
        return None
    if not (folder / PORTABLE_MARKER).is_file():
        return None
    return folder / "data"


def _base_dir() -> Path:
    override = os.environ.get(_ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()
    portable = portable_dir()
    if portable is not None:
        return portable
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / APP_NAME
    # Non-Windows fallback (used by the test-suite and by developers).
    return Path.home() / f".{APP_NAME.lower()}"


def is_portable() -> bool:
    return portable_dir() is not None


def app_data_dir() -> Path:
    return _base_dir()


def db_path() -> Path:
    return app_data_dir() / "smartsort.db"


def log_dir() -> Path:
    return app_data_dir() / "logs"


def log_file() -> Path:
    return log_dir() / "smartsort.log"


def bridge_token_path() -> Path:
    return app_data_dir() / "bridge.token"


def native_host_dir() -> Path:
    return app_data_dir() / "native-host"


def native_manifest_path() -> Path:
    return native_host_dir() / "com.smartsort.host.json"


def backup_dir() -> Path:
    return app_data_dir() / "backups"


def default_downloads_dir() -> Path:
    """Best-effort resolution of the user's Downloads folder."""
    if sys.platform == "win32":
        profile = os.environ.get("USERPROFILE")
        if profile:
            candidate = Path(profile) / "Downloads"
            if candidate.is_dir():
                return candidate
    candidate = Path.home() / "Downloads"
    return candidate


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
