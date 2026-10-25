"""Upgrading a database written by an earlier version.

Users already have a version 1 database; the schema change for duplicate
detection must add its columns without touching the history that is in there.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from smartsort.app.storage import migrations
from smartsort.app.storage.database import Database


def _build_v1_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        assert migrations.apply(conn, target=1) == 1
        conn.execute(
            "INSERT INTO operations (origin, category, original_path, final_path,"
            " size_bytes, organized_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "browser",
                "images",
                "C:/Downloads/holiday.jpg",
                "D:/SmartSort/2026-10-20/Images/holiday.jpg",
                1234,
                "2026-10-20T10:00:00+00:00",
                "organized",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_v1_database_upgrades_and_keeps_its_history(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _build_v1_database(path)

    db = Database(path).open()
    try:
        assert db.scalar("PRAGMA user_version") == 2
        rows = db.query("SELECT * FROM operations")
        assert len(rows) == 1
        assert rows[0]["original_path"] == "C:/Downloads/holiday.jpg"
        assert rows[0]["content_hash"] is None
        assert rows[0]["duplicate_of"] is None
    finally:
        db.close()


def test_the_new_columns_are_queryable(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _build_v1_database(path)

    db = Database(path).open()
    try:
        columns = {row["name"] for row in db.query("PRAGMA table_info(operations)")}
        assert {"content_hash", "duplicate_of"} <= columns
        # The column exists and is selectable, not just listed in the schema.
        assert len(db.query("SELECT content_hash FROM operations")) == 1
    finally:
        db.close()
