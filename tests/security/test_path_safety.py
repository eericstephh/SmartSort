"""Security: the organizer must not be usable to escape the destination."""

from __future__ import annotations

from pathlib import Path

from smartsort.app.core.conflict_resolver import sanitize_filename
from smartsort.app.core.organizer import Organizer
from smartsort.app.storage.models import OrganizeRequest
from tests.conftest import make_file


def test_traversal_in_suggested_name_is_neutralised(
    organizer: Organizer, configured, downloads_dir: Path, destination: Path
) -> None:
    source = make_file(downloads_dir, "innocent.txt", b"x")
    result = organizer.organize(
        OrganizeRequest(
            source_path=str(source),
            origin="browser",
            suggested_name="..\\..\\..\\Windows\\System32\\payload.dll",
        )
    )
    assert result.status == "organized"
    final = Path(result.final_path).resolve()
    assert destination.resolve() in final.parents
    assert final.name == "payload.dll"


def test_absolute_suggested_name_is_reduced_to_a_file_name() -> None:
    assert sanitize_filename("C:\\Windows\\System32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("/etc/shadow") == "shadow"


def test_reserved_device_names_are_escaped() -> None:
    for name in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
        assert sanitize_filename(name).startswith("_")


def test_control_characters_are_removed() -> None:
    assert "\x01" not in sanitize_filename("bad\x01name.txt")


def test_never_organizes_the_destination_root_itself(
    organizer: Organizer, configured, destination: Path
) -> None:
    result = organizer.organize(
        OrganizeRequest(source_path=str(destination), origin="manual")
    )
    assert result.status in {"failed", "skipped"}
    assert destination.is_dir()


def test_symlinked_source_inside_destination_is_left_alone(
    organizer: Organizer, configured, destination: Path
) -> None:
    inner = destination / "already"
    inner.mkdir()
    source = make_file(inner, "file.txt")
    result = organizer.organize(OrganizeRequest(source_path=str(source), origin="browser"))
    assert result.status == "skipped"
    assert source.exists()


def test_extension_allow_list_blocks_other_extensions() -> None:
    from smartsort.app.browser.message_validation import ValidationError, validate_message

    payload = {
        "type": "download_completed",
        "browser": "chrome",
        "extensionId": "b" * 32,
        "download": {"id": "1", "filename": "C:\\Downloads\\a.txt"},
    }
    message = validate_message(payload)
    assert message["extensionId"] == "b" * 32


def test_system_directories_are_never_organized(
    organizer: Organizer, configured, tmp_path: Path, monkeypatch
) -> None:
    """A browser message may name any path; system folders are refused.

    The guard runs before ``stat()``, so a hostile message cannot even make the
    app touch a system directory.
    """
    fake_windows = tmp_path / "FakeWindows"
    fake_windows.mkdir()
    payload = make_file(fake_windows, "system32.dll", b"binary")
    monkeypatch.setenv("SystemRoot", str(fake_windows))

    result = organizer.organize(
        OrganizeRequest(source_path=str(payload), origin="browser", download_id="42")
    )

    assert result.status == "skipped"
    assert result.message == "protected_location"
    assert payload.exists(), "the system file must be untouched"


def test_protected_location_detection_covers_the_usual_roots(monkeypatch, tmp_path) -> None:
    from smartsort.app.core.fileops import is_protected_location

    fake_program_files = tmp_path / "PF"
    fake_program_files.mkdir()
    monkeypatch.setenv("ProgramFiles", str(fake_program_files))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramData", raising=False)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "W"))

    assert is_protected_location(fake_program_files / "App" / "tool.exe")
    assert is_protected_location(tmp_path / "W" / "System32" / "drivers" / "etc" / "hosts")
    assert not is_protected_location(tmp_path / "Downloads" / "photo.jpg")
