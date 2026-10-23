"""SQLite connection handling, schema migrations and safe transactions."""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import migrations

logger = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """Raised when the database cannot be opened or migrated."""


class Database:
    """A thin, thread-safe wrapper around a single SQLite connection.

    The application performs very short writes (a few rows per organized file)
    and reads for the history view, so a single connection guarded by a lock is
    both simpler and faster than a connection pool, and it keeps the
    ``check_same_thread`` pitfalls away from the UI and worker threads.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> "Database":
        with self._lock:
            if self._conn is not None:
                return self
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                conn = sqlite3.connect(
                    str(self.path),
                    check_same_thread=False,
                    isolation_level=None,  # explicit transaction control
                    timeout=30.0,
                )
            except sqlite3.Error as exc:  # pragma: no cover - environmental
                raise DatabaseError(f"cannot open database at {self.path}: {exc}") from exc
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=15000")
            except sqlite3.Error as exc:  # pragma: no cover - environmental
                conn.close()
                raise DatabaseError(f"cannot configure database: {exc}") from exc
            self._conn = conn
            migrations.apply(conn)
            return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    def __enter__(self) -> "Database":
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("database is not open")
        return self._conn

    # -- queries -----------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.connection.execute(sql, tuple(params))

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            return self.connection.executemany(sql, seq)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.connection.execute(sql, tuple(params)).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block inside an IMMEDIATE transaction.

        Nested use is not supported on purpose: callers should compose
        repository calls that each manage their own transaction.
        """
        with self._lock:
            conn = self.connection
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:  # pragma: no cover - defensive
                    logger.exception("rollback failed")
                raise
            else:
                conn.execute("COMMIT")

    # -- maintenance -------------------------------------------------------
    def backup_to(self, target: Path | str) -> Path:
        """Write a consistent copy of the database to ``target``."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            dest = sqlite3.connect(str(target))
            try:
                self.connection.backup(dest)
            finally:
                dest.close()
        return target

    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))
