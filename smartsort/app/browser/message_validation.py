"""Validation of everything that arrives from a browser extension.

Browser messages are untrusted input. Every field is type-checked, length
limited and normalised before it can reach the organizer, and paths are
rejected unless they are absolute, traversal-free, local Windows paths.
"""

from __future__ import annotations

import ntpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config.defaults import (
    EXTENSION_ID_LENGTH,
    MAX_FILENAME_LENGTH,
    MAX_PATH_LENGTH,
    PROTOCOL_VERSION,
)

SUPPORTED_TYPES = {
    "hello",
    "ping",
    "status",
    "download_started",
    "download_progress",
    "download_completed",
    "download_interrupted",
    "download_cancelled",
}

SUPPORTED_BROWSERS = {"chrome", "edge", "chromium", "brave", "opera", "vivaldi", "unknown"}

_DOWNLOAD_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_EXTENSION_ID_RE = re.compile(rf"^[a-p]{{{EXTENSION_ID_LENGTH}}}$")
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:?\d{2})?$"
)

MAX_TOTAL_BYTES = 10**15


@dataclass(frozen=True)
class ValidationError(Exception):
    code: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.detail}" if self.detail else self.code


def validate_message(raw: Any) -> dict[str, Any]:
    """Return a normalised message or raise :class:`ValidationError`."""
    if not isinstance(raw, dict):
        raise ValidationError("invalid_message", "message must be a JSON object")

    msg_type = raw.get("type")
    if not isinstance(msg_type, str) or msg_type not in SUPPORTED_TYPES:
        raise ValidationError("unknown_message_type", str(msg_type)[:64])

    version = raw.get("protocolVersion", PROTOCOL_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValidationError("invalid_protocol_version")
    if version < 1:
        raise ValidationError("invalid_protocol_version")
    if version > PROTOCOL_VERSION:
        raise ValidationError(
            "unsupported_protocol_version",
            f"extension speaks v{version}, app supports v{PROTOCOL_VERSION}",
        )

    normalised: dict[str, Any] = {
        "type": msg_type,
        "protocolVersion": version,
    }

    extension_id = raw.get("extensionId")
    if extension_id is not None:
        normalised["extensionId"] = validate_extension_id(extension_id)

    browser = raw.get("browser", "unknown")
    if not isinstance(browser, str):
        raise ValidationError("invalid_browser")
    browser = browser.strip().lower()
    if browser not in SUPPORTED_BROWSERS:
        browser = "unknown"
    normalised["browser"] = browser

    if msg_type in {"hello", "ping", "status"}:
        return normalised

    payload = raw.get("download")
    if not isinstance(payload, dict):
        raise ValidationError("missing_download", "download object is required")

    download = _validate_download(payload, msg_type)
    normalised["download"] = download
    return normalised


def validate_extension_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("invalid_extension_id")
    candidate = value.strip().lower()
    if not _EXTENSION_ID_RE.match(candidate):
        raise ValidationError("invalid_extension_id", "expected 32 characters a-p")
    return candidate


def validate_path(value: Any) -> str:
    """Validate and normalise an absolute Windows path from a browser."""
    if not isinstance(value, str):
        raise ValidationError("invalid_path", "path must be a string")
    raw = value.strip()
    if not raw:
        raise ValidationError("invalid_path", "path is empty")
    if "\x00" in raw:
        raise ValidationError("invalid_path", "path contains a NUL byte")
    if len(raw) > MAX_PATH_LENGTH:
        raise ValidationError("invalid_path", "path is too long")

    # Reject traversal before normalisation so that "C:\a\..\..\b" is refused
    # even though normpath would silently collapse it.
    segments = [seg for seg in re.split(r"[\\/]+", raw) if seg not in ("", ".")]
    if any(seg == ".." for seg in segments):
        raise ValidationError("path_traversal", "path contains '..' segments")

    if raw.startswith("\\\\?\\") or raw.startswith("\\\\.\\"):
        raise ValidationError("invalid_path", "device paths are not allowed")

    normalised = ntpath.normpath(raw)
    if not ntpath.isabs(normalised):
        raise ValidationError("invalid_path", "path must be absolute")

    drive, _tail = ntpath.splitdrive(normalised)
    if not drive:
        raise ValidationError("invalid_path", "path must include a drive or share")

    if len(ntpath.basename(normalised)) > MAX_FILENAME_LENGTH:
        raise ValidationError("invalid_path", "file name is too long")

    return normalised


def _validate_download(payload: dict[str, Any], msg_type: str) -> dict[str, Any]:
    download_id = payload.get("id")
    if download_id is None and msg_type == "download_completed":
        raise ValidationError("missing_download_id")
    if download_id is not None:
        if isinstance(download_id, bool):
            raise ValidationError("invalid_download_id")
        if isinstance(download_id, int):
            download_id = str(download_id)
        if not isinstance(download_id, str) or not _DOWNLOAD_ID_RE.match(download_id):
            raise ValidationError("invalid_download_id")
    else:
        download_id = None

    filename = payload.get("filename")
    if filename is not None:
        filename = validate_path(filename)
    elif msg_type == "download_completed":
        raise ValidationError("missing_filename")

    state = payload.get("state")
    if state is not None and not isinstance(state, str):
        raise ValidationError("invalid_state")

    total_bytes = payload.get("totalBytes")
    if total_bytes is not None:
        if isinstance(total_bytes, bool) or not isinstance(total_bytes, int):
            raise ValidationError("invalid_total_bytes")
        if total_bytes < 0 or total_bytes > MAX_TOTAL_BYTES:
            raise ValidationError("invalid_total_bytes")

    completed_at = payload.get("completedAt")
    if completed_at is not None:
        completed_at = _validate_timestamp(completed_at)

    exists = payload.get("exists", True)
    if not isinstance(exists, bool):
        raise ValidationError("invalid_exists_flag")

    url = payload.get("url")
    if url is not None:
        if not isinstance(url, str) or len(url) > 8192:
            raise ValidationError("invalid_url")
        url = url.strip()

    mime = payload.get("mime")
    if mime is not None:
        if not isinstance(mime, str) or len(mime) > 200:
            raise ValidationError("invalid_mime")

    danger = payload.get("danger")
    if danger is not None and (not isinstance(danger, str) or len(danger) > 32):
        raise ValidationError("invalid_danger")

    return {
        "id": download_id,
        "filename": filename,
        "state": state,
        "totalBytes": total_bytes,
        "completedAt": completed_at,
        "exists": exists,
        "url": url,
        "mime": mime,
        "danger": danger,
    }


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        raise ValidationError("invalid_timestamp", "expected an ISO 8601 timestamp")
    text = value.strip()
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValidationError("invalid_timestamp", str(exc)) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_completed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
