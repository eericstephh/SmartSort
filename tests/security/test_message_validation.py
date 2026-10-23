"""Security: every browser message is untrusted input."""

from __future__ import annotations

import pytest

from smartsort.app.browser.message_validation import (
    ValidationError,
    validate_message,
    validate_path,
)

EXT_ID = "a" * 32


def valid_payload(**overrides) -> dict:
    payload = {
        "type": "download_completed",
        "protocolVersion": 1,
        "browser": "chrome",
        "extensionId": EXT_ID,
        "download": {
            "id": "12345",
            "filename": "C:\\Users\\user\\Downloads\\report.pdf",
            "state": "complete",
            "totalBytes": 1024,
            "completedAt": "2026-10-21T10:00:00Z",
            "exists": True,
            "url": "https://example.com/report.pdf",
            "mime": "application/pdf",
        },
    }
    payload.update(overrides)
    return payload


def test_valid_message_is_accepted() -> None:
    message = validate_message(valid_payload())
    assert message["type"] == "download_completed"
    assert message["browser"] == "chrome"
    assert message["download"]["id"] == "12345"
    assert message["download"]["filename"].endswith("report.pdf")
    assert message["download"]["completedAt"].endswith("+00:00")


def test_ping_does_not_require_a_download() -> None:
    message = validate_message({"type": "ping", "browser": "edge"})
    assert message["type"] == "ping"


def test_non_object_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_message(["not", "a", "dict"])


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError) as info:
        validate_message({"type": "run_command"})
    assert info.value.code == "unknown_message_type"


def test_newer_protocol_version_is_rejected() -> None:
    with pytest.raises(ValidationError) as info:
        validate_message(valid_payload(protocolVersion=99))
    assert info.value.code == "unsupported_protocol_version"


def test_boolean_version_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_message(valid_payload(protocolVersion=True))


def test_missing_download_object_is_rejected() -> None:
    payload = valid_payload()
    del payload["download"]
    with pytest.raises(ValidationError) as info:
        validate_message(payload)
    assert info.value.code == "missing_download"


def test_missing_download_id_is_rejected() -> None:
    payload = valid_payload()
    del payload["download"]["id"]
    with pytest.raises(ValidationError) as info:
        validate_message(payload)
    assert info.value.code == "missing_download_id"


@pytest.mark.parametrize(
    "bad_id",
    ["has space", "semi;colon", "a" * 200, "new\nline", "", "../../etc"],
)
def test_invalid_download_ids_are_rejected(bad_id: str) -> None:
    payload = valid_payload()
    payload["download"]["id"] = bad_id
    with pytest.raises(ValidationError):
        validate_message(payload)


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Users\\..\\..\\Windows\\System32\\evil.exe",
        "C:\\a\\..\\..\\b.txt",
        "relative\\file.txt",
        "file.txt",
        "",
        "\\\\?\\C:\\device\\path.txt",
        "\\\\.\\PhysicalDrive0",
        "C:\\bad\x00name.txt",
    ],
)
def test_unsafe_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        validate_path(path)


def test_unc_path_is_accepted() -> None:
    assert validate_path("\\\\server\\share\\file.txt").startswith("\\\\server\\share")


def test_path_with_forward_slashes_is_normalised() -> None:
    assert validate_path("C:/Users/user/Downloads/a.pdf") == "C:\\Users\\user\\Downloads\\a.pdf"


def test_invalid_extension_id_is_rejected() -> None:
    with pytest.raises(ValidationError) as info:
        validate_message(valid_payload(extensionId="zzzz"))
    assert info.value.code == "invalid_extension_id"


def test_extension_id_with_invalid_alphabet_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_message(valid_payload(extensionId="z" * 32))


@pytest.mark.parametrize(
    "timestamp",
    ["yesterday", "2026-13-45T99:99:99Z", "2026-10-21", 12345, None],
)
def test_invalid_timestamps_are_rejected(timestamp) -> None:
    payload = valid_payload()
    payload["download"]["completedAt"] = timestamp
    if timestamp is None:
        # "not provided" is allowed and simply means "use the local clock".
        assert validate_message(payload)["download"]["completedAt"] is None
        return
    with pytest.raises(ValidationError):
        validate_message(payload)


def test_negative_total_bytes_is_rejected() -> None:
    payload = valid_payload()
    payload["download"]["totalBytes"] = -1
    with pytest.raises(ValidationError):
        validate_message(payload)


def test_non_boolean_exists_is_rejected() -> None:
    payload = valid_payload()
    payload["download"]["exists"] = "yes"
    with pytest.raises(ValidationError):
        validate_message(payload)


def test_overlong_url_is_rejected() -> None:
    payload = valid_payload()
    payload["download"]["url"] = "https://x/" + "a" * 9000
    with pytest.raises(ValidationError):
        validate_message(payload)


def test_unknown_browser_is_normalised_to_unknown() -> None:
    message = validate_message(valid_payload(browser="netscape-navigator"))
    assert message["browser"] == "unknown"


def test_oversized_filename_is_rejected() -> None:
    payload = valid_payload()
    payload["download"]["filename"] = "C:\\Downloads\\" + "a" * 400
    with pytest.raises(ValidationError):
        validate_message(payload)
