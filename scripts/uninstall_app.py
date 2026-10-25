"""SmartSort uninstaller.

Removes the shortcuts, the "Apps & features" entry, the start-with-Windows value
and the native messaging registrations, then deletes the install folder. User
data under ``%LOCALAPPDATA%\\SmartSort`` is kept unless the user asks otherwise.

The program cannot delete the executable it is running from, so it first moves
itself into a temporary folder — Windows keeps the image handle valid — and then
deletes the install folder it came from.

    uninstall.exe                 interactive
    uninstall.exe /S              silent, keeps user data
    uninstall.exe /S /PURGE       silent, removes user data too
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP_NAME = "SmartSort"
APP_VERSION = "1.1.0"
EXE_NAME = "SmartSort.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SmartSort"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SmartSort"
START_MENU_FOLDER = "SmartSort"

BROWSER_ROOTS = (
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
)
NATIVE_HOST_NAME = "com.smartsort.host"


# -- paths -----------------------------------------------------------------
def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent / "dist" / APP_NAME


def user_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / APP_NAME


def _desktop_link() -> Path:
    profile = os.environ.get("USERPROFILE")
    base = Path(profile) if profile else Path.home()
    return base / "Desktop" / f"{APP_NAME}.lnk"


def _start_menu_link() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / START_MENU_FOLDER / f"{APP_NAME}.lnk"


# -- registry --------------------------------------------------------------
def _delete_tree(root: str, path: str) -> bool:
    """Delete a registry key and its children. Returns True when removed."""
    import winreg

    full = f"{root}\\{path}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, full, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(root, f"{path}\\{child}")
    except OSError:
        return False
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, full)
        return True
    except OSError:
        return False


def remove_registry() -> list[str]:
    import winreg

    removed: list[str] = []

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, RUN_VALUE)
            removed.append("start with Windows")
    except OSError:
        pass

    for root in BROWSER_ROOTS:
        if _delete_tree(root, NATIVE_HOST_NAME):
            removed.append(f"native host: {root.rsplit(chr(92), 1)[-1]}")

    if _delete_tree(r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "SmartSort"):
        removed.append("uninstall entry")

    return removed


# -- deletion --------------------------------------------------------------
def _is_safe_to_delete(path: Path) -> tuple[bool, str]:
    """Refuse anything that is not clearly a SmartSort install folder."""
    try:
        resolved = path.resolve()
    except OSError as exc:
        return False, f"cannot resolve {path}: {exc}"
    if not resolved.is_dir():
        return False, f"{resolved} is not a folder"
    if len(resolved.parts) < 3:
        return False, f"refusing to delete {resolved}: too close to the drive root"
    if not (resolved / EXE_NAME).is_file():
        return False, f"refusing to delete {resolved}: {EXE_NAME} is not there"
    home = Path(os.environ.get("USERPROFILE") or Path.home()).resolve()
    if resolved == home:
        return False, "refusing to delete the user profile"
    return True, ""


def remove_folder(path: Path) -> None:
    ok, reason = _is_safe_to_delete(path)
    if not ok:
        raise OSError(reason)
    try:
        shutil.rmtree(path)
    except OSError:
        # The running executable is usually the only thing that cannot go; take
        # everything else and report honestly rather than leaving a full tree.
        _remove_contents(path)
        raise


def _remove_contents(path: Path) -> None:
    for item in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        except OSError:
            continue


def remove_data(path: Path) -> bool:
    if not path.is_dir():
        return False
    if not (path / "smartsort.db").exists() and not (path / "logs").is_dir():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def uninstall(target: Path, *, purge_data: bool) -> list[str]:
    notes: list[str] = []

    for link in (_desktop_link(), _start_menu_link()):
        try:
            if link.is_file():
                link.unlink()
                notes.append(f"removed {link.name}")
        except OSError as exc:
            notes.append(f"{link.name}: {exc}")

    try:
        start_folder = _start_menu_link().parent
        if start_folder.is_dir() and not any(start_folder.iterdir()):
            start_folder.rmdir()
    except OSError:
        pass

    notes.extend(remove_registry())

    if purge_data:
        if remove_data(user_data_dir()):
            notes.append("removed settings and history")
        else:
            notes.append("settings folder was already gone")

    remove_folder(target)
    notes.append(f"removed {target}")
    return notes


# -- entry point -----------------------------------------------------------
def _detach_self() -> Path | None:
    """Move the running executable out of the folder it is about to delete.

    Windows keeps the image handle valid when a running executable is renamed or
    moved, so the process carries on while the install folder becomes fully
    deletable. This is deliberately preferred over copying ourselves to a
    temporary folder and spawning that copy: no second process, and nothing has
    to be executed from %TEMP%.
    """
    staging = Path(tempfile.mkdtemp(prefix="smartsort-uninstall-"))
    destination = staging / "uninstall.exe"
    try:
        os.replace(sys.executable, destination)
    except OSError:
        try:
            staging.rmdir()
        except OSError:
            pass
        return None
    # A process cannot delete the directory it is sitting in, and the shell may
    # have started us from inside the install folder. Move the working directory
    # out of the way before anything tries to remove it.
    try:
        os.chdir(staging)
    except OSError:  # pragma: no cover - environmental
        pass
    return destination


def run_dialog(target: Path) -> int:
    """Ask what to remove using a native message box.

    The uninstaller deliberately carries no GUI toolkit: a PySide6 build would
    add ~40 MB to every installation, and a self-contained binary is required
    anyway so it can move itself out of the folder it is about to delete.

    The default button is **No** (keep settings and history): a user who presses
    Enter out of habit must not lose their data. A message box that fails to
    appear returns 0, and that is treated as "cancel" rather than "uninstall
    without asking".
    """
    persian = (ctypes.WinDLL("kernel32").GetUserDefaultUILanguage() & 0x3FF) == 0x29
    if persian:
        title = "حذف SmartSort"
        body = (
            f"SmartSort از این پوشه حذف می‌شود:\n{target}\n\n"
            "بله: حذف، همراه با پاک کردن تنظیمات و تاریخچه\n"
            "خیر: حذف، ولی نگه داشتن تنظیمات و تاریخچه\n"
            "انصراف: هیچ کاری نکن"
        )
    else:
        title = "Uninstall SmartSort"
        body = (
            f"SmartSort will be removed from:\n{target}\n\n"
            "Yes: remove it and delete settings and history\n"
            "No: remove it but keep settings and history\n"
            "Cancel: do nothing"
        )

    mb_yesnocancel = 0x00000003
    mb_iconquestion = 0x00000020
    mb_defbutton2 = 0x00000100  # Enter selects "No" — the non-destructive choice
    answer = ctypes.windll.user32.MessageBoxW(
        None, body, title, mb_yesnocancel | mb_iconquestion | mb_defbutton2
    )
    if answer == 2:  # IDCANCEL
        return 0
    if answer not in (6, 7):  # IDYES, IDNO
        print(
            "error: the confirmation dialog could not be shown; nothing was removed.\n"
            "       run 'uninstall.exe /S' to uninstall without a prompt.",
            file=sys.stderr,
        )
        return 1
    return _perform(target, purge=answer == 6, silent=False)


def _perform(target: Path, *, purge: bool, silent: bool) -> int:
    # Absolute before anything changes the working directory: _detach_self()
    # moves the process into a temporary folder, and a relative target would
    # then resolve somewhere else entirely.
    target = Path(target).resolve()
    moved = _detach_self()
    try:
        notes = uninstall(target, purge_data=purge)
    except OSError as exc:
        if not silent:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "SmartSort", 0x00000010)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for note in notes:
        print(note)

    if not silent:
        ctypes.windll.user32.MessageBoxW(
            None, "SmartSort has been removed.", "Uninstall SmartSort", 0x00000040
        )

    if moved is not None:
        # Still open by this process, so this normally fails; it is only here to
        # tidy up on the platforms that allow it.
        try:
            moved.unlink()
        except OSError:
            pass
    return 0


def _normalise_argv(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        upper = item.upper()
        if upper in {"/S", "-S"}:
            out.append("--silent")
        elif upper in {"/PURGE", "-PURGE"}:
            out.append("--purge")
        elif upper in {"/?", "-?"}:
            out.append("--help")
        else:
            out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="uninstall", add_help=False)
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--target", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--help", action="store_true", dest="help")
    args, _unknown = parser.parse_known_args(_normalise_argv(raw))

    if args.help:
        print(__doc__)
        return 0

    target = Path(args.target).resolve() if args.target else install_dir()
    if not target.is_dir():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 1

    if args.silent:
        return _perform(target, purge=args.purge, silent=True)

    return run_dialog(target)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
