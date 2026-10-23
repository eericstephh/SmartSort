"""Turns browser/watcher events into organization requests.

The manager owns the policy layer: it decides whether an event is actionable at
all (finished, not cancelled, not paused) and then delegates the actual file
move to :class:`~smartsort.app.core.organizer.Organizer`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..config.defaults import STATUS_SKIPPED
from ..config.settings import SettingsService
from ..storage.models import OrganizeRequest, OrganizeResult
from ..storage.repositories import Repositories
from .organizer import Organizer

logger = logging.getLogger(__name__)

KIND_STARTED = "download_started"
KIND_PROGRESS = "download_progress"
KIND_COMPLETED = "download_completed"
KIND_INTERRUPTED = "download_interrupted"
KIND_CANCELLED = "download_cancelled"

_IGNORED_KINDS = {KIND_STARTED, KIND_PROGRESS, KIND_INTERRUPTED, KIND_CANCELLED}


@dataclass
class DownloadEvent:
    kind: str
    download_id: str | None = None
    browser: str | None = None
    filename: str | None = None
    url: str | None = None
    mime: str | None = None
    total_bytes: int | None = None
    completed_at: datetime | None = None
    exists: bool = True


class DownloadManager:
    def __init__(
        self,
        organizer: Organizer,
        repos: Repositories,
        settings: SettingsService,
    ) -> None:
        self._organizer = organizer
        self._repos = repos
        self._settings = settings
        self._paused = threading.Event()
        self._lock = threading.Lock()
        self._last_result: OrganizeResult | None = None

    # -- pause / resume ----------------------------------------------------
    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def pause(self) -> None:
        self._paused.set()
        logger.info("automatic organization paused")

    def resume(self) -> None:
        self._paused.clear()
        logger.info("automatic organization resumed")

    @property
    def last_result(self) -> OrganizeResult | None:
        with self._lock:
            return self._last_result

    # -- event handling ----------------------------------------------------
    def handle_event(self, event: DownloadEvent) -> OrganizeResult:
        if event.kind in _IGNORED_KINDS:
            # A cancelled or interrupted download must never be moved, and a
            # started/progress event only tells us a file is being written.
            return OrganizeResult(STATUS_SKIPPED, f"ignored_{event.kind}")

        if event.kind != KIND_COMPLETED:
            return OrganizeResult(STATUS_SKIPPED, "unsupported_event")

        if self.is_paused:
            return OrganizeResult(STATUS_SKIPPED, "paused")

        if not event.exists:
            return OrganizeResult(STATUS_SKIPPED, "browser_reports_missing_file")

        if not event.filename:
            return OrganizeResult(STATUS_SKIPPED, "missing_filename")

        request = OrganizeRequest(
            source_path=event.filename,
            download_id=event.download_id,
            browser=event.browser,
            completed_at=event.completed_at,
            origin="browser",
            allow_move=self._settings.allow_move_from_browser_default,
        )
        result = self._organizer.organize(request)
        with self._lock:
            self._last_result = result
        return result

    # -- watcher integration ----------------------------------------------
    def handle_watched_file(self, path: str) -> OrganizeResult:
        if self.is_paused:
            return OrganizeResult(STATUS_SKIPPED, "paused")
        request = OrganizeRequest(source_path=str(path), origin="watcher", allow_move=True)
        result = self._organizer.organize(request)
        with self._lock:
            self._last_result = result
        return result

    def organize_manually(
        self, path: str, completed_at: datetime | None = None
    ) -> OrganizeResult:
        """Organize a file the user picked themselves.

        ``completed_at`` lets the caller supply the file's own timestamp. A file
        that was downloaded last week should land in last week's folder, not in
        today's, and there is no browser event to tell us when it arrived.
        """
        request = OrganizeRequest(
            source_path=str(path),
            origin="manual",
            allow_move=True,
            completed_at=completed_at,
        )
        result = self._organizer.organize(request)
        with self._lock:
            self._last_result = result
        return result

    # -- introspection -----------------------------------------------------
    def summary(self) -> dict[str, Any]:
        return {
            "paused": self.is_paused,
            "auto_organize": self._settings.auto_organize,
            "destination": self._settings.destination_dir,
            "processed": self._repos.processed.count(),
        }
