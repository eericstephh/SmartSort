"""Command line surface of the application.

These tests cover the maintenance flags, which are the ones an installer or a
support script relies on. They must not need a window, so they run before any
QApplication is created.
"""

from __future__ import annotations

import pytest

from smartsort.app.config.defaults import APP_NAME, APP_VERSION
from smartsort.app.main import main


@pytest.fixture(autouse=True)
def _clear_data_dir_override(monkeypatch):
    """--data-dir writes to the environment; never leak that into other tests."""
    monkeypatch.delenv("SMARTSORT_DATA_DIR", raising=False)
    yield
    monkeypatch.delenv("SMARTSORT_DATA_DIR", raising=False)


def test_version_flag_prints_and_exits(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"{APP_NAME} {APP_VERSION}"


def test_print_paths_uses_the_default_location(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert main(["--print-paths"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / APP_NAME) in out
    assert "smartsort.db" in out
    assert "com.smartsort.host.json" in out


def test_print_paths_honours_data_dir(tmp_path, capsys):
    """Regression: --data-dir used to be applied after the maintenance branch
    returned, so it was silently ignored by --print-paths and
    --register-host."""
    target = tmp_path / "custom-data"
    assert main(["--data-dir", str(target), "--print-paths"]) == 0

    out = capsys.readouterr().out
    assert str(target) in out
    assert str(target / "smartsort.db") in out
    assert str(target / "native-host" / "com.smartsort.host.json") in out


def test_print_paths_reports_a_launcher(capsys):
    assert main(["--print-paths"]) == 0
    out = capsys.readouterr().out
    launcher = next(line for line in out.splitlines() if line.startswith("launcher:"))
    assert launcher.split(":", 1)[1].strip()


def test_scan_previews_without_moving_anything(tmp_path, capsys):
    data_dir = tmp_path / "data"
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "photo.jpg").write_bytes(b"jpeg")
    (folder / "half.mp4.crdownload").write_bytes(b"partial")

    # A destination has to exist before the preview can name a target folder.
    from smartsort.app.bootstrap import create_context

    context = create_context(data_dir, setup_logs=False)
    context.settings.destination_dir = str(tmp_path / "Dest")
    context.close()

    code = main(["--data-dir", str(data_dir), "--scan", str(folder)])

    assert code == 0
    out = capsys.readouterr().out
    assert "photo.jpg" in out
    assert "images" in out
    assert "file_still_downloading" in out
    assert "1 of 2 files can be organized" in out
    assert (folder / "photo.jpg").exists(), "a preview must not move the file"
    assert not (tmp_path / "Dest").exists(), "a preview must not create folders"


def test_scan_without_a_destination_fails_clearly(tmp_path, capsys):
    data_dir = tmp_path / "data"
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "photo.jpg").write_bytes(b"jpeg")

    code = main(["--data-dir", str(data_dir), "--scan", str(folder)])

    assert code == 2
    assert "no destination folder configured" in capsys.readouterr().err


def test_registering_pins_the_allow_list(tmp_path, monkeypatch, capsys):
    """Registering the host must also pin the extension IDs.

    An empty allow-list accepts any extension, so a registration that only
    wrote the registry key would leave the bridge unbound.
    """
    from smartsort.app.bootstrap import create_context
    from smartsort.app.main import _pin_extension_ids

    data_dir = tmp_path / "data"
    monkeypatch.setenv("SMARTSORT_DATA_DIR", str(data_dir))
    extension_id = "a" * 32

    _pin_extension_ids([extension_id])

    assert extension_id in capsys.readouterr().out

    context = create_context(data_dir, setup_logs=False)
    try:
        assert context.settings.allowed_extension_ids == [extension_id]
    finally:
        context.close()
