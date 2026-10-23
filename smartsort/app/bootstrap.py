"""Application wiring: build the object graph once, in one place."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .browser.bridge_server import ensure_token
from .config import paths
from .config.settings import SettingsService
from .core.download_manager import DownloadManager
from .core.folder_scanner import FolderScanner
from .core.organizer import Organizer
from .core.undo_manager import UndoManager
from .services import logging_service
from .storage.database import Database
from .storage.repositories import Repositories

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    data_dir: Path
    db_path: Path
    log_file: Path
    bridge_token: bytes
    db: Database
    repos: Repositories
    settings: SettingsService
    organizer: Organizer
    undo: UndoManager
    downloads: DownloadManager
    scanner: FolderScanner

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive
            logger.debug("database close failed", exc_info=True)


def create_context(data_dir: Path | str | None = None, *, setup_logs: bool = True) -> AppContext:
    directory = Path(data_dir) if data_dir else paths.app_data_dir()
    paths.ensure_dir(directory)
    log_file = directory / "logs" / "smartsort.log"
    if setup_logs:
        logging_service.setup_logging(log_file)

    db_path = directory / "smartsort.db"
    db = Database(db_path).open()
    repos = Repositories(db)
    settings = SettingsService(repos.settings)
    organizer = Organizer(repos, settings)
    undo = UndoManager(repos)
    downloads = DownloadManager(organizer, repos, settings)
    scanner = FolderScanner(organizer, repos, settings)
    token = ensure_token(directory / "bridge.token")

    logger.info("context ready (data dir: %s)", directory)
    return AppContext(
        data_dir=directory,
        db_path=db_path,
        log_file=log_file,
        bridge_token=token,
        db=db,
        repos=repos,
        settings=settings,
        organizer=organizer,
        undo=undo,
        downloads=downloads,
        scanner=scanner,
    )
