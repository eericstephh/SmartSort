"""The release scripts' safety rails.

These are not part of the application, but the uninstaller deletes directories
and the installer parses Windows-style switches, so both deserve a guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def installer():
    return _load("installer_app")


@pytest.fixture(scope="module")
def uninstaller():
    return _load("uninstall_app")


def test_setup_accepts_windows_style_switches(installer) -> None:
    assert installer._normalise_argv(["/S"]) == ["--silent"]
    assert installer._normalise_argv(["/D=C:\\Apps\\SmartSort"]) == [
        "--dir",
        "C:\\Apps\\SmartSort",
    ]
    assert installer._normalise_argv(["--silent", "--no-shortcuts"]) == [
        "--silent",
        "--no-shortcuts",
    ]


def test_uninstaller_accepts_windows_style_switches(uninstaller) -> None:
    assert uninstaller._normalise_argv(["/S", "/PURGE"]) == ["--silent", "--purge"]


def test_uninstaller_refuses_a_folder_without_the_application(
    uninstaller, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    ok, reason = uninstaller._is_safe_to_delete(empty)
    assert ok is False
    assert "SmartSort.exe" in reason


def test_uninstaller_refuses_a_drive_root(uninstaller) -> None:
    ok, reason = uninstaller._is_safe_to_delete(Path("C:\\"))
    assert ok is False
    assert "drive root" in reason or "not a folder" in reason


def test_uninstaller_refuses_the_user_profile(uninstaller) -> None:
    home = Path(__import__("os").environ.get("USERPROFILE") or Path.home())
    if not home.is_dir():
        pytest.skip("no user profile on this platform")
    ok, _reason = uninstaller._is_safe_to_delete(home)
    assert ok is False


def test_uninstaller_accepts_a_real_install_folder(uninstaller, tmp_path: Path) -> None:
    target = tmp_path / "SmartSort"
    target.mkdir()
    (target / "SmartSort.exe").write_bytes(b"fake")
    ok, reason = uninstaller._is_safe_to_delete(target)
    assert ok is True, reason


def test_installer_extracts_without_escaping_the_target(
    installer, tmp_path: Path
) -> None:
    import zipfile

    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("SmartSort.exe", b"fake")
        archive.writestr("uninstall.exe", b"fake")
        archive.writestr("../../escaped.txt", b"nope")

    target = tmp_path / "install"
    with pytest.raises(OSError):
        installer.install(
            payload, target, desktop_shortcut=False, start_menu_shortcut=False
        )
    assert not (tmp_path.parent / "escaped.txt").exists()


def _fake_install(tmp_path: Path) -> Path:
    target = tmp_path / "SmartSort"
    target.mkdir()
    (target / "SmartSort.exe").write_bytes(b"fake")
    (target / "uninstall.exe").write_bytes(b"fake")
    return target


def _isolate(uninstaller, monkeypatch, tmp_path: Path) -> Path:
    """Point every side effect of uninstall() at the test's temporary folder."""
    data = tmp_path / "local" / "SmartSort"
    (data / "logs").mkdir(parents=True, exist_ok=True)
    (data / "smartsort.db").write_text("db", encoding="utf-8")
    monkeypatch.setattr(uninstaller, "user_data_dir", lambda: data)
    monkeypatch.setattr(uninstaller, "_desktop_link", lambda: tmp_path / "desk.lnk")
    monkeypatch.setattr(
        uninstaller, "_start_menu_link", lambda: tmp_path / "menu" / "SmartSort.lnk"
    )
    monkeypatch.setattr(uninstaller, "remove_registry", lambda: [])
    return data


def test_silent_uninstall_keeps_settings_and_history(
    uninstaller, monkeypatch, tmp_path: Path
) -> None:
    target = _fake_install(tmp_path)
    data = _isolate(uninstaller, monkeypatch, tmp_path)

    uninstaller.uninstall(target, purge_data=False)

    assert not target.exists()
    assert data.is_dir(), "silent mode must not delete user data"
    assert (data / "smartsort.db").is_file()


def test_purge_removes_settings_and_history(
    uninstaller, monkeypatch, tmp_path: Path
) -> None:
    target = _fake_install(tmp_path)
    data = _isolate(uninstaller, monkeypatch, tmp_path)

    uninstaller.uninstall(target, purge_data=True)

    assert not target.exists()
    assert not data.exists()


def test_dialog_failure_removes_nothing(uninstaller, monkeypatch) -> None:
    """A message box that cannot be shown must not count as consent."""
    performed: list[dict[str, object]] = []
    monkeypatch.setattr(
        uninstaller.ctypes.windll.user32, "MessageBoxW", lambda *args: 0
    )
    monkeypatch.setattr(
        uninstaller,
        "_perform",
        lambda target, **kwargs: performed.append(kwargs) or 0,
    )

    assert uninstaller.run_dialog(Path("C:/nowhere")) == 1
    assert performed == []


def test_dialog_no_keeps_user_data(uninstaller, monkeypatch) -> None:
    performed: list[dict[str, object]] = []
    monkeypatch.setattr(
        uninstaller.ctypes.windll.user32, "MessageBoxW", lambda *args: 7
    )
    monkeypatch.setattr(
        uninstaller,
        "_perform",
        lambda target, **kwargs: performed.append(kwargs) or 0,
    )

    assert uninstaller.run_dialog(Path("C:/nowhere")) == 0
    assert performed == [{"purge": False, "silent": False}]


def test_dialog_cancel_does_nothing(uninstaller, monkeypatch) -> None:
    performed: list[dict[str, object]] = []
    monkeypatch.setattr(
        uninstaller.ctypes.windll.user32, "MessageBoxW", lambda *args: 2
    )
    monkeypatch.setattr(
        uninstaller,
        "_perform",
        lambda target, **kwargs: performed.append(kwargs) or 0,
    )

    assert uninstaller.run_dialog(Path("C:/nowhere")) == 0
    assert performed == []


def test_the_version_is_the_same_everywhere() -> None:
    """One version, or the installer and the app disagree in Apps & features."""
    import re

    from smartsort.app.config import defaults

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert declared is not None, "pyproject.toml has no version"
    assert declared.group(1) == defaults.APP_VERSION

    for module in ("installer_app", "uninstall_app", "build_release"):
        source = (SCRIPTS / f"{module}.py").read_text(encoding="utf-8")
        assert f'APP_VERSION = "{defaults.APP_VERSION}"' in source, (
            f"{module}.py has a different APP_VERSION"
        )
