"""Schema migrations.

The schema version is tracked with ``PRAGMA user_version`` so that a migration
can be applied with a single, atomic step per version.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

from ..config.defaults import CATEGORY_DEFINITIONS, DEFAULT_SETTINGS, SCHEMA_VERSION

logger = logging.getLogger(__name__)


def _v1(conn: sqlite3.Connection) -> None:
    # Statements are executed one by one (instead of via ``executescript``,
    # which implicitly commits) so the whole migration stays inside the
    # transaction opened by :func:`apply`.
    statements = [
        """
        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS categories (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            enabled    INTEGER NOT NULL DEFAULT 1,
            extensions TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            builtin    INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS operations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            download_id   TEXT,
            origin        TEXT NOT NULL,
            category      TEXT NOT NULL,
            original_path TEXT NOT NULL,
            final_path    TEXT NOT NULL,
            size_bytes    INTEGER NOT NULL DEFAULT 0,
            completed_at  TEXT,
            organized_at  TEXT NOT NULL,
            status        TEXT NOT NULL,
            error         TEXT,
            message       TEXT,
            undo_state    TEXT NOT NULL DEFAULT 'available',
            undo_at       TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_operations_organized_at"
        " ON operations (organized_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_operations_status ON operations (status)",
        "CREATE INDEX IF NOT EXISTS idx_operations_original_path"
        " ON operations (original_path)",
        """
        CREATE TABLE IF NOT EXISTS processed_items (
            key          TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            download_id  TEXT,
            browser      TEXT,
            source_path  TEXT,
            final_path   TEXT,
            processed_at TEXT NOT NULL,
            operation_id INTEGER
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_processed_items_processed_at"
        " ON processed_items (processed_at)",
    ]
    for statement in statements:
        conn.execute(statement)


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _v1),
]


def _seed_categories(conn: sqlite3.Connection) -> None:
    existing = {row["id"] for row in conn.execute("SELECT id FROM categories").fetchall()}
    for order, (cat_id, name, extensions) in enumerate(CATEGORY_DEFINITIONS):
        if cat_id in existing:
            continue
        conn.execute(
            "INSERT INTO categories (id, name, enabled, extensions, sort_order, builtin)"
            " VALUES (?, ?, 1, ?, ?, 1)",
            (cat_id, name, ",".join(extensions), order),
        )


def _seed_settings(conn: sqlite3.Connection) -> None:
    import json

    existing = {row["key"] for row in conn.execute("SELECT key FROM settings").fetchall()}
    for key, value in DEFAULT_SETTINGS.items():
        if key in existing:
            continue
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, json.dumps(value)),
        )


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def apply(conn: sqlite3.Connection, target: int = SCHEMA_VERSION) -> int:
    """Apply every pending migration. Returns the resulting schema version."""
    version = current_version(conn)
    if version > target:
        raise RuntimeError(
            f"database schema version {version} is newer than the supported version {target}"
        )
    for number, step in MIGRATIONS:
        if number <= version:
            continue
        logger.info("applying schema migration %s", number)
        conn.execute("BEGIN IMMEDIATE")
        try:
            step(conn)
            _seed_categories(conn)
            _seed_settings(conn)
            conn.execute(f"PRAGMA user_version = {number}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
        version = number
    return current_version(conn)
