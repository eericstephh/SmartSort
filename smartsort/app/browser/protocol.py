"""Native messaging wire protocol.

Chrome and Edge native messaging use the same framing on all platforms:

    <4-byte unsigned length, little endian><UTF-8 encoded JSON>

Reading and writing are deliberately strict: a frame larger than
``MAX_MESSAGE_BYTES`` aborts the connection instead of allocating memory.
"""

from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO

from ..config.defaults import MAX_MESSAGE_BYTES

_HEADER = struct.Struct("<I")


class ProtocolError(Exception):
    """Raised for malformed framing. The connection should be dropped."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks:
                return None
            raise ProtocolError("truncated_message", f"expected {size} bytes")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one framed message.

    Returns ``None`` on a clean end-of-stream (the browser closed the port).
    """
    header = _read_exact(stream, _HEADER.size)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    if length == 0:
        raise ProtocolError("empty_message")
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            "message_too_large", f"{length} bytes exceeds the {MAX_MESSAGE_BYTES} byte limit"
        )
    body = _read_exact(stream, length)
    if body is None:
        raise ProtocolError("truncated_message", "header without body")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid_json", str(exc)) from exc
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_message", "top level value must be an object")
    return payload


def encode_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message_too_large", f"{len(body)} bytes")
    return _HEADER.pack(len(body)) + body


def write_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    stream.write(encode_message(payload))
    stream.flush()


def error_response(code: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    response: dict[str, Any] = {"ok": False, "error": code}
    if detail:
        response["detail"] = detail
    response.update(extra)
    return response


def ok_response(**payload: Any) -> dict[str, Any]:
    response: dict[str, Any] = {"ok": True}
    response.update(payload)
    return response
