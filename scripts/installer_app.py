"""SmartSort setup program.

One executable, no administrator rights, no network access. It carries the
application payload as an embedded zip, extracts it into a per-user folder,
creates shortcuts and registers itself in "Apps & features".

Usage:

    SmartSort-Setup-1.0.0.exe                 interactive installer
    SmartSort-Setup-1.0.0.exe /S              silent, default options
    SmartSort-Setup-1.0.0.exe /S /D=C:\\Path  silent, custom folder
    SmartSort-Setup-1.0.0.exe /?              usage

Design notes:

* installation is per-user, so nothing here touches HKLM or needs elevation;
* the payload is validated against zip-slip before extraction;
* a failed shortcut or registry write is reported but does not abort the
  install, because the application itself still works without them.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

APP_NAME = "SmartSort"
APP_VERSION = "1.1.0"
APP_PUBLISHER = "SmartSort"
EXE_NAME = "SmartSort.exe"
UNINSTALL_EXE = "uninstall.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SmartSort"
START_MENU_FOLDER = "SmartSort"

Progress = Callable[[int, str], None]


# -- resources -------------------------------------------------------------
def resource_path(name: str) -> Path:
    """Locate a file bundled next to the executable or inside the bundle."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent.parent / "build" / name


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "Programs" / APP_NAME


def _start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / START_MENU_FOLDER


def _desktop_dir() -> Path:
    profile = os.environ.get("USERPROFILE")
    base = Path(profile) if profile else Path.home()
    return base / "Desktop"


# -- shortcuts -------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    ole32 = ctypes.WinDLL("ole32")
    ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID)]
    ole32.CLSIDFromString.restype = ctypes.c_long
    value = _GUID()
    if ole32.CLSIDFromString(text, ctypes.byref(value)) < 0:
        raise OSError(f"invalid GUID: {text}")
    return value


def _vt_call(pointer, index: int, argtypes: list, args: list):
    """Call a COM vtable slot without a COM framework."""
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return prototype(table[index])(pointer, *args)


def create_shortcut(
    link_path: Path,
    target: Path,
    *,
    arguments: str = "",
    working_dir: Path | None = None,
    description: str = "",
    icon: Path | None = None,
) -> None:
    """Create a .lnk file through IShellLink.

    Implemented with ctypes because the build must not depend on pywin32.
    """
    link_path = Path(link_path).resolve()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    target = Path(target).resolve()
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitialize(None)

    clsid = _guid("{00021401-0000-0000-C000-000000000046}")  # ShellLink
    iid_link = _guid("{000214F9-0000-0000-C000-000000000046}")  # IShellLinkW
    iid_persist = _guid("{0000010b-0000-0000-C000-000000000046}")  # IPersistFile
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long

    link = ctypes.c_void_p()
    if ole32.CoCreateInstance(
        ctypes.byref(clsid), None, 1, ctypes.byref(iid_link), ctypes.byref(link)
    ) < 0:
        raise OSError("cannot create a shell link object")

    persist = ctypes.c_void_p()
    try:
        # IShellLinkW vtable: 20 SetPath, 11 SetArguments, 9 SetWorkingDirectory,
        # 7 SetDescription, 17 SetIconLocation.
        _vt_call(link, 20, [ctypes.c_wchar_p], [str(target)])
        if arguments:
            _vt_call(link, 11, [ctypes.c_wchar_p], [arguments])
        if working_dir is not None:
            _vt_call(link, 9, [ctypes.c_wchar_p], [str(working_dir)])
        if description:
            _vt_call(link, 7, [ctypes.c_wchar_p], [description])
        if icon is not None:
            _vt_call(link, 17, [ctypes.c_wchar_p, ctypes.c_int], [str(icon), 0])

        if (
            _vt_call(
                link,
                0,
                [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)],
                [ctypes.byref(iid_persist), ctypes.byref(persist)],
            )
            < 0
        ):
            raise OSError("cannot obtain IPersistFile")

        # IPersistFile: 6 Save.
        if _vt_call(persist, 6, [ctypes.c_wchar_p, ctypes.c_int], [str(link_path), 1]) < 0:
            raise OSError(f"cannot write {link_path}")
    finally:
        if persist:
            _vt_call(persist, 2, [], [])
        if link:
            _vt_call(link, 2, [], [])
        ole32.CoUninitialize()


