"""Undo support for file moves recorded in the operation history."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config.defaults import STATUS_ORGANIZED, UNDO_DONE, UNDO_UNAVAILABLE
from ..storage.models import UndoResult
from ..storage.repositories import Repositories
from .conflict_resolver import unique_path
from .fileops import MoveError, restore_move

logger = logging.getLogger(__name__)


class UndoManager:
    def __init__(self, repos: Repositories) -> None:
        self._repos = repos

    # -- inspection --------------------------------------------------------
    def can_undo(self, operation_id: int) -> tuple[bool, str]:
        operation = self._repos.operations.get(operation_id)
        if operation is None:
            return False, "operation_not_found"
        if operation.status != STATUS_ORGANIZED:
            return False, "operation_not_undoable"
        if operation.undo_state == UNDO_DONE:
            return False, "already_undone"
        if not operation.final_path:
            return False, "no_destination_recorded"
        if not Path(operation.final_path).exists():
            return False, "organized_file_missing"
        return True, ""

    def conflict_for(self, operation_id: int) -> bool:
        """True when the original path is occupied and a decision is needed."""
        operation = self._repos.operations.get(operation_id)
        if operation is None or not operation.original_path:
            return False
        return Path(operation.original_path).exists()

    # -- action ------------------------------------------------------------
    def undo(self, operation_id: int, *, on_conflict: str = "cancel") -> UndoResult:
        """Move the organized file back to where it came from.

        ``on_conflict`` is ``"cancel"`` (report the conflict to the caller) or
        ``"rename"`` (restore next to the existing file using a free name).
        """
        operation = self._repos.operations.get(operation_id)
        if operation is None:
            return UndoResult("failed", "operation_not_found", operation_id=operation_id)

        ok, reason = self.can_undo(operation_id)
        if not ok:
            return UndoResult("failed", reason, operation_id=operation_id, error=reason)

        organized_path = Path(operation.final_path)
        original_path = Path(operation.original_path)

        if not original_path.parent.exists():
            # Never delete the organized copy just because we cannot restore it.
            return UndoResult(
                "failed",
                "original_directory_missing",
                operation_id=operation_id,
                error=f"directory no longer exists: {original_path.parent}",
            )

        target = original_path
        if target.exists():
            if on_conflict != "rename":
                return UndoResult(
                    "conflict",
                    "target_exists",
                    operation_id=operation_id,
                    conflict=True,
                )
            try:
                target = unique_path(original_path.parent, original_path.name)
            except FileExistsError as exc:
                return UndoResult(
                    "failed", "conflict_exhausted", operation_id=operation_id, error=str(exc)
                )

        try:
            outcome = restore_move(organized_path, target)
        except MoveError as exc:
            logger.warning("undo failed for operation %s: %s", operation_id, exc.code)
            return UndoResult(
                "failed", exc.code, operation_id=operation_id, error=exc.message
            )
        except OSError as exc:  # pragma: no cover - defensive
            logger.exception("unexpected undo failure for operation %s", operation_id)
            return UndoResult("failed", "io_error", operation_id=operation_id, error=str(exc))

        restored = str(outcome.final_path)
        message = f"restored_to: {restored}"
        if outcome.warning:
            message += f" ({outcome.warning})"
        self._repos.operations.mark_undone(operation_id, message)
        logger.info("undo restored %s -> %s", organized_path, restored)
        return UndoResult("undone", message, restored_path=restored, operation_id=operation_id)

    # -- maintenance -------------------------------------------------------
    def mark_unavailable(self, operation_id: int) -> None:
        self._repos.operations.set_undo_state(operation_id, UNDO_UNAVAILABLE)
