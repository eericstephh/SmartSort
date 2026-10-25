"""Plain data models shared by the storage, core and UI layers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    enabled: bool
    extensions: tuple[str, ...]
    sort_order: int = 0
    builtin: bool = True

    @property
    def folder_name(self) -> str:
        """Folder name used on disk. Built-in names are stable and safe."""
        return self.name


@dataclass(frozen=True)
class Operation:
    id: int
    download_id: str | None
    origin: str
    category: str
    original_path: str
    final_path: str
    size_bytes: int
    completed_at: str | None
    organized_at: str
    status: str
    error: str | None = None
    message: str | None = None
    undo_state: str = "available"
    undo_at: str | None = None
    content_hash: str | None = None
    duplicate_of: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "Operation":
        keys = row.keys()
        return cls(
            id=int(row["id"]),
            download_id=row["download_id"],
            origin=row["origin"],
            category=row["category"],
            original_path=row["original_path"],
            final_path=row["final_path"],
            size_bytes=int(row["size_bytes"] or 0),
            completed_at=row["completed_at"],
            organized_at=row["organized_at"],
            status=row["status"],
            error=row["error"] if "error" in keys else None,
            message=row["message"] if "message" in keys else None,
            undo_state=row["undo_state"] if "undo_state" in keys else "available",
            undo_at=row["undo_at"] if "undo_at" in keys else None,
            content_hash=row["content_hash"] if "content_hash" in keys else None,
            duplicate_of=row["duplicate_of"] if "duplicate_of" in keys else None,
        )


@dataclass
class OrganizeRequest:
    """A request to organize a single completed download."""

    source_path: str
    download_id: str | None = None
    browser: str | None = None
    completed_at: Any = None  # datetime | None
    origin: str = "browser"  # browser | watcher | manual
    allow_move: bool = True
    suggested_name: str | None = None


@dataclass
class OrganizeResult:
    status: str
    message: str = ""
    operation_id: int | None = None
    final_path: str | None = None
    category: str | None = None
    error: str | None = None
    dedupe_key: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "organized"


@dataclass
class UndoResult:
    status: str
    message: str = ""
    restored_path: str | None = None
    operation_id: int | None = None
    error: str | None = None
    conflict: bool = False


@dataclass
class Stats:
    organized_total: int = 0
    organized_today: int = 0
    failed_total: int = 0
    bytes_today: int = 0
    last_organized_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(raw: str, default: Any = None) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
