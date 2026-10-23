"""Fallback folder watcher.

Browser events are the primary detection mechanism. This polling watcher is the
fallback for downloads that never reach the extension (other browsers, download
managers, or a disabled extension).

Polling was chosen over OS change notifications on purpose: it behaves
identically on local disks, removable media and network shares, it needs no
extra dependency, and it makes "is this file still being written?" an explicit,
testable decision instead of a race.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config.defaults import IGNORED_PREFIXES, TEMP_SUFFIXES
from ..core.fileops import is_locked, is_within

logger = logging.getLogger(__name__)


@dataclass
class _Candidate:
    size: int
    stable_since: float


class DownloadFolderWatcher:
    """Polls a directory and reports files that have finished downloading."""

    def __init__(
        self,
        directory: str | Path,
        on_ready: Callable[[Path], None],
        *,
        poll_interval: float = 2.0,
        settle_seconds: float = 3.0,
        destination: str | Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._directory = Path(directory)
        self._on_ready = on_ready
        self._poll_interval = max(0.25, float(poll_interval))
        self._settle_seconds = max(0.0, float(settle_seconds))
        self._destination = Path(destination) if destination else None
        self._clock = clock
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._candidates: dict[Path, _Candidate] = {}
        self._handled: set[Path] = set()
        self.detected_count = 0
        self.last_error: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="smartsort-watcher", daemon=True
        )
        self._thread.start()
        logger.info("watching %s (poll %.1fs, settle %.1fs)",
                    self._directory, self._poll_interval, self._settle_seconds)

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def poll_interval(self) -> float:
        return self._poll_interval

    @property
    def settle_seconds(self) -> float:
        return self._settle_seconds

    # -- main loop ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
                self.last_error = None
            except Exception as exc:  # pragma: no cover - defensive
                self.last_error = str(exc)
                logger.warning("watcher scan failed for %s: %s", self._directory, exc)
            self._stop.wait(self._poll_interval)

    def scan_once(self) -> list[Path]:
        """Perform one scan and return the paths that were reported as ready."""
        directory = self._directory
        if not directory.is_dir():
            return []
        now = self._clock()
        ready: list[Path] = []
        seen: set[Path] = set()

        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            self.last_error = str(exc)
            logger.debug("cannot scan %s: %s", directory, exc)
            return []

        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            path = Path(entry.path)
            if self._should_ignore(path):
                continue
            seen.add(path)
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if size <= 0:
                continue
            with self._lock:
                candidate = self._candidates.get(path)
                if candidate is None:
                    self._candidates[path] = _Candidate(size=size, stable_since=now)
                    continue
                if candidate.size != size:
                    candidate.size = size
                    candidate.stable_since = now
                    continue
                if (now - candidate.stable_since) < self._settle_seconds:
                    continue
                self._candidates.pop(path, None)
                self._handled.add(path)

            if is_locked(path):
                # Still open by the browser: re-evaluate on the next pass.
                with self._lock:
                    self._candidates[path] = _Candidate(size=size, stable_since=now)
                continue

            ready.append(path)
            self._dispatch(path)

        with self._lock:
            for path in list(self._candidates):
                if path not in seen:
                    self._candidates.pop(path, None)
        return ready

    def forget(self, path: Path) -> None:
        """Stop tracking a path (used after a successful move)."""
        with self._lock:
            self._candidates.pop(Path(path), None)

    def reset(self) -> None:
        with self._lock:
            self._candidates.clear()
            self._handled.clear()

    # -- internals ---------------------------------------------------------
    def _dispatch(self, path: Path) -> None:
        self.detected_count += 1
        try:
            self._on_ready(path)
        except Exception:  # pragma: no cover - defensive
            logger.exception("watcher callback failed for %s", path)

    def _should_ignore(self, path: Path) -> bool:
        name = path.name
        lowered = name.lower()
        if any(lowered.endswith(suffix) for suffix in TEMP_SUFFIXES):
            return True
        if any(name.startswith(prefix) for prefix in IGNORED_PREFIXES):
            return True
        if self._destination is not None and is_within(path, self._destination):
            return True
        with self._lock:
            if path in self._handled:
                return True
        return False
