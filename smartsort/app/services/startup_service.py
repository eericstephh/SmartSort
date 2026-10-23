"""Opt-in "start with Windows" support.

Only a single value under ``HKCU\\...\\CurrentVersion\\Run`` is written. Nothing
is written to ``HKLM``, no scheduled task is created, and no security setting is
touched.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SmartSort"


class StartupUnavailable(RuntimeError):
    pass


def _winreg():
    if sys.platform != "win32":
        raise StartupUnavailable("start with Windows is only supported on Windows")
    import winreg

    return winreg


def command_for_current_install() -> str:
    """Build the command line used by the Run key.

    A frozen build is self-contained, so the executable can be launched directly.
    A source checkout cannot: ``-m smartsort.app.main`` only resolves when the
    working directory is the project root, and a Run value has no notion of a
    working directory. The command therefore sets it with ``cd /d``. Where
    ``pythonw.exe`` exists it is preferred, so no console window flashes at
    sign-in.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'

    interpreter = Path(sys.executable)
    windowed = interpreter.with_name("pythonw.exe")
    if windowed.is_file():
        interpreter = windowed

    project_root = Path(__file__).resolve().parents[3]
    return (
        f'cmd /c cd /d "{project_root}" && "{interpreter}" '
        f"-m smartsort.app.main --minimized"
    )


def is_enabled() -> bool:
    try:
        winreg = _winreg()
    except StartupUnavailable:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(str(value).strip())
    except OSError:
        return False


def enable(command: str | None = None) -> bool:
    try:
        winreg = _winreg()
    except StartupUnavailable:
        return False
    cmd = command or command_for_current_install()
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
    except OSError as exc:  # pragma: no cover - environmental
        logger.warning("could not enable start with Windows: %s", exc)
        return False
    logger.info("start with Windows enabled: %s", cmd)
    return True


def disable() -> bool:
    try:
        winreg = _winreg()
    except StartupUnavailable:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return True
    except OSError as exc:  # pragma: no cover - environmental
        logger.warning("could not disable start with Windows: %s", exc)
        return False
    logger.info("start with Windows disabled")
    return True


def apply(enabled: bool) -> bool:
    return enable() if enabled else disable()
