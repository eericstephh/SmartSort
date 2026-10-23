"""The organization engine.

Given a completed download this service decides the destination, classifies the
file, resolves conflicts, performs a safe move and records everything in the
operation history. It never deletes data and never overwrites a file.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from ..config.defaults import (
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_ORGANIZED,
    STATUS_SKIPPED,
    UNDO_AVAILABLE,
    UNDO_UNAVAILABLE,
)
from ..config.settings import SettingsService
from ..storage.models import OrganizeRequest, OrganizeResult
from ..storage.repositories import Repositories
from .classifier import Classifier
from .conflict_resolver import sanitize_filename
from .fileops import MoveError, is_protected_location, is_within, safe_move

logger = logging.getLogger(__name__)


@dataclass
class _Plan:
    source: Path
    target_dir: Path
    filename: str
    category: str
    size_bytes: int


@dataclass(frozen=True)
class TargetPreview:
    """Where a file would land, without moving anything."""

    target_dir: Path
    filename: str
    category: str
    category_name: str

    @property
    def full_path(self) -> Path:
        return self.target_dir / self.filename


def path_key(path: str | Path) -> str:
    """Stable, case-insensitive key for a filesystem path."""
    raw = os.path.normcase(os.path.abspath(os.fspath(path)))
    digest = hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()
    return digest[:32]


def download_key(browser: str | None, download_id: str | None) -> str | None:
    if not download_id:
        return None
    return f"dl:{(browser or 'unknown').lower()}:{download_id}"


class Organizer:
    def __init__(
        self,
        repos: Repositories,
        settings: SettingsService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repos = repos
        self._settings = settings
        self._clock = clock or (lambda: datetime.now())
        self._classifier: Classifier | None = None
        self._classifier_lock = threading.Lock()
        # Serialises the "find a free name and rename" window inside this
        # process. The OS-level rename is still the real guarantee.
        self._move_lock = threading.Lock()

    # -- classifier --------------------------------------------------------
    def classifier(self) -> Classifier:
        with self._classifier_lock:
            if self._classifier is None:
                self._classifier = Classifier(self._repos.categories.list_all())
            return self._classifier

    def invalidate_classifier(self) -> None:
        with self._classifier_lock:
            self._classifier = None

    # -- preview -----------------------------------------------------------
    def preview(
        self, source_path: str | Path, completed_at: object = None
    ) -> TargetPreview | None:
        """Return where ``source_path`` would be placed, or ``None`` when no
        destination is configured.

        Used by the folder scanner so the UI can show the target before the
        user commits to moving anything. It shares ``_plan`` with the real move,
        so the preview cannot drift from what ``organize`` actually does.
        """
        destination = self._settings.destination_path
        if destination is None:
            return None
        try:
            source = Path(source_path)
            size_bytes = source.stat().st_size
        except OSError:
            size_bytes = 0
        request = OrganizeRequest(source_path=str(source_path), completed_at=completed_at)
        plan = self._plan(source, destination, request, size_bytes)
        meta = self._repos.categories.get(plan.category)
        return TargetPreview(
            target_dir=plan.target_dir,
            filename=plan.filename,
            category=plan.category,
            category_name=meta.name if meta else plan.category,
        )

    # -- public API --------------------------------------------------------
    def organize(self, request: OrganizeRequest) -> OrganizeResult:
        settings = self._settings

        if request.origin != "manual" and not settings.auto_organize:
            return OrganizeResult(STATUS_SKIPPED, "auto_organize_disabled")

        if request.origin == "browser" and not request.allow_move:
            return OrganizeResult(STATUS_SKIPPED, "policy_disallows_move")

        destination = settings.destination_path
        if destination is None:
            return OrganizeResult(
                STATUS_FAILED, "destination_not_configured", error="destination_not_configured"
            )

        try:
            source = Path(request.source_path)
        except (TypeError, ValueError):
            return OrganizeResult(STATUS_FAILED, "invalid_source_path", error="invalid_source_path")

        if not source.is_absolute():
            return OrganizeResult(STATUS_FAILED, "invalid_source_path", error="invalid_source_path")

        # A browser message can name any path. Windows and Program Files are
        # never a legitimate download target, so refuse before stat()-ing
        # anything: this is the difference between "a bad message is rejected"
        # and "a bad message made us touch a system directory".
        if is_protected_location(source):
            logger.warning("refusing to organize %s: protected location", source)
            return OrganizeResult(STATUS_SKIPPED, "protected_location")

        # -- dedupe --------------------------------------------------------
        dl_key = download_key(request.browser, request.download_id)
        fs_key = f"path:{path_key(source)}"
        if dl_key and self._repos.processed.exists(dl_key):
            return OrganizeResult(STATUS_DUPLICATE, "already_processed", dedupe_key=dl_key)
        if self._repos.processed.exists(fs_key):
            return OrganizeResult(STATUS_DUPLICATE, "already_processed", dedupe_key=fs_key)

        # -- source validation ---------------------------------------------
        try:
            if not source.exists():
                return OrganizeResult(STATUS_FAILED, "source_missing", error="source_missing")
            if not source.is_file():
                return OrganizeResult(
                    STATUS_FAILED, "source_not_a_file", error="source_not_a_file"
                )
            size_bytes = source.stat().st_size
        except OSError as exc:
            logger.warning("cannot stat %s: %s", source, exc)
            return OrganizeResult(STATUS_FAILED, "source_unreadable", error=str(exc))

        if size_bytes == 0:
            return OrganizeResult(STATUS_SKIPPED, "empty_file")

        if self.classifier().is_temporary(source):
            return OrganizeResult(STATUS_SKIPPED, "file_still_downloading")

        # -- destination validation ----------------------------------------
        # A destination inside the source folder (or equal to it) would make the
        # watcher see its own output, so anything already inside the managed
        # destination is left alone. This also covers the case where the user
        # picked the downloads folder itself as the destination.
        if is_within(source, destination):
            return OrganizeResult(STATUS_SKIPPED, "already_in_destination")

        if not destination.exists():
            try:
                destination.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return OrganizeResult(
                    STATUS_FAILED, "destination_unavailable", error=str(exc)
                )
        if not destination.is_dir():
            return OrganizeResult(
                STATUS_FAILED, "destination_not_a_directory", error="destination_not_a_directory"
            )

        # -- plan ----------------------------------------------------------
        try:
            plan = self._plan(source, destination, request, size_bytes)
        except OSError as exc:
            return OrganizeResult(STATUS_FAILED, "destination_unavailable", error=str(exc))

        # -- execute -------------------------------------------------------
        warning: str | None = None
        try:
            with self._move_lock:
                outcome = safe_move(source, plan.target_dir, plan.filename)
            warning = outcome.warning
            mode = outcome.mode
        except MoveError as exc:
            logger.warning("move failed for %s: %s (%s)", source, exc.code, exc.message)
            operation_id = self._record_failure(request, plan, exc.code, exc.message)
            return OrganizeResult(
                STATUS_FAILED,
                exc.code,
                operation_id=operation_id,
                category=plan.category,
                error=exc.message,
            )
        except OSError as exc:  # pragma: no cover - defensive
            logger.exception("unexpected move failure for %s", source)
            operation_id = self._record_failure(request, plan, "io_error", str(exc))
            return OrganizeResult(
                STATUS_FAILED,
                "io_error",
                operation_id=operation_id,
                category=plan.category,
                error=str(exc),
            )

        final_path = outcome.final_path
        message = warning or f"moved_by_{mode}"

        operation_id = self._repos.operations.add(
            origin=request.origin,
            category=plan.category,
            original_path=str(source),
            final_path=str(final_path),
            status=STATUS_ORGANIZED,
            size_bytes=plan.size_bytes,
            download_id=request.download_id,
            completed_at=_iso(request.completed_at),
            message=message,
            undo_state=UNDO_AVAILABLE if final_path.exists() else UNDO_UNAVAILABLE,
        )

        if dl_key:
            self._repos.processed.add(
                dl_key,
                kind="download",
                download_id=request.download_id,
                browser=request.browser,
                source_path=str(source),
                final_path=str(final_path),
                operation_id=operation_id,
            )
        self._repos.processed.add(
            fs_key,
            kind="path",
            download_id=request.download_id,
            browser=request.browser,
            source_path=str(source),
            final_path=str(final_path),
            operation_id=operation_id,
        )

        logger.info("organized %s -> %s (%s)", source, final_path, plan.category)
        return OrganizeResult(
            STATUS_ORGANIZED,
            message,
            operation_id=operation_id,
            final_path=str(final_path),
            category=plan.category,
            dedupe_key=fs_key,
        )

    # -- internals ---------------------------------------------------------
    def _plan(
        self,
        source: Path,
        destination: Path,
        request: OrganizeRequest,
        size_bytes: int,
    ) -> _Plan:
        settings = self._settings
        completed = self._resolve_datetime(request.completed_at)
        day: date = completed.date()

        filename = sanitize_filename(request.suggested_name or source.name, fallback="download")
        # The category follows the name that will actually exist on disk.
        category = self.classifier().classify(filename)

        target = destination
        if settings.use_date_folders:
            target = target / day.isoformat()
        if settings.use_category_folders:
            category_meta = self._repos.categories.get(category)
            folder = category_meta.folder_name if category_meta else category
            target = target / folder

        return _Plan(
            source=source,
            target_dir=target,
            filename=filename,
            category=category,
            size_bytes=size_bytes,
        )

    def _resolve_datetime(self, value: object) -> datetime:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str) and value.strip():
            dt = _parse_iso(value)
        else:
            dt = self._clock()
        if dt is None:
            dt = self._clock()
        if dt.tzinfo is not None:
            # Stored/transport timestamps are UTC; folder dates are local.
            return dt.astimezone()
        return dt

    def _record_failure(
        self, request: OrganizeRequest, plan: _Plan, code: str, message: str
    ) -> int:
        return self._repos.operations.add(
            origin=request.origin,
            category=plan.category,
            original_path=str(plan.source),
            final_path="",
            status=STATUS_FAILED,
            size_bytes=plan.size_bytes,
            download_id=request.download_id,
            completed_at=_iso(request.completed_at),
            error=f"{code}: {message}",
            message=code,
            undo_state=UNDO_UNAVAILABLE,
        )

    def record_skip(self, request: OrganizeRequest, reason: str) -> int | None:
        """Persist a skip in the history when the user asked for a manual run."""
        if request.origin != "manual":
            return None
        try:
            source = Path(request.source_path)
            size = source.stat().st_size if source.exists() else 0
        except OSError:
            size = 0
        return self._repos.operations.add(
            origin=request.origin,
            category="other",
            original_path=request.source_path,
            final_path="",
            status=STATUS_SKIPPED,
            size_bytes=size,
            download_id=request.download_id,
            message=reason,
            undo_state=UNDO_UNAVAILABLE,
        )


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _parse_iso(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