# -- registry --------------------------------------------------------------
def write_uninstall_entry(target: Path, uninstall_exe: Path, size_bytes: int) -> None:
    import winreg

    display_icon = str(target / EXE_NAME)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE) as key:
        values = {
            "DisplayName": APP_NAME,
            "DisplayVersion": APP_VERSION,
            "Publisher": APP_PUBLISHER,
            "DisplayIcon": f"{display_icon},0",
            "InstallLocation": str(target),
            "UninstallString": f'"{uninstall_exe}"',
            "QuietUninstallString": f'"{uninstall_exe}" /S',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, int(size_bytes // 1024))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


# -- install ---------------------------------------------------------------
def _safe_extract(archive: zipfile.ZipFile, target: Path, progress: Progress | None) -> None:
    """Extract, refusing any member that would escape ``target``."""
    target_root = target.resolve()
    members = archive.infolist()
    total = max(1, len(members))
    for index, member in enumerate(members, start=1):
        destination = (target / member.filename).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise OSError(f"refusing to extract outside the install folder: {member.filename}")
        archive.extract(member, target)
        if progress is not None:
            progress(int(index * 100 / total), member.filename)


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def install(
    payload: Path,
    target: Path,
    *,
    desktop_shortcut: bool = True,
    start_menu_shortcut: bool = True,
    progress: Progress | None = None,
) -> list[str]:
    """Extract and register the application. Returns human-readable notes."""
    notes: list[str] = []
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    if progress is not None:
        progress(0, "")

    with zipfile.ZipFile(payload) as archive:
        _safe_extract(archive, target, progress)

    app_exe = target / EXE_NAME
    if not app_exe.is_file():
        raise OSError(f"{EXE_NAME} is missing from the payload")

    uninstall_exe = target / UNINSTALL_EXE
    if not uninstall_exe.is_file():
        notes.append(f"{UNINSTALL_EXE} is missing from the payload")

    if start_menu_shortcut:
        try:
            create_shortcut(
                _start_menu_dir() / f"{APP_NAME}.lnk",
                app_exe,
                working_dir=target,
                description=f"{APP_NAME} - downloads, organized",
                icon=app_exe,
            )
        except OSError as exc:
            notes.append(f"start menu shortcut: {exc}")

    if desktop_shortcut:
        try:
            create_shortcut(
                _desktop_dir() / f"{APP_NAME}.lnk",
                app_exe,
                working_dir=target,
                description=f"{APP_NAME} - downloads, organized",
                icon=app_exe,
            )
        except OSError as exc:
            notes.append(f"desktop shortcut: {exc}")

    try:
        write_uninstall_entry(target, uninstall_exe, directory_size(target))
    except OSError as exc:  # pragma: no cover - environmental
        notes.append(f"uninstall entry: {exc}")

    if progress is not None:
        progress(100, "")
    return notes


# -- translations ----------------------------------------------------------
STRINGS = {
    "en": {
        "title": "SmartSort setup",
        "subtitle": "Sorts finished downloads into date and type folders.",
        "location": "Install for the current user (no administrator rights needed)",
        "folder": "Install folder",
        "browse": "Browse…",
        "desktop": "Create a desktop shortcut",
        "start_menu": "Add to the Start menu",
        "launch": "Start SmartSort when setup finishes",
        "install": "Install",
        "cancel": "Cancel",
        "close": "Close",
        "installing": "Installing…",
        "done": "SmartSort is installed.",
        "failed": "Installation failed",
        "browse_title": "Choose a folder",
        "already": "That folder already contains SmartSort. Its files will be replaced.",
        "notes": "Some optional steps did not complete:",
    },
    "fa": {
        "title": "نصب SmartSort",
        "subtitle": "دانلودهای تمام‌شده را بر اساس تاریخ و نوع مرتب می‌کند.",
        "location": "نصب برای کاربر جاری (بدون نیاز به دسترسی ادمین)",
        "folder": "پوشهٔ نصب",
        "browse": "انتخاب…",
        "desktop": "میان‌بر روی دسکتاپ ساخته شود",
        "start_menu": "به منوی استارت اضافه شود",
        "launch": "پس از نصب، SmartSort اجرا شود",
        "install": "نصب",
        "cancel": "انصراف",
        "close": "بستن",
        "installing": "در حال نصب…",
        "done": "SmartSort نصب شد.",
        "failed": "نصب ناموفق بود",
        "browse_title": "انتخاب پوشه",
        "already": "این پوشه از قبل SmartSort دارد. فایل‌هایش جایگزین می‌شوند.",
        "notes": "برخی مراحل اختیاری انجام نشد:",
    },
}

_STYLESHEET = """
QWidget { background: #ffffff; color: #1f2937;
          font-family: "Segoe UI", "Vazirmatn", sans-serif; font-size: 13px; }
QLabel#title { font-size: 20px; font-weight: 600; color: #111827; }
QLabel#subtitle { color: #6b7280; }
QLabel#section { color: #6b7280; font-size: 12px; }
QLineEdit { border: 1px solid #d1d5db; border-radius: 8px; padding: 7px 10px;
            background: #ffffff; }
QLineEdit:focus { border-color: #2563eb; }
QPushButton { border: 1px solid #d1d5db; border-radius: 8px; padding: 7px 16px;
              background: #ffffff; }
QPushButton:hover { background: #f3f4f6; }
QPushButton#primary { background: #2563eb; border-color: #2563eb; color: #ffffff;
                      font-weight: 600; padding: 9px 22px; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #9ca3af; border-color: #9ca3af; }
QCheckBox { spacing: 8px; }
QProgressBar { border: none; border-radius: 4px; background: #e5e7eb; height: 6px;
               text-align: center; }
QProgressBar::chunk { background: #2563eb; border-radius: 4px; }
"""


def _language() -> str:
    try:
        langid = ctypes.WinDLL("kernel32").GetUserDefaultUILanguage()
    except (OSError, AttributeError):  # pragma: no cover - non-Windows
        return "en"
    return "fa" if (langid & 0x3FF) == 0x29 else "en"


def run_gui(payload: Path, target: Path) -> int:
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    language = _language()
    text = STRINGS[language]

    app = QApplication(sys.argv[:1])
    app.setApplicationName(f"{APP_NAME} Setup")
    if language == "fa":
        app.setLayoutDirection(Qt.RightToLeft)

    window = QWidget()
    window.setWindowTitle(text["title"])
    window.setFixedWidth(560)
    icon_file = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "smartsort.ico"
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
        window.setWindowIcon(QIcon(str(icon_file)))

    layout = QVBoxLayout(window)
    layout.setContentsMargins(28, 24, 28, 22)
    layout.setSpacing(10)

    title = QLabel(f"{APP_NAME} {APP_VERSION}")
    title.setObjectName("title")
    layout.addWidget(title)

    subtitle = QLabel(text["subtitle"])
    subtitle.setObjectName("subtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    location = QLabel(text["location"])
    location.setObjectName("section")
    location.setWordWrap(True)
    layout.addWidget(location)

    folder_row = QHBoxLayout()
    folder_edit = QLineEdit(str(target))
    browse = QPushButton(text["browse"])
    folder_row.addWidget(folder_edit, 1)
    folder_row.addWidget(browse)
    layout.addLayout(folder_row)

    desktop_box = QCheckBox(text["desktop"])
    desktop_box.setChecked(True)
    start_box = QCheckBox(text["start_menu"])
    start_box.setChecked(True)
    launch_box = QCheckBox(text["launch"])
    launch_box.setChecked(True)
    for box in (desktop_box, start_box, launch_box):
        layout.addWidget(box)

    progress = QProgressBar()
    progress.setRange(0, 100)
    progress.setTextVisible(False)
    progress.hide()
    layout.addWidget(progress)

    status = QLabel("")
    status.setObjectName("section")
    status.setWordWrap(True)
    layout.addWidget(status)

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton(text["cancel"])
    primary = QPushButton(text["install"])
    primary.setObjectName("primary")
    primary.setDefault(True)
    buttons.addWidget(cancel)
    buttons.addWidget(primary)
    layout.addLayout(buttons)

    state = {"done": False}

    class Worker(QThread):
        finished_ok = Signal(list)
        failed = Signal(str)
        tick = Signal(int, str)

        def run(self) -> None:
            try:
                notes = install(
                    payload,
                    Path(folder_edit.text().strip() or default_install_dir()),
                    desktop_shortcut=desktop_box.isChecked(),
                    start_menu_shortcut=start_box.isChecked(),
                    progress=lambda value, name: self.tick.emit(value, name),
                )
            except Exception as exc:  # noqa: BLE001 - reported to the user
                self.failed.emit(str(exc))
                return
            self.finished_ok.emit(notes)

    worker: Worker | None = None

    def browse_folder() -> None:
        chosen = QFileDialog.getExistingDirectory(window, text["browse_title"], folder_edit.text())
        if chosen:
            folder_edit.setText(chosen)

    def on_tick(value: int, name: str) -> None:
        progress.setValue(value)
        if name:
            status.setText(name)

    def set_busy(busy: bool) -> None:
        for widget in (folder_edit, browse, desktop_box, start_box, launch_box, primary):
            widget.setEnabled(not busy)
        progress.setVisible(busy)
        cancel.setText(text["close"] if busy else text["cancel"])

    def on_done(notes: list[str]) -> None:
        state["done"] = True
        set_busy(False)
        progress.setValue(100)
        status.setText(text["done"])
        if notes:
            status.setText(text["done"] + "\n" + text["notes"] + " " + "; ".join(notes))
        primary.setEnabled(True)
        primary.setText(text["close"])
        primary.setDefault(True)
        if launch_box.isChecked():
            target_exe = Path(folder_edit.text().strip()) / EXE_NAME
            if target_exe.is_file():
                try:
                    subprocess.Popen([str(target_exe)], cwd=str(target_exe.parent))
                except OSError:  # pragma: no cover - environmental
                    pass

    def on_failed(message: str) -> None:
        set_busy(False)
        QMessageBox.critical(window, text["failed"], message)
        primary.setEnabled(True)
        primary.setText(text["install"])

    def start_install() -> None:
        nonlocal worker
        if state["done"]:
            window.close()
            return
        destination = Path(folder_edit.text().strip() or default_install_dir())
        if (destination / EXE_NAME).exists():
            answer = QMessageBox.question(
                window,
                text["title"],
                text["already"],
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        set_busy(True)
        status.setText(text["installing"])
        worker = Worker()
        worker.tick.connect(on_tick)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_failed)
        worker.start()

    def on_cancel() -> None:
        if state["done"]:
            window.close()
            return
        window.close()

    browse.clicked.connect(browse_folder)
    primary.clicked.connect(start_install)
    cancel.clicked.connect(on_cancel)

    window.show()
    return app.exec()


# -- entry point -----------------------------------------------------------
def _normalise_argv(raw: list[str]) -> list[str]:
    """Translate the Windows-style switches into long options.

    ``argparse`` treats ``-D=value`` as the value ``=value`` for a short option,
    so ``/D=…`` is rewritten by hand rather than left to the parser.
    """
    out: list[str] = []
    for item in raw:
        upper = item.upper()
        if upper in {"/S", "-S"}:
            out.append("--silent")
        elif upper.startswith("/D=") or upper.startswith("-D="):
            out.extend(["--dir", item[3:]])
        elif upper in {"/?", "-?"}:
            out.append("--help")
        else:
            out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog=f"{APP_NAME}-Setup", add_help=False)
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--dir", dest="directory", default=None)
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--payload", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--help", action="store_true", dest="help")
    args, _unknown = parser.parse_known_args(_normalise_argv(raw))

    if args.help:
        print(__doc__)
        return 0

    payload = Path(args.payload) if args.payload else resource_path("payload.zip")
    if not payload.is_file():
        print(f"error: payload not found at {payload}", file=sys.stderr)
        return 2

    target = Path(args.directory) if args.directory else default_install_dir()

    if args.silent:
        try:
            notes = install(
                payload,
                target,
                desktop_shortcut=not args.no_shortcuts,
                start_menu_shortcut=not args.no_shortcuts,
            )
        except Exception as exc:  # noqa: BLE001 - reported on stderr
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"installed to {target}")
        for note in notes:
            print(f"note: {note}")
        return 0

    return run_gui(payload, target)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
