"""Typed access to persisted application settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..storage.repositories import SettingsRepository
from .defaults import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


class SettingsService:
    """A typed facade over the ``settings`` table.

    Values are read on demand. SQLite keeps the page cache warm, and this makes
    the settings always reflect the latest committed state even when several
    threads (UI, watcher, bridge) touch them.
    """

    def __init__(self, repo: SettingsRepository) -> None:
        self._repo = repo

    # -- raw access --------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        fallback = DEFAULT_SETTINGS.get(key, default)
        return self._repo.get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        self._repo.set(key, value)

    def set_many(self, values: dict[str, Any]) -> None:
        self._repo.set_many(values)

    def as_dict(self) -> dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self._repo.all())
        return merged

    # -- destination -------------------------------------------------------
    @property
    def destination_dir(self) -> str:
        return str(self.get("destination_dir") or "")

    @destination_dir.setter
    def destination_dir(self, value: str | Path) -> None:
        self.set("destination_dir", str(value))

    @property
    def destination_path(self) -> Path | None:
        raw = self.destination_dir.strip()
        if not raw:
            return None
        try:
            return Path(raw)
        except (OSError, ValueError):
            return None

    # -- behaviour ---------------------------------------------------------
    @property
    def auto_organize(self) -> bool:
        return bool(self.get("auto_organize", True))

    @auto_organize.setter
    def auto_organize(self, value: bool) -> None:
        self.set("auto_organize", bool(value))

    @property
    def use_date_folders(self) -> bool:
        return bool(self.get("use_date_folders", True))

    @property
    def use_category_folders(self) -> bool:
        return bool(self.get("use_category_folders", True))

    @property
    def allow_move_from_browser_default(self) -> bool:
        return bool(self.get("allow_move_from_browser_default", True))

    # -- watcher -----------------------------------------------------------
    @property
    def watch_enabled(self) -> bool:
        return bool(self.get("watch_enabled", False))

    @property
    def watch_directory(self) -> str:
        return str(self.get("watch_directory") or "")

    @property
    def watch_poll_seconds(self) -> float:
        return _clamp_float(self.get("watch_poll_seconds", 2.0), 0.25, 60.0, 2.0)

    @property
    def watch_settle_seconds(self) -> float:
        return _clamp_float(self.get("watch_settle_seconds", 3.0), 0.0, 600.0, 3.0)

    # -- desktop integration ----------------------------------------------
    @property
    def start_with_windows(self) -> bool:
        return bool(self.get("start_with_windows", False))

    @property
    def minimize_to_tray(self) -> bool:
        return bool(self.get("minimize_to_tray", True))

    @property
    def close_to_tray(self) -> bool:
        return bool(self.get("close_to_tray", True))

    # -- appearance --------------------------------------------------------
    @property
    def language(self) -> str:
        value = str(self.get("language", "en") or "en")
        return value if value in {"en", "fa"} else "en"

    @property
    def theme(self) -> str:
        value = str(self.get("theme", "light") or "light")
        return value if value in {"light", "dark"} else "light"

    # -- browser integration ----------------------------------------------
    @property
    def allowed_extension_ids(self) -> list[str]:
        raw = self.get("allowed_extension_ids", [])
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        if not isinstance(raw, list):
            return []
        cleaned: list[str] = []
        for item in raw:
            text = str(item).strip().lower()
            # Chrome extension IDs are 32 chars from a..p.
            if len(text) == 32 and all("a" <= ch <= "p" for ch in text):
                cleaned.append(text)
        return cleaned

    @allowed_extension_ids.setter
    def allowed_extension_ids(self, value: list[str]) -> None:
        self.set("allowed_extension_ids", list(value))

    @property
    def browser_integration_enabled(self) -> bool:
        return bool(self.get("browser_integration_enabled", True))

    @property
    def history_retention_days(self) -> int:
        return _clamp_int(self.get("history_retention_days", 0), 0, 3650, 0)


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))
