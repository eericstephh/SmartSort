"""Logging setup, diagnostics collection and backups."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config.defaults import APP_NAME, APP_VERSION, NATIVE_HOST_NAME

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_PROFILE_PLACEHOLDER = "%USERPROFILE%"


def _profile_prefix() -> str | None:
    """The current user's profile directory, used for redaction."""
    value = os.environ.get("USERPROFILE")
    if value:
        return value.rstrip("\\/")
    try:
        return str(Path.home()).rstrip("\\/")
    except RuntimeError:  # pragma: no cover - environmental
        return None


def redact_paths(text: str) -> str:
    """Replace the user's profile directory with ``%USERPROFILE%``.

    On-disk logs keep full paths because diagnosis needs them; this is applied
    only to copies that leave the machine, so a shared diagnostics archive does
    not disclose the account name.
    """
    prefix = _profile_prefix()
    if not prefix or prefix not in text:
        return text
    return text.replace(prefix, _PROFILE_PLACEHOLDER)


def _redact_database(path: Path) -> None:
    """Rewrite profile paths inside a copy of the history database."""
    prefix = _profile_prefix()
    if not prefix:
        return
    import sqlite3

    try:
        connection = sqlite3.connect(str(path))
    except sqlite3.Error:  # pragma: no cover - environmental
        return
    try:
        for table, columns in (
            ("operations", ("original_path", "final_path")),
            ("processed_items", ("source_path", "final_path")),
        ):
            for column in columns:
                # Table and column names are literals from the tuple above, not
                # user input; only the values are parameterised.
                sql = (
                    f"UPDATE {table} SET {column} = REPLACE({column}, ?, ?)"
                    f" WHERE {column} LIKE ?"
                )
                try:
                    connection.execute(sql, (prefix, _PROFILE_PLACEHOLDER, f"%{prefix}%"))
                except sqlite3.Error:  # pragma: no cover - environmental
                    continue
        connection.commit()
    finally:
        connection.close()


def setup_logging(log_file: Path, *, level: int = logging.INFO, console: bool = False) -> Path:
    """Configure rotating file logging. Returns the log file path."""
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    if console or not getattr(sys, "frozen", False):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(stream)

    logging.getLogger("smartsort").info("%s %s starting", APP_NAME, APP_VERSION)
    return log_file


def collect_diagnostics(
    *,
    data_dir: Path,
    db_path: Path,
    log_file: Path,
    settings: dict[str, Any] | None = None,
    db_info: dict[str, Any] | None = None,
    browser_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gather environment information for troubleshooting. Never sent anywhere."""
    info: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "application": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "frozen": bool(getattr(sys, "frozen", False)),
            "native_host_name": NATIVE_HOST_NAME,
        },
        "environment": {
            "platform": platform.platform(),
            "windows_version": platform.version(),
            "python": platform.python_version(),
            "executable": sys.executable,
            "architecture": platform.machine(),
        },
        "paths": {
            "data_dir": str(data_dir),
            "database": str(db_path),
            "log_file": str(log_file),
        },
    }
    if settings is not None:
        info["settings"] = settings
    if db_info is not None:
        info["database"] = db_info
    if browser_status is not None:
        info["browser_integration"] = browser_status
    return info


def export_diagnostics(
    destination: Path,
    *,
    data_dir: Path,
    log_file: Path,
    diagnostics: dict[str, Any],
    include_database: bool = True,
    db_path: Path | None = None,
) -> Path:
    """Write a zip archive with logs, diagnostics and (optionally) the database."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            redact_paths(json.dumps(diagnostics, indent=2, ensure_ascii=False)),
        )
        if log_file.exists():
            for candidate in [log_file, *sorted(log_file.parent.glob(log_file.name + ".*"))]:
                if not candidate.is_file():
                    continue
                try:
                    text = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:  # pragma: no cover - environmental
                    continue
                archive.writestr(f"logs/{candidate.name}", redact_paths(text))
        if include_database and db_path and db_path.exists():
            temp_copy = destination.parent / f".{destination.stem}-db.tmp"
            try:
                src = __import__("sqlite3").connect(str(db_path))
                dst = __import__("sqlite3").connect(str(temp_copy))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                _redact_database(temp_copy)
                archive.write(temp_copy, arcname="data/smartsort.db")
            except Exception:  # pragma: no cover - environmental
                logger.warning("could not include the database in the export", exc_info=True)
            finally:
                try:
                    temp_copy.unlink(missing_ok=True)
                except OSError:
                    pass
        readme = (
            "SmartSort diagnostics export\n"
            "============================\n\n"
            "This archive was created on your request and contains local log files,\n"
            "application settings and optionally a copy of the history database.\n"
            "It may contain file paths from your computer, but your Windows profile\n"
            f"directory has been replaced with {_PROFILE_PLACEHOLDER}.\n"
            "Nothing in this archive was uploaded anywhere - SmartSort has no\n"
            "telemetry. Review it before sharing.\n"
        )
        archive.writestr("README.txt", readme)
    return destination


def backup_state(destination: Path, *, db_path: Path, settings_json: Path | None = None) -> Path:
    """Create a restorable backup of settings and history."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    temp_copy = destination.parent / f".{destination.stem}-tmp.db"
    try:
        import sqlite3

        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(temp_copy))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        if settings_json and settings_json.exists():
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(temp_copy, arcname="smartsort.db")
                archive.write(settings_json, arcname="settings.json")
        else:
            shutil.copy2(temp_copy, destination)
    finally:
        try:
            temp_copy.unlink(missing_ok=True)
        except OSError:
            pass
    return destination
