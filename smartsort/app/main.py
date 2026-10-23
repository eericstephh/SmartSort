"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .bootstrap import create_context
from .config.defaults import APP_NAME, APP_VERSION
from .i18n import is_rtl, set_language

logger = logging.getLogger(__name__)

SINGLE_INSTANCE_KEY = "SmartSort.SingleInstance.v1"


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SmartSort.Desktop.1"
        )
    except Exception:  # pragma: no cover - cosmetic only
        pass


def _install_excepthook() -> None:
    def handler(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.getLogger("smartsort").critical("unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                f"{APP_NAME} - unexpected error",
                f"An unexpected error occurred:\n\n{exc_value}\n\n"
                "Details were written to the log file.",
            )
        except Exception:  # pragma: no cover - no GUI available
            pass

    sys.excepthook = handler


class SingleInstanceGuard:
    """Ensures only one desktop instance runs; focuses the existing window."""

    def __init__(self, key: str = SINGLE_INSTANCE_KEY) -> None:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket

        self._server: QLocalServer | None = None
        self._key = key
        self._socket = QLocalSocket()
        self._socket.connectToServer(key)
        if self._socket.waitForConnected(300):
            self._socket.write(b"show")
            self._socket.flush()
            self._socket.waitForBytesWritten(300)
            self.is_primary = False
            return

        QLocalServer.removeServer(key)
        self._server = QLocalServer()
        self._server.listen(key)
        self.is_primary = True

    def on_activate(self, callback) -> None:
        if self._server is None:
            return

        def handle() -> None:
            connection = self._server.nextPendingConnection()
            if connection is None:
                return
            connection.readyRead.connect(lambda: connection.readAll())
            connection.disconnected.connect(connection.deleteLater)
            callback()

        self._server.newConnection.connect(handle)

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smartsort", add_help=True)
    parser.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    parser.add_argument("--data-dir", default=None, help="override the application data directory")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument(
        "--native-host",
        action="store_true",
        help="run as the browser native messaging host (used by the manifest)",
    )
    parser.add_argument(
        "--register-host",
        default=None,
        metavar="EXTENSION_ID[,EXTENSION_ID]",
        help="register the native messaging host for the given extension ids and exit",
    )
    parser.add_argument(
        "--unregister-host",
        action="store_true",
        help="remove the native messaging host registration and exit",
    )
    parser.add_argument(
        "--print-paths",
        action="store_true",
        help="print the application data locations and exit",
    )
    parser.add_argument(
        "--scan",
        default=None,
        metavar="FOLDER",
        help="preview what would happen to the files in FOLDER and exit (read-only)",
    )
    parser.add_argument(
        "--scan-recursive",
        action="store_true",
        help="include subfolders when used with --scan",
    )
    return parser


def _run_maintenance(args: argparse.Namespace) -> int:
    from .browser import registry
    from .config import paths

    manifest = paths.native_manifest_path()

    if args.print_paths:
        print(f"data_dir:  {paths.app_data_dir()}")
        print(f"database:  {paths.db_path()}")
        print(f"log_file:  {paths.log_file()}")
        print(f"manifest:  {manifest}")
        print(f"launcher:  {registry.resolve_launcher()}")
        return 0

    if args.unregister_host:
        result = registry.uninstall(manifest_path=manifest)
        for action in result.actions:
            print(action)
        for error in result.errors:
            print(f"error: {error}", file=sys.stderr)
        print("native messaging host removed" if result.ok else "removal incomplete")
        return 0 if result.ok else 1

    if args.scan:
        return _run_scan(args, manifest)

    raw = str(args.register_host).replace(";", ",")
    extension_ids = [part.strip() for part in raw.split(",") if part.strip()]
    result = registry.install(extension_ids=extension_ids, manifest_path=manifest)
    for action in result.actions:
        print(action)
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    if result.ok:
        print(f"registered browsers: {', '.join(result.browsers)}")
        print(f"manifest: {result.manifest_path}")
        print(f"launcher: {result.launcher_path}")
        _pin_extension_ids(extension_ids)
        print("Restart Chrome/Edge so it reloads the native messaging hosts.")
        return 0
    return 1


def _pin_extension_ids(extension_ids: list[str]) -> None:
    """Record the allow-list so the bridge is bound to these extensions.

    Registering the native host without pinning the IDs would leave the
    app-side allow-list empty, and an empty allow-list accepts any extension.
    Both halves are done in one step so the two can never drift apart.
    """
    try:
        context = create_context()
    except Exception:  # pragma: no cover - environmental
        logging.getLogger(__name__).warning(
            "could not record the extension allow-list", exc_info=True
        )
        return
    try:
        context.settings.allowed_extension_ids = list(extension_ids)
        print(f"pinned extension ids: {', '.join(extension_ids)}")
    finally:
        context.close()


def _run_scan(args: argparse.Namespace, manifest: Path) -> int:
    """Print what the folder scanner would do, without moving anything.

    This exists so a packaged build can be checked headlessly: the GUI path is
    the same code, but there is no way to click a button from a script.
    """
    context = create_context()
    try:
        destination = context.settings.destination_dir
        if not destination:
            print("error: no destination folder configured", file=sys.stderr)
            print(f"       set one in the app, or see {manifest}", file=sys.stderr)
            return 2

        result = context.scanner.scan(args.scan, recursive=args.scan_recursive)
        if result.error:
            print(f"error: {result.error}: {result.directory}", file=sys.stderr)
            return 2

        print(f"destination: {destination}")
        print(f"scanning:    {result.directory}")
        print("")
        for item in result.items:
            state = "ok" if item.actionable else item.reason
            target = item.target_dir if (item.actionable and item.target_dir) else "-"
            print(f"{state}\t{item.category}\t{item.size_bytes}\t{item.name}\t{target}")
        print("")
        print(
            f"{len(result.actionable)} of {len(result.items)} files can be organized "
            f"({result.total_bytes} bytes)"
        )
        if result.truncated:
            print("note: the listing was truncated; narrow the folder to see the rest")
        return 0
    finally:
        context.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    if args.native_host:
        from .browser.native_host import main as host_main

        return host_main(sys.argv[1:])

    # Must happen before any path is resolved, including the maintenance
    # commands below, otherwise --data-dir would silently be ignored.
    if args.data_dir:
        os.environ["SMARTSORT_DATA_DIR"] = args.data_dir

    if args.print_paths or args.register_host or args.unregister_host or args.scan:
        return _run_maintenance(args)

    _set_app_user_model_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    from .ui.branding import app_icon

    app.setWindowIcon(app_icon())
    _install_excepthook()

    guard = SingleInstanceGuard()
    if not guard.is_primary:
        return 0

    context = create_context(args.data_dir)
    set_language(context.settings.language)
    app.setLayoutDirection(
        Qt.RightToLeft if is_rtl(context.settings.language) else Qt.LeftToRight
    )

    from .ui.controller import AppController
    from .ui.main_window import MainWindow

    controller = AppController(context)
    controller.start()

    window = MainWindow(controller)
    guard.on_activate(window._show_from_tray)

    start_hidden = args.minimized or bool(context.settings.get("start_minimized", False))
    if start_hidden and window._tray is not None:
        logger.info("starting minimized to tray")
    else:
        window.show()

    exit_code = app.exec()
    guard.release()
    context.close()
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
