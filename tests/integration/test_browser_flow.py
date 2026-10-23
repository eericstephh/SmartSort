"""End-to-end browser flow through the Qt controller.

The extension's JSON message is fed into ``AppController.handle_message`` - the
exact entry point used by the native host bridge - and the resulting file layout
is asserted on disk.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from smartsort.app.bootstrap import create_context  # noqa: E402
from tests.conftest import make_file  # noqa: E402

EXT_ID = "a" * 32


@pytest.fixture
def controller(tmp_path: Path, monkeypatch, qapp):
    """Build a controller on the session-wide QApplication provided by pytest-qt.

    Qt only allows one application object per process, so the tests must not
    create their own QCoreApplication/QApplication.
    """
    from smartsort.app.ui.controller import AppController

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("SMARTSORT_DATA_DIR", str(data_dir))
    context = create_context(data_dir, setup_logs=False)
    instance = AppController(context)
    try:
        yield instance
    finally:
        instance.shutdown()
        context.close()


def message_for(path: Path, **overrides) -> dict:
    payload = {
        "type": "download_completed",
        "protocolVersion": 1,
        "browser": "chrome",
        "extensionId": EXT_ID,
        "download": {
            "id": "1001",
            "filename": str(path),
            "state": "complete",
            "totalBytes": path.stat().st_size if path.exists() else 0,
            "exists": True,
        },
    }
    payload.update(overrides)
    return payload


def test_completed_download_is_organized_end_to_end(
    controller, tmp_path: Path
) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    source = make_file(tmp_path / "Downloads", "photo.jpg", b"jpeg")

    response = controller.handle_message(message_for(source))

    assert response["ok"] is True
    assert response["status"] == "organized"
    assert response["category"] == "images"
    expected_day = datetime.now().astimezone().date().isoformat()
    assert (destination / expected_day / "Images" / "photo.jpg").is_file()
    assert not source.exists()


def test_allow_list_rejects_a_message_that_omits_the_extension_id(
    controller, tmp_path: Path
) -> None:
    """An allow-list must bind every message, not just self-identifying ones.

    Omitting "extensionId" used to skip the check entirely, so the list was
    advisory: a process that knew the bridge token could act as any extension.
    """
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    controller.settings.allowed_extension_ids = [EXT_ID]
    source = make_file(tmp_path / "Downloads", "secret.pdf", b"pdf")

    message = message_for(source)
    message.pop("extensionId")
    response = controller.handle_message(message)

    assert response["ok"] is False
    assert response["error"] == "extension_not_allowed"
    assert source.is_file(), "the source must be left alone"
    assert list(destination.rglob("*.pdf")) == []


def test_allow_list_rejects_a_different_extension_id(controller, tmp_path: Path) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    controller.settings.allowed_extension_ids = ["b" * 32]
    source = make_file(tmp_path / "Downloads", "photo.jpg", b"jpeg")

    response = controller.handle_message(message_for(source))

    assert response["ok"] is False
    assert response["error"] == "extension_not_allowed"
    assert source.is_file()


def test_allow_list_still_accepts_the_registered_extension(
    controller, tmp_path: Path
) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    controller.settings.allowed_extension_ids = [EXT_ID]
    source = make_file(tmp_path / "Downloads", "photo.jpg", b"jpeg")

    response = controller.handle_message(message_for(source))

    assert response["ok"] is True
    assert response["status"] == "organized"
    assert not source.exists()


def test_ping_reports_readiness(controller, tmp_path: Path) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)

    response = controller.handle_message({"type": "ping", "browser": "edge"})
    assert response["ok"] is True
    assert response["app"] == "SmartSort"
    assert response["ready"] is True
    assert response["destination"] == str(destination)


def test_second_completion_for_the_same_download_is_deduplicated(
    controller, tmp_path: Path
) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    source = make_file(tmp_path / "Downloads", "file.pdf", b"pdf")

    first = controller.handle_message(message_for(source))
    second = controller.handle_message(message_for(source))

    assert first["status"] == "organized"
    assert second["status"] == "duplicate"
    assert len(list(destination.rglob("file.pdf"))) == 1


def test_invalid_message_is_rejected(controller) -> None:
    response = controller.handle_message({"type": "eval", "code": "import os"})
    assert response["ok"] is False
    assert response["error"] == "unknown_message_type"


def test_message_from_a_foreign_extension_is_rejected(
    controller, tmp_path: Path
) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    controller.settings.allowed_extension_ids = ["b" * 32]
    source = make_file(tmp_path / "Downloads", "x.txt", b"x")

    response = controller.handle_message(message_for(source))
    assert response["ok"] is False
    assert response["error"] == "extension_not_allowed"
    assert source.exists()


def test_cancelled_download_is_not_moved(controller, tmp_path: Path) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    source = make_file(tmp_path / "Downloads", "partial.zip", b"zip")

    payload = message_for(source)
    payload["type"] = "download_cancelled"
    response = controller.handle_message(payload)

    assert response["status"] == "skipped"
    assert source.exists()
    assert list(destination.rglob("*")) == []


def test_paused_controller_does_not_move_files(controller, tmp_path: Path) -> None:
    destination = tmp_path / "SmartSort"
    destination.mkdir()
    controller.settings.destination_dir = str(destination)
    controller.set_paused(True)
    source = make_file(tmp_path / "Downloads", "a.mp3", b"audio")

    response = controller.handle_message(message_for(source))
    assert response["status"] == "skipped"
    assert source.exists()
