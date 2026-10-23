"""The "start with Windows" command must actually start the application.

A Run value has no working directory. A frozen build can therefore be launched
directly, but a source checkout cannot: ``-m smartsort.app.main`` only resolves
when the project root is the current directory. These tests pin both shapes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from smartsort.app.services import startup_service


def test_frozen_build_points_at_its_own_executable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\SmartSort\SmartSort.exe")

    command = startup_service.command_for_current_install()

    assert command == '"C:\\Apps\\SmartSort\\SmartSort.exe" --minimized'


def test_source_checkout_sets_the_working_directory(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    command = startup_service.command_for_current_install()
    root = Path(startup_service.__file__).resolve().parents[3]

    assert command.startswith("cmd /c cd /d ")
    assert str(root) in command, "the Run value must cd into the project root"
    assert "-m smartsort.app.main --minimized" in command


def test_source_checkout_prefers_pythonw(monkeypatch, tmp_path: Path) -> None:
    """python.exe would flash a console window at every sign-in."""
    console = tmp_path / "python.exe"
    console.write_bytes(b"")
    (tmp_path / "pythonw.exe").write_bytes(b"")

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(console))

    assert "pythonw.exe" in startup_service.command_for_current_install()
