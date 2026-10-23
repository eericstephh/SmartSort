"""Deterministic, local file classification.

No language model, no network, no content inspection: the category is derived
from the file's extension only, using a configurable, ordered rule set.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Sequence

from ..config.defaults import OTHER_CATEGORY_ID, TEMP_SUFFIXES
from ..storage.models import Category

logger = logging.getLogger(__name__)


class Classifier:
    """Maps a file name to a category id.

    Rules are built from the enabled categories. Extensions may be compound
    (``tar.gz``), in which case the longest match wins, which keeps the mapping
    deterministic.
    """

    def __init__(self, categories: Sequence[Category], other_id: str = OTHER_CATEGORY_ID):
        self._other_id = other_id
        self._map: dict[str, str] = {}
        self._category_ids: set[str] = set()
        self._max_parts = 1
        for category in categories:
            self._category_ids.add(category.id)
            if category.id == other_id:
                continue
            if not category.enabled:
                continue
            for ext in category.extensions:
                normalised = _normalise_extension(ext)
                if not normalised:
                    continue
                # First category wins for a duplicated extension.
                self._map.setdefault(normalised, category.id)
                self._max_parts = max(self._max_parts, normalised.count("."))

    # -- public API --------------------------------------------------------
    @property
    def known_extensions(self) -> dict[str, str]:
        return dict(self._map)

    @property
    def category_ids(self) -> set[str]:
        return set(self._category_ids)

    def classify(self, path: str | Path) -> str:
        """Return the category id for ``path``.

        Files that are still being written by a download manager are reported
        with the ``other`` category *and* flagged by :meth:`is_temporary`; the
        organizer refuses to move them anyway.
        """
        name = Path(str(path)).name
        ext = self.match_extension(name)
        if ext is None:
            return self._other_id
        return self._map.get(ext, self._other_id)

    def match_extension(self, filename: str) -> str | None:
        """Return the matched extension (with a leading dot) or ``None``."""
        lowered = filename.lower()
        parts = lowered.split(".")
        if len(parts) < 2:
            return None
        # Build candidate suffixes from longest to shortest, e.g. "tar.gz".
        max_take = min(self._max_parts, len(parts) - 1)
        for take in range(max_take, 0, -1):
            candidate = "." + ".".join(parts[-take:])
            if candidate in self._map:
                return candidate
        # A single-suffix fallback even when the map only holds compound keys.
        return "." + parts[-1] if parts[-1] else None

    def is_temporary(self, path: str | Path) -> bool:
        """True when the file looks like an in-progress download."""
        name = Path(str(path)).name.lower()
        return any(name.endswith(suffix) for suffix in TEMP_SUFFIXES)

    def is_known(self, filename: str) -> bool:
        ext = self.match_extension(filename)
        return bool(ext and ext in self._map)

    def classify_name(self, filename: str) -> str:
        return self.classify(filename)


def _normalise_extension(ext: str) -> str:
    value = str(ext).strip().lower()
    value = value.lstrip("*")
    if not value:
        return ""
    if not value.startswith("."):
        value = "." + value
    if len(value) < 2 or len(value) > 26:
        return ""
    return value


def build_classifier(categories: Iterable[Category]) -> Classifier:
    return Classifier(list(categories))
