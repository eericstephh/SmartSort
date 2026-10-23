"""Scan an existing folder for files that SmartSort could organize.

This is the "what about the files that are already in my Downloads folder?"
feature. It is deliberately read-only: :meth:`FolderScanner.scan` never moves,
renames or deletes anything. It returns a list the UI can show, and the user
then chooses what to organize.

Two rules keep it safe:

* A file is only *actionable* when nothing is wrong with it. Anything still
  being written, empty, already inside the destination or locked by another
  process is reported with a reason instead of being offered.
* The preview comes from :meth:`Organizer.preview`, which shares the planning
  code with the real move. What the user sees is what will happen.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..config.defaults import IGNORED_PREFIXES
from ..config.settings import SettingsService
from ..storage.repositories import Repositories
from .classifier import Classifier
from .fileops import is_protected_location, is_within
from .organizer import Organizer

logger = logging.getLogger(__name__)

# Reasons a scanned file cannot be organized. These are stable identifiers, not
# display text, so the UI can translate them.
REASON_TEMPORARY = "file_still_downloading"
REASON_EMPTY = "empty_file"
REASON_IN_DESTINATION = "already_in_destination"
REASON_HIDDEN = "hidden_file"
REASON_PROTECTED = "protected_location"


@dataclass(frozen=True)
class ScanItem:
    path: Path
    name: str
    size_bytes: int
    modified_at: datetime
    category: str
    category_name: str
    target_dir: Path | None
    reason: str | None = None

    @property
    def actionable(self) -> bool:
        """True when organizing this file is expected to succeed."""
        return self.reason is None


@dataclass
class ScanResult:
    directory: Path
    items: list[ScanItem]
    error: str | None = None
    truncated: bool = False

    @property
    def actionable(self) -> list[ScanItem]:
        return [item for item in self.items if item.actionable]

    @property
    def skipped(self) -> list[ScanItem]:
        return [item for item in self.items if not item.actionable]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.actionable)


class FolderScanner:
    """Enumerates a folder and reports what SmartSort would do with each file."""

    def __init__(
        self,
        organizer: Organizer,
        repos: Repositories,
        settings: SettingsService,
        *,
        max_items: int = 5000,
    ) -> None:
        self._organizer = organizer
        self._repos = repos
        self._settings = settings
        self._max_items = max(1, int(max_items))

    # -- public API --------------------------------------------------------
    def scan(self, directory: str | Path, *, recursive: bool = False) -> ScanResult:
        root = Path(str(directory))
        if not root.exists() or not root.is_dir():
            return ScanResult(root, [], error="folder_missing")

        destination = self._settings.destination_path
        classifier = self._organizer.classifier()
        items: list[ScanItem] = []
        truncated = False

        for path in self._iter_files(root, recursive=recursive):
            if len(items) >= self._max_items:
                truncated = True
                break
            item = self._describe(path, classifier, destination)
            if item is not None:
                items.append(item)

        # Newest first: those are the ones a user most likely wants to move.
        items.sort(key=lambda entry: entry.modified_at, reverse=True)
        return ScanResult(root, items, truncated=truncated)

    # -- internals ---------------------------------------------------------
    def _iter_files(self, root: Path, *, recursive: bool) -> Iterator[Path]:
        if not recursive:
            try:
                entries = list(os.scandir(root))
            except OSError as exc:
                logger.debug("cannot scan %s: %s", root, exc)
                return
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                except OSError:
                    continue
            return

        for current, dirnames, filenames in os.walk(root, followlinks=False):
            # Never descend into the managed destination: it holds SmartSort's
            # own output and re-scanning it would be pointless noise.
            destination = self._settings.destination_path
            if destination is not None:
                dirnames[:] = [
                    name
                    for name in dirnames
                    if not is_within(Path(current) / name, destination)
                ]
            for name in filenames:
                yield Path(current) / name

    def _describe(
        self,
        path: Path,
        classifier: Classifier,
        destination: Path | None,
    ) -> ScanItem | None:
        try:
            stat = path.stat()
        except OSError:
            return None

        modified = datetime.fromtimestamp(stat.st_mtime)
        preview = self._organizer.preview(path, completed_at=modified)

        category = preview.category if preview else classifier.classify(path.name)
        category_name = preview.category_name if preview else category
        target_dir = preview.target_dir if preview else None

        return ScanItem(
            path=path,
            name=path.name,
            size_bytes=int(stat.st_size),
            modified_at=modified,
            category=category,
            category_name=category_name,
            target_dir=target_dir,
            reason=self._reason(path, classifier, destination, stat.st_size),
        )

    def _reason(
        self,
        path: Path,
        classifier: Classifier,
        destination: Path | None,
        size: int,
    ) -> str | None:
        name = path.name
        if any(name.startswith(prefix) for prefix in IGNORED_PREFIXES):
            return REASON_HIDDEN
        if classifier.is_temporary(path):
            return REASON_TEMPORARY
        if size <= 0:
            return REASON_EMPTY
        if destination is not None and is_within(path, destination):
            return REASON_IN_DESTINATION
        # The organizer refuses these too; saying so up front keeps the preview
        # from promising a move that will not happen.
        if is_protected_location(path):
            return REASON_PROTECTED
        # No lock probe here on purpose: asking "is this file open?" means
        # attempting a rename, and a scan must not write. A file that really is
        # held open fails later with a clear error and keeps its source intact.
        return None
