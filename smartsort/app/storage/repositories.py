"""Repositories: the only place that knows SQL.

Each repository owns one aggregate and never leaks ``sqlite3.Row`` objects to
callers.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from .database import Database
from .models import Category, Operation, dumps, loads

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self._db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        value = loads(row["value"], default)
        return default if value is None else value

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = excluded.updated_at",
            (key, dumps(value), utc_now_iso()),
        )

    def set_many(self, values: dict[str, Any]) -> None:
        with self._db.transaction() as conn:
            now = utc_now_iso()
            conn.executemany(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                [(k, dumps(v), now) for k, v in values.items()],
            )

    def all(self) -> dict[str, Any]:
        rows = self._db.query("SELECT key, value FROM settings")
        return {row["key"]: loads(row["value"]) for row in rows}


class CategoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_all(self) -> list[Category]:
        rows = self._db.query(
            "SELECT * FROM categories ORDER BY sort_order ASC, id ASC"
        )
        result: list[Category] = []
        for row in rows:
            raw = (row["extensions"] or "").strip()
            exts = tuple(e.strip().lower() for e in raw.split(",") if e.strip())
            result.append(
                Category(
                    id=row["id"],
                    name=row["name"],
                    enabled=bool(row["enabled"]),
                    extensions=exts,
                    sort_order=int(row["sort_order"]),
                    builtin=bool(row["builtin"]),
                )
            )
        return result

    def get(self, category_id: str) -> Category | None:
        for category in self.list_all():
            if category.id == category_id:
                return category
        return None

    def update(
        self,
        category_id: str,
        *,
        enabled: bool | None = None,
        extensions: Iterable[str] | None = None,
    ) -> None:
        sets: list[str] = []
        params: list[Any] = []
        if enabled is not None:
            sets.append("enabled = ?")
            params.append(1 if enabled else 0)
        if extensions is not None:
            cleaned = _normalise_extensions(extensions)
            sets.append("extensions = ?")
            params.append(",".join(cleaned))
        if not sets:
            return
        params.append(category_id)
        self._db.execute(
            f"UPDATE categories SET {', '.join(sets)} WHERE id = ?", tuple(params)
        )

    def rename(self, category_id: str, name: str) -> None:
        self._db.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))


def _normalise_extensions(extensions: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in extensions:
        ext = str(raw).strip().lower().lstrip("*").lstrip(".")
        if not ext or len(ext) > 24:
            continue
        if not all(ch.isalnum() or ch in "._-" for ch in ext):
            continue
        if ext in seen:
            continue
        seen.add(ext)
        cleaned.append(ext)
    return cleaned


class OperationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self,
        *,
        origin: str,
        category: str,
        original_path: str,
        final_path: str,
        status: str,
        size_bytes: int = 0,
        download_id: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
        message: str | None = None,
        undo_state: str = "available",
    ) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO operations (download_id, origin, category, original_path,"
                " final_path, size_bytes, completed_at, organized_at, status, error,"
                " message, undo_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    download_id,
                    origin,
                    category,
                    original_path,
                    final_path,
                    int(size_bytes),
                    completed_at,
                    utc_now_iso(),
                    status,
                    error,
                    message,
                    undo_state,
                ),
            )
            return int(cursor.lastrowid or 0)

    def get(self, operation_id: int) -> Operation | None:
        row = self._db.query_one("SELECT * FROM operations WHERE id = ?", (operation_id,))
        return Operation.from_row(row) if row else None

    def list_recent(self, limit: int = 20) -> list[Operation]:
        rows = self._db.query(
            "SELECT * FROM operations ORDER BY id DESC LIMIT ?", (int(limit),)
        )
        return [Operation.from_row(row) for row in rows]

    def search(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        text: str = "",
        status: str = "",
        category: str = "",
    ) -> list[Operation]:
        where: list[str] = []
        params: list[Any] = []
        if text:
            where.append(
                "(original_path LIKE ? OR final_path LIKE ? OR download_id LIKE ?)"
            )
            like = f"%{text}%"
            params.extend([like, like, like])
        if status:
            where.append("status = ?")
            params.append(status)
        if category:
            where.append("category = ?")
            params.append(category)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        params.extend([int(limit), int(offset)])
        rows = self._db.query(
            f"SELECT * FROM operations{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [Operation.from_row(row) for row in rows]

    def count(self) -> int:
        return int(self._db.scalar("SELECT COUNT(*) FROM operations", default=0))

    def count_by_category(self) -> dict[str, int]:
        rows = self._db.query(
            "SELECT category, COUNT(*) AS total FROM operations"
            " WHERE status = 'organized' GROUP BY category"
        )
        return {row["category"]: int(row["total"]) for row in rows}

    def set_undo_state(self, operation_id: int, state: str) -> None:
        self._db.execute(
            "UPDATE operations SET undo_state = ?, undo_at = ? WHERE id = ?",
            (state, utc_now_iso(), operation_id),
        )

    def mark_undone(self, operation_id: int, message: str | None = None) -> None:
        self._db.execute(
            "UPDATE operations SET status = 'undone', undo_state = 'undone',"
            " undo_at = ?, message = COALESCE(?, message) WHERE id = ?",
            (utc_now_iso(), message, operation_id),
        )

    def stats(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        start_local = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_utc = start_local.astimezone(timezone.utc).isoformat(timespec="seconds")
        organized = int(
            self._db.scalar(
                "SELECT COUNT(*) FROM operations WHERE status = 'organized'", default=0
            )
        )
        organized_today = int(
            self._db.scalar(
                "SELECT COUNT(*) FROM operations WHERE status = 'organized'"
                " AND organized_at >= ?",
                (start_utc,),
                default=0,
            )
        )
        failed = int(
            self._db.scalar(
                "SELECT COUNT(*) FROM operations WHERE status = 'failed'", default=0
            )
        )
        bytes_today = int(
            self._db.scalar(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM operations"
                " WHERE status = 'organized' AND organized_at >= ?",
                (start_utc,),
                default=0,
            )
        )
        last = self._db.scalar(
            "SELECT organized_at FROM operations WHERE status = 'organized'"
            " ORDER BY id DESC LIMIT 1"
        )
        return {
            "organized_total": organized,
            "organized_today": organized_today,
            "failed_total": failed,
            "bytes_today": bytes_today,
            "last_organized_at": last,
        }

    def prune(self, older_than_days: int) -> int:
        """Delete history rows older than ``days``. Returns the number removed."""
        if older_than_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat(
            timespec="seconds"
        )
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM operations WHERE organized_at < ? AND status != 'organized'",
                (cutoff,),
            )
            return int(cursor.rowcount or 0)


class ProcessedRepository:
    """Remembers which downloads/files have already been handled.

    This is the single source of truth that prevents double processing when
    both the browser event and the filesystem watcher report the same file.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def exists(self, key: str) -> bool:
        row = self._db.query_one("SELECT 1 FROM processed_items WHERE key = ?", (key,))
        return row is not None

    def get(self, key: str) -> sqlite3.Row | None:
        return self._db.query_one("SELECT * FROM processed_items WHERE key = ?", (key,))

    def add(
        self,
        key: str,
        *,
        kind: str,
        download_id: str | None = None,
        browser: str | None = None,
        source_path: str | None = None,
        final_path: str | None = None,
        operation_id: int | None = None,
    ) -> None:
        self._db.execute(
            "INSERT INTO processed_items (key, kind, download_id, browser, source_path,"
            " final_path, processed_at, operation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET processed_at = excluded.processed_at,"
            " final_path = COALESCE(excluded.final_path, processed_items.final_path),"
            " operation_id = COALESCE(excluded.operation_id, processed_items.operation_id)",
            (
                key,
                kind,
                download_id,
                browser,
                source_path,
                final_path,
                utc_now_iso(),
                operation_id,
            ),
        )

    def remove(self, key: str) -> None:
        self._db.execute("DELETE FROM processed_items WHERE key = ?", (key,))

    def count(self) -> int:
        return int(self._db.scalar("SELECT COUNT(*) FROM processed_items", default=0))

    def prune(self, older_than_days: int = 30) -> int:
        if older_than_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat(
            timespec="seconds"
        )
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM processed_items WHERE processed_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)


class Repositories:
    """Convenience bundle passed around the application."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.settings = SettingsRepository(db)
        self.categories = CategoryRepository(db)
        self.operations = OperationRepository(db)
        self.processed = ProcessedRepository(db)
