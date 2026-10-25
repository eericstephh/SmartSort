"""Qt-aware mediator between the UI and the core services.

The core (organizer, classifier, storage) is deliberately free of Qt. This
object is the single place that knows about both worlds: it owns the background
threads, turns browser messages into results, and emits signals the widgets can
subscribe to.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..bootstrap import AppContext
from ..browser import registry
from ..browser.bridge_server import BridgeServer
from ..browser.message_validation import ValidationError, validate_message
from ..config import paths
from ..config.defaults import (
    APP_VERSION,
    PIPE_NAME,
    STATUS_CONTENT_DUPLICATE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_ORGANIZED,
    STATUS_SKIPPED,
)
from ..core.download_manager import DownloadEvent
from ..i18n import set_language
from ..services import logging_service
from ..services.filesystem_monitor import DownloadFolderWatcher

logger = logging.getLogger(__name__)

BROWSERS = ("chrome", "edge")
# The extension pings every 5 minutes, and every download event also counts as
# activity, so a 6 minute window keeps the indicator honest without pretending
# a suspended service worker is still connected.
CONNECTED_WINDOW_SECONDS = 360.0


class AppController(QObject):
    operations_changed = Signal()
    settings_changed = Signal()
    status_changed = Signal()
    language_changed = Signal(str)
    notification = Signal(str, str)
    browser_activity = Signal(str)

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._bridge: BridgeServer | None = None
        self._watcher: DownloadFolderWatcher | None = None
        self._browser_seen: dict[str, float] = {}
        self._last_error: str | None = None
        self._quitting = False

    # -- accessors ---------------------------------------------------------
    @property
    def context(self) -> AppContext:
        return self._ctx

    @property
    def settings(self):
        return self._ctx.settings

    @property
    def repos(self):
        return self._ctx.repos

    @property
    def bridge_running(self) -> bool:
        return self._bridge is not None and self._bridge.is_running

    @property
    def watcher_running(self) -> bool:
        return self._watcher is not None and self._watcher.is_running

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._start_bridge()
        self._sync_watcher()
        self._prune_history()
        logger.info("controller started")

    def _start_bridge(self) -> None:
        if not self._ctx.settings.browser_integration_enabled:
            logger.info("browser integration disabled in settings")
            return
        server = BridgeServer(PIPE_NAME, self._ctx.bridge_token, self.handle_message)
        try:
            server.start()
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("bridge could not start: %s", exc)
            return
        self._bridge = server
        self._warn_if_unbound()

    def _warn_if_unbound(self) -> None:
        """An empty allow-list accepts any extension. Never let that be silent."""
        if self._ctx.settings.allowed_extension_ids:
            return
        try:
            registered = [name for name, path in registry.status().items() if path]
        except Exception:  # pragma: no cover - registry access is environmental
            return
        if not registered:
            return
        logger.warning(
            "native host is registered for %s but no extension ID is pinned; "
            "any extension can send messages - re-run 'Install browser integration'",
            ", ".join(registered),
        )

    def shutdown(self) -> None:
        self._quitting = True
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        if self._bridge is not None:
            self._bridge.stop()
            self._bridge = None
        logger.info("controller stopped")

    def _prune_history(self) -> None:
        days = self._ctx.settings.history_retention_days
        if days > 0:
            try:
                self._ctx.repos.operations.prune(days)
                self._ctx.repos.processed.prune(max(days, 7))
            except Exception:  # pragma: no cover - defensive
                logger.warning("history pruning failed", exc_info=True)

    # -- browser bridge ----------------------------------------------------
    def handle_message(self, raw: Any) -> dict[str, Any]:
        """Validate and act on a message from a browser extension.

        Called from bridge worker threads: must stay thread-safe and must never
        trust its input.
        """
        try:
            message = validate_message(raw)
        except ValidationError as exc:
            logger.warning("rejected browser message: %s", exc)
            return {"ok": False, "error": exc.code, "detail": exc.detail}

        browser = message.get("browser", "unknown")
        extension_id = message.get("extensionId")
        allowed = self._ctx.settings.allowed_extension_ids
        if allowed:
            # An allow-list is only worth anything if it is enforced on every
            # message. Previously a message that simply omitted "extensionId"
            # skipped the check entirely, which made the list advisory.
            if not extension_id:
                logger.warning("rejected message with no extension id (allow-list is configured)")
                return {"ok": False, "error": "extension_not_allowed"}
            if extension_id not in allowed:
                logger.warning("rejected message from unexpected extension %s", extension_id)
                return {"ok": False, "error": "extension_not_allowed"}

        if browser in BROWSERS:
            self._browser_seen[browser] = time.monotonic()
            self.browser_activity.emit(browser)

        msg_type = message["type"]
        if msg_type in {"hello", "ping", "status"}:
            return self._status_response()

        if not self._ctx.settings.browser_integration_enabled:
            return {"ok": False, "error": "integration_disabled"}

        download = message["download"]
        event = DownloadEvent(
            kind=msg_type,
            download_id=download.get("id"),
            browser=browser,
            filename=download.get("filename"),
            url=download.get("url"),
            mime=download.get("mime"),
            total_bytes=download.get("totalBytes"),
            completed_at=_parse_ts(download.get("completedAt")),
            exists=download.get("exists", True),
        )
        result = self._ctx.downloads.handle_event(event)

        if result.status == STATUS_ORGANIZED:
            self._announce(result)
        self.operations_changed.emit()
        return _result_payload(result)

    def _status_response(self) -> dict[str, Any]:
        destination = self._ctx.settings.destination_dir
        return {
            "ok": True,
            "app": "SmartSort",
            "version": APP_VERSION,
            "ready": bool(destination) and self._ctx.settings.auto_organize,
            "paused": self._ctx.downloads.is_paused,
            "destination": destination or None,
            "protocolVersion": 1,
        }

    def _announce(self, result) -> None:
        name = Path(result.final_path).name if result.final_path else ""
        self.notification.emit("organized", f"{name}|{result.category or ''}")

    def browser_status(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        status: dict[str, dict[str, Any]] = {}
        for browser in BROWSERS:
            last = self._browser_seen.get(browser)
            connected = last is not None and (now - last) <= CONNECTED_WINDOW_SECONDS
            status[browser] = {
                "connected": connected,
                "last_seen_seconds": None if last is None else int(now - last),
            }
        return status

    # -- watcher -----------------------------------------------------------
    def _sync_watcher(self) -> None:
        settings = self._ctx.settings
        desired_dir = settings.watch_directory.strip()
        should_run = (
            settings.watch_enabled
            and bool(desired_dir)
            and Path(desired_dir).is_dir()
            and not self._ctx.downloads.is_paused
        )

        if self._watcher is not None:
            same_target = str(self._watcher.directory) == desired_dir
            same_tuning = (
                abs(self._watcher.poll_interval - settings.watch_poll_seconds) < 0.01
                and abs(self._watcher.settle_seconds - settings.watch_settle_seconds) < 0.01
            )
            if should_run and same_target and same_tuning:
                return
            self._watcher.stop()
            self._watcher = None

        if not should_run:
            return

        watcher = DownloadFolderWatcher(
            desired_dir,
            self._on_watched_file,
            poll_interval=settings.watch_poll_seconds,
            settle_seconds=settings.watch_settle_seconds,
            destination=settings.destination_dir or None,
        )
        watcher.start()
        self._watcher = watcher

    def _on_watched_file(self, path: Path) -> None:
        try:
            result = self._ctx.downloads.handle_watched_file(str(path))
        except Exception:  # pragma: no cover - defensive
            logger.exception("watcher handling failed for %s", path)
            return
        if result.status == STATUS_ORGANIZED:
            self._announce(result)
        self.operations_changed.emit()

    # -- actions -----------------------------------------------------------
    def set_destination(self, directory: str | Path) -> tuple[bool, str]:
        candidate = Path(str(directory))
        if not candidate.exists() or not candidate.is_dir():
            return False, "destination_missing"
        try:
            probe = candidate / ".smartsort-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError:
            return False, "destination_not_writable"
        self._ctx.settings.destination_dir = str(candidate)
        self._ctx.settings.set("onboarding_completed", True)
        self._sync_watcher()
        self.settings_changed.emit()
        self.status_changed.emit()
        return True, str(candidate)

    def set_auto_organize(self, enabled: bool) -> None:
        self._ctx.settings.set("auto_organize", bool(enabled))
        if enabled:
            self._ctx.downloads.resume()
        self.settings_changed.emit()
        self.status_changed.emit()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._ctx.downloads.pause()
        else:
            self._ctx.downloads.resume()
        self._sync_watcher()
        self.status_changed.emit()

    def toggle_paused(self) -> bool:
        self.set_paused(not self._ctx.downloads.is_paused)
        return self._ctx.downloads.is_paused

    def is_paused(self) -> bool:
        return self._ctx.downloads.is_paused

    def update_settings(self, values: dict[str, Any]) -> None:
        self._ctx.settings.set_many(values)
        if "watch_enabled" in values or "watch_directory" in values or "watch_poll_seconds" in values:
            self._sync_watcher()
        self.settings_changed.emit()
        self.status_changed.emit()

    def set_language(self, language: str) -> None:
        self._ctx.settings.set("language", language)
        set_language(language)
        self.language_changed.emit(language)

    def organize_now(self, path: str) -> dict[str, Any]:
        result = self._ctx.downloads.organize_manually(path)
        self.operations_changed.emit()
        return _result_payload(result)

    # -- existing-folder scan ----------------------------------------------
    def default_scan_directory(self) -> str:
        """Best guess for "the folder my downloads land in"."""
        watched = self._ctx.settings.watch_directory.strip()
        if watched and Path(watched).is_dir():
            return watched
        downloads = paths.default_downloads_dir()
        return str(downloads) if downloads.is_dir() else ""

    def scan_folder(self, directory: str, *, recursive: bool = False):
        """Read-only. Returns a ScanResult; nothing is moved."""
        return self._ctx.scanner.scan(directory, recursive=recursive)

    def organize_scanned(self, items, on_progress=None) -> dict[str, Any]:
        """Organize the scan items the user selected, one at a time.

        Each file goes through the normal organizer, so dedupe, conflict naming,
        history and undo all apply exactly as they do for an automatic move. One
        failure never aborts the batch.
        """
        organized = 0
        skipped = 0
        failed = 0
        details: list[dict[str, Any]] = []
        total = len(items)

        for index, item in enumerate(items, start=1):
            if on_progress is not None:
                try:
                    on_progress(index, total, item.name)
                except Exception:  # pragma: no cover - defensive
                    pass
            try:
                result = self._ctx.downloads.organize_manually(
                    str(item.path), completed_at=item.modified_at
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("batch organize failed for %s", item.path)
                failed += 1
                details.append({"path": str(item.path), "status": STATUS_FAILED, "error": str(exc)})
                continue

            if result.status == STATUS_ORGANIZED:
                organized += 1
            elif result.status in (STATUS_SKIPPED, STATUS_DUPLICATE, STATUS_CONTENT_DUPLICATE):
                skipped += 1
            else:
                failed += 1
            details.append(
                {
                    "path": str(item.path),
                    "status": result.status,
                    "message": result.message,
                    "final_path": result.final_path,
                }
            )

        if organized:
            self.operations_changed.emit()
        return {
            "organized": organized,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "details": details,
        }

    def undo_operation(self, operation_id: int, on_conflict: str = "cancel"):
        result = self._ctx.undo.undo(operation_id, on_conflict=on_conflict)
        if result.status in {"undone", "failed"}:
            self.operations_changed.emit()
        return result

    # -- data for the UI ---------------------------------------------------
    def stats(self) -> dict[str, Any]:
        data = self._ctx.repos.operations.stats()
        data["destination"] = self._ctx.settings.destination_dir
        data["auto_organize"] = self._ctx.settings.auto_organize
        data["paused"] = self._ctx.downloads.is_paused
        data["watcher_running"] = self.watcher_running
        data["bridge_running"] = self.bridge_running
        return data

    def recent(self, limit: int = 8):
        return self._ctx.repos.operations.list_recent(limit)

    def history(self, **kwargs):
        return self._ctx.repos.operations.search(**kwargs)

    def categories(self):
        return self._ctx.repos.categories.list_all()

    def save_categories(self, updates: list[tuple[str, bool, list[str]]]) -> None:
        for category_id, enabled, extensions in updates:
            self._ctx.repos.categories.update(
                category_id, enabled=enabled, extensions=extensions
            )
        self._ctx.organizer.invalidate_classifier()
        self.operations_changed.emit()

    def reset_categories(self) -> None:
        from ..config.defaults import CATEGORY_DEFINITIONS

        for cat_id, _name, extensions in CATEGORY_DEFINITIONS:
            self._ctx.repos.categories.update(cat_id, enabled=True, extensions=extensions)
        self._ctx.organizer.invalidate_classifier()

    def add_category(self, name: str, extensions: list[str]) -> str:
        """Create a user category and return its id. Raises CategoryError."""
        category_id = self._ctx.repos.categories.create(name, extensions)
        self._ctx.organizer.invalidate_classifier()
        self.operations_changed.emit()
        return category_id

    def rename_category(self, category_id: str, name: str) -> None:
        self._ctx.repos.categories.rename(category_id, name)
        self._ctx.organizer.invalidate_classifier()
        self.operations_changed.emit()

    def delete_category(self, category_id: str) -> None:
        self._ctx.repos.categories.delete(category_id)
        self._ctx.organizer.invalidate_classifier()
        self.operations_changed.emit()

    def category_conflicts(
        self, extensions: list[str], exclude_id: str = ""
    ) -> dict[str, str]:
        """Extensions in ``extensions`` that another category already wins."""
        owners = self._ctx.repos.categories.extension_owners(exclude_id)
        conflicts: dict[str, str] = {}
        for raw in extensions:
            ext = str(raw).strip().lower().lstrip("*").lstrip(".")
            if ext and ext in owners:
                conflicts[ext] = owners[ext]
        return conflicts

    # -- diagnostics -------------------------------------------------------
    def browser_registration(self) -> dict[str, Any]:
        return {
            "status": registry.status(),
            "extension_ids": self._ctx.settings.allowed_extension_ids,
            "bridge_running": self.bridge_running,
            "extension_folder": registry.open_extension_folder(),
        }

    def install_browser_integration(self, extension_ids: list[str]):
        from ..config.defaults import NATIVE_HOST_NAME

        manifest = self._ctx.data_dir / "native-host" / f"{NATIVE_HOST_NAME}.json"
        result = registry.install(
            extension_ids=extension_ids,
            manifest_path=manifest,
            browsers=BROWSERS,
        )
        if result.ok:
            self._ctx.settings.allowed_extension_ids = extension_ids
            self.settings_changed.emit()
        return result

    def remove_browser_integration(self):
        from ..config.defaults import NATIVE_HOST_NAME

        manifest = self._ctx.data_dir / "native-host" / f"{NATIVE_HOST_NAME}.json"
        return registry.uninstall(manifest_path=manifest)

    def diagnostics(self) -> dict[str, Any]:
        db_info = {
            "schema_version": int(self._ctx.db.scalar("PRAGMA user_version", default=0)),
            "integrity": self._ctx.db.integrity_check(),
            "operations": self._ctx.repos.operations.count(),
            "processed_items": self._ctx.repos.processed.count(),
        }
        return logging_service.collect_diagnostics(
            data_dir=self._ctx.data_dir,
            db_path=self._ctx.db_path,
            log_file=self._ctx.log_file,
            settings=self._ctx.settings.as_dict(),
            db_info=db_info,
            browser_status={
                "registry": registry.status(),
                "bridge_running": self.bridge_running,
                "watcher_running": self.watcher_running,
            },
        )

    def export_diagnostics(self, destination: Path) -> Path:
        return logging_service.export_diagnostics(
            destination,
            data_dir=self._ctx.data_dir,
            log_file=self._ctx.log_file,
            diagnostics=self.diagnostics(),
            db_path=self._ctx.db_path,
        )

    def backup_state(self, destination: Path) -> Path:
        return logging_service.backup_state(destination, db_path=self._ctx.db_path)

    def open_path(self, path: str | Path) -> None:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            logger.warning("cannot open %s", path, exc_info=True)

    @property
    def data_dir(self) -> Path:
        return self._ctx.data_dir

    @property
    def log_file(self) -> Path:
        return self._ctx.log_file

    def default_downloads_dir(self) -> str:
        return str(paths.default_downloads_dir())


def _result_payload(result) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": result.status
        in {STATUS_ORGANIZED, STATUS_SKIPPED, STATUS_DUPLICATE, STATUS_CONTENT_DUPLICATE}
    }
    payload["status"] = result.status
    payload["message"] = result.message
    if result.final_path:
        payload["finalPath"] = result.final_path
    if result.category:
        payload["category"] = result.category
    if result.operation_id:
        payload["operationId"] = result.operation_id
    if result.status == STATUS_FAILED:
        payload["ok"] = False
        payload["error"] = result.message
    return payload


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
