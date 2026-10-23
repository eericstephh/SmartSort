"""Shared pytest fixtures.

Every test runs against temporary directories. Nothing in the suite touches the
user's real Downloads folder or application data directory.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Keep the GUI tests headless and away from the real desktop session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from smartsort.app.config.settings import SettingsService  # noqa: E402
from smartsort.app.core.organizer import Organizer  # noqa: E402
from smartsort.app.core.undo_manager import UndoManager  # noqa: E402
from smartsort.app.storage.database import Database  # noqa: E402
from smartsort.app.storage.repositories import Repositories  # noqa: E402


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "appdata"
    directory.mkdir()
    monkeypatch.setenv("SMARTSORT_DATA_DIR", str(directory))
    return directory


@pytest.fixture
def db(data_dir: Path):
    database = Database(data_dir / "test.db").open()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repos(db: Database) -> Repositories:
    return Repositories(db)


@pytest.fixture
def settings(repos: Repositories) -> SettingsService:
    return SettingsService(repos.settings)


@pytest.fixture
def fake_clock():
    """A controllable local clock."""

    def clock() -> datetime:
        return clock.state["now"]  # type: ignore[attr-defined]

    clock.state = {"now": datetime(2026, 10, 21, 12, 0, 0)}  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def organizer(repos: Repositories, settings: SettingsService, fake_clock) -> Organizer:
    return Organizer(repos, settings, clock=fake_clock)


@pytest.fixture
def undo(repos: Repositories) -> UndoManager:
    return UndoManager(repos)


@pytest.fixture
def downloads_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "Downloads"
    directory.mkdir()
    return directory


@pytest.fixture
def destination(tmp_path: Path) -> Path:
    directory = tmp_path / "SmartSort"
    directory.mkdir()
    return directory


@pytest.fixture
def configured(settings: SettingsService, destination: Path) -> SettingsService:
    settings.destination_dir = str(destination)
    settings.set("auto_organize", True)
    return settings


def make_file(directory: Path, name: str, content: bytes = b"data") -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path
