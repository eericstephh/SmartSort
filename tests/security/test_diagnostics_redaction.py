"""Security: diagnostics exports must not disclose the account name."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from smartsort.app.services.logging_service import export_diagnostics, redact_paths


def _home() -> str:
    return os.environ.get("USERPROFILE") or str(Path.home())


def test_redact_paths_replaces_the_profile_directory() -> None:
    home = _home()
    text = f"organized {home}\\Downloads\\invoice.pdf"
    assert redact_paths(text) == "organized %USERPROFILE%\\Downloads\\invoice.pdf"


def test_redact_paths_leaves_other_text_alone() -> None:
    assert redact_paths("nothing to hide") == "nothing to hide"


def test_export_replaces_profile_paths_in_logs_and_database(tmp_path: Path, db) -> None:
    from smartsort.app.storage.repositories import Repositories

    home = _home()
    secret = f"{home}\\Downloads\\private-file.pdf"

    log_file = tmp_path / "logs" / "smartsort.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text(f"2026-01-01 INFO organized {secret} -> D:\\Dest\\a.pdf\n", encoding="utf-8")

    repos = Repositories(db)
    repos.operations.add(
        origin="browser",
        category="documents",
        original_path=secret,
        final_path="D:\\Dest\\a.pdf",
        status="organized",
    )

    archive_path = tmp_path / "export.zip"
    export_diagnostics(
        archive_path,
        data_dir=tmp_path,
        log_file=log_file,
        diagnostics={"log_file": str(log_file), "note": secret},
        db_path=db.path,
    )

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "logs/smartsort.log" in names
        log_text = archive.read("logs/smartsort.log").decode("utf-8")
        diagnostics_text = archive.read("diagnostics.json").decode("utf-8")
        readme = archive.read("README.txt").decode("utf-8")

    assert home not in log_text
    assert "%USERPROFILE%\\Downloads\\private-file.pdf" in log_text
    assert home not in diagnostics_text
    assert "%USERPROFILE%" in readme

    # The database copy is rewritten too, not just the text files.
    with zipfile.ZipFile(archive_path) as archive:
        extracted = tmp_path / "copy.db"
        extracted.write_bytes(archive.read("data/smartsort.db"))

    import sqlite3

    connection = sqlite3.connect(str(extracted))
    try:
        original = connection.execute("SELECT original_path FROM operations").fetchone()[0]
    finally:
        connection.close()
    assert home not in original
    assert original.startswith("%USERPROFILE%")


def test_export_does_not_modify_the_original_database(tmp_path: Path, db) -> None:
    from smartsort.app.storage.repositories import Repositories

    home = _home()
    secret = f"{home}\\Downloads\\keep-me.pdf"
    repos = Repositories(db)
    operation_id = repos.operations.add(
        origin="manual",
        category="documents",
        original_path=secret,
        final_path="D:\\Dest\\keep-me.pdf",
        status="organized",
    )

    export_diagnostics(
        tmp_path / "export.zip",
        data_dir=tmp_path,
        log_file=tmp_path / "missing.log",
        diagnostics={},
        db_path=db.path,
    )

    stored = repos.operations.get(operation_id)
    assert stored is not None
    assert stored.original_path == secret, "redaction must only affect the exported copy"


@pytest.mark.skipif(os.name != "nt", reason="Windows ACLs")
def test_bridge_token_is_readable_only_by_the_current_user(tmp_path: Path) -> None:
    import subprocess

    from smartsort.app.browser.bridge_server import ensure_token

    token_path = tmp_path / "bridge.token"
    ensure_token(token_path)

    completed = subprocess.run(
        ["icacls", str(token_path)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    output = completed.stdout
    assert "BUILTIN\\Users" not in output
    assert "Everyone" not in output
    assert "Users:" not in output
