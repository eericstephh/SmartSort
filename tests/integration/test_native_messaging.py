"""Integration tests for the native messaging pipeline.

These exercise the real wire format, the real named pipe and a real
``native_host`` subprocess - not mocks.
"""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from smartsort.app.browser.bridge_server import BridgeServer, ensure_token
from smartsort.app.browser.protocol import (
    ProtocolError,
    encode_message,
    read_message,
    write_message,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPE_PREFIX = r"\\.\pipe\smartsort-test-"


@pytest.fixture
def pipe_name() -> str:
    return PIPE_PREFIX + uuid.uuid4().hex


# -- framing --------------------------------------------------------------
def test_roundtrip_single_message() -> None:
    buffer = io.BytesIO()
    write_message(buffer, {"type": "ping", "value": 1})
    buffer.seek(0)
    assert read_message(buffer) == {"type": "ping", "value": 1}


def test_roundtrip_multiple_messages() -> None:
    buffer = io.BytesIO()
    write_message(buffer, {"type": "a"})
    write_message(buffer, {"type": "b"})
    buffer.seek(0)
    assert read_message(buffer) == {"type": "a"}
    assert read_message(buffer) == {"type": "b"}
    assert read_message(buffer) is None


def test_header_is_little_endian_length() -> None:
    frame = encode_message({"type": "ping"})
    length = struct.unpack("<I", frame[:4])[0]
    assert length == len(frame) - 4


def test_eof_returns_none() -> None:
    assert read_message(io.BytesIO(b"")) is None


def test_oversized_message_is_rejected() -> None:
    header = struct.pack("<I", 10 * 1024 * 1024)
    with pytest.raises(ProtocolError) as info:
        read_message(io.BytesIO(header))
    assert info.value.code == "message_too_large"


def test_truncated_body_is_rejected() -> None:
    frame = struct.pack("<I", 100) + b"{"
    with pytest.raises(ProtocolError) as info:
        read_message(io.BytesIO(frame))
    assert info.value.code == "truncated_message"


def test_invalid_json_is_rejected() -> None:
    body = b"not json"
    frame = struct.pack("<I", len(body)) + body
    with pytest.raises(ProtocolError) as info:
        read_message(io.BytesIO(frame))
    assert info.value.code == "invalid_json"


def test_non_object_payload_is_rejected() -> None:
    body = b"[1,2,3]"
    frame = struct.pack("<I", len(body)) + body
    with pytest.raises(ProtocolError) as info:
        read_message(io.BytesIO(frame))
    assert info.value.code == "invalid_message"


# -- bridge ---------------------------------------------------------------
def test_bridge_roundtrip_over_named_pipe(pipe_name: str, tmp_path: Path) -> None:
    from multiprocessing.connection import Client

    from smartsort.app.browser.bridge_server import recv_payload, send_payload

    token = ensure_token(tmp_path / "bridge.token")
    received: list[dict] = []

    def handler(message):
        received.append(message)
        return {"ok": True, "type": message.get("type")}

    server = BridgeServer(pipe_name, token, handler)
    server.start()
    try:
        connection = Client(pipe_name, family="AF_PIPE", authkey=token)
        send_payload(connection, {"type": "ping"})
        assert recv_payload(connection, timeout=5.0) == {"ok": True, "type": "ping"}
        send_payload(connection, {"type": "status"})
        assert recv_payload(connection, timeout=5.0)["type"] == "status"
        connection.close()
    finally:
        server.stop()
    assert [m["type"] for m in received] == ["ping", "status"]


def test_stop_leaves_no_bridge_thread_behind(pipe_name: str, tmp_path: Path) -> None:
    """A stopped server must not keep a thread parked in accept().

    accept() blocks until somebody connects, so closing the listener is not
    enough to end the loop. A surviving thread is still inside native code when
    the interpreter shuts down, which takes the whole process down with an
    access violation after a fully green run.
    """
    import threading

    token = ensure_token(tmp_path / "bridge.token")
    server = BridgeServer(pipe_name, token, lambda message: {"ok": True})
    server.start()
    before = {t for t in threading.enumerate() if t.name == "smartsort-bridge"}
    assert before, "the server should have started a thread"

    server.stop()

    alive = {
        t for t in threading.enumerate() if t.name == "smartsort-bridge" and t.is_alive()
    }
    assert not (before & alive), "stop() left the accept thread running"


def test_stop_is_idempotent(pipe_name: str, tmp_path: Path) -> None:
    token = ensure_token(tmp_path / "bridge.token")
    server = BridgeServer(pipe_name, token, lambda message: {"ok": True})
    server.start()
    server.stop()
    server.stop()
    assert server.is_running is False


def test_bridge_rejects_a_wrong_token(pipe_name: str, tmp_path: Path) -> None:
    from multiprocessing.connection import AuthenticationError, Client

    from smartsort.app.browser.bridge_server import recv_payload, send_payload

    token = ensure_token(tmp_path / "bridge.token")
    server = BridgeServer(pipe_name, token, lambda message: {"ok": True})
    server.start()
    try:
        with pytest.raises((AuthenticationError, OSError, EOFError)):
            connection = Client(pipe_name, family="AF_PIPE", authkey=b"x" * 64)
            send_payload(connection, {"type": "ping"})
            recv_payload(connection, timeout=5.0)
    finally:
        server.stop()


def test_bridge_never_unpickles_a_client_payload(pipe_name: str, tmp_path: Path) -> None:
    """A token holder must not be able to execute code through the pipe.

    ``multiprocessing.connection.recv`` unpickles, which would make any leaked
    token a code-execution primitive. The server reads raw bytes and parses
    JSON, so a pickle payload is rejected as malformed and the handler is never
    called.
    """
    import pickle
    from multiprocessing.connection import Client

    token = ensure_token(tmp_path / "bridge.token")
    calls: list[dict] = []
    server = BridgeServer(pipe_name, token, lambda message: calls.append(message) or {"ok": True})
    server.start()
    try:
        connection = Client(pipe_name, family="AF_PIPE", authkey=token)
        connection.send_bytes(pickle.dumps({"type": "ping"}))
        with pytest.raises((EOFError, OSError)):
            connection.recv_bytes(1024)
        connection.close()
    finally:
        server.stop()
    assert calls == [], "the handler must never see a pickled payload"


def test_bridge_refuses_connections_beyond_the_limit(pipe_name: str, tmp_path: Path) -> None:
    """An authenticated client that never closes must not spawn threads forever."""
    from multiprocessing.connection import Client

    from smartsort.app.browser.bridge_server import BridgeError, recv_payload, send_payload

    token = ensure_token(tmp_path / "bridge.token")
    server = BridgeServer(pipe_name, token, lambda message: {"ok": True}, max_connections=1)
    server.start()
    first = Client(pipe_name, family="AF_PIPE", authkey=token)
    try:
        send_payload(first, {"type": "ping"})
        assert recv_payload(first, timeout=5.0) == {"ok": True}
        assert server.connection_count == 1

        second = Client(pipe_name, family="AF_PIPE", authkey=token)
        answered = False
        try:
            send_payload(second, {"type": "ping"})
            recv_payload(second, timeout=3.0)
            answered = True
        except (BridgeError, EOFError, OSError):
            pass
        second.close()

        assert answered is False, "the server must not serve beyond max_connections"
        assert server.connection_count == 1
    finally:
        first.close()
        server.stop()


# -- native host subprocess ----------------------------------------------
def _spawn_host(data_dir: Path, pipe_name: str) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    # stderr goes to a file: a full pipe buffer would deadlock the child.
    stderr_log = open(data_dir / "host.stderr.log", "wb")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "smartsort.app.browser.native_host",
            "--data-dir",
            str(data_dir),
            "--pipe-name",
            pipe_name,
            "--log-file",
            str(data_dir / "host.log"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_log,
        cwd=str(PROJECT_ROOT),
        env=env,
    )


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        pass


def test_native_host_forwards_messages_to_the_app(pipe_name: str, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    token = ensure_token(data_dir / "bridge.token")

    def handler(message):
        if message.get("type") == "ping":
            return {"ok": True, "app": "SmartSort", "version": "1.0.0"}
        return {"ok": False, "error": "unexpected"}

    server = BridgeServer(pipe_name, token, handler)
    server.start()
    process = _spawn_host(data_dir, pipe_name)
    try:
        write_message(process.stdin, {"type": "ping", "browser": "chrome"})
        response = read_message(process.stdout)
        assert response is not None
        assert response["ok"] is True
        assert response["app"] == "SmartSort"

        process.stdin.close()
        process.wait(timeout=20)
    finally:
        server.stop()
        _terminate(process)


def test_native_host_reports_when_the_app_is_not_running(pipe_name: str, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    process = _spawn_host(data_dir, pipe_name)
    try:
        write_message(process.stdin, {"type": "ping", "browser": "chrome"})
        response = read_message(process.stdout)
        assert response is not None
        assert response["ok"] is False
        assert response["error"] == "app_not_running"
        process.stdin.close()
        process.wait(timeout=20)
    finally:
        _terminate(process)


def test_native_host_rejects_malformed_frames(pipe_name: str, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    process = _spawn_host(data_dir, pipe_name)
    try:
        # A frame that promises 50 bytes but delivers 7: the host must report a
        # protocol error rather than block or crash. EOF is required for the
        # host to detect the short read.
        process.stdin.write(struct.pack("<I", 50) + b"{broken")
        process.stdin.flush()
        process.stdin.close()
        response = read_message(process.stdout)
        assert response is not None
        assert response["ok"] is False
        assert response["error"] == "truncated_message"
        assert process.wait(timeout=20) == 1
    finally:
        _terminate(process)


def test_native_host_exits_when_stdin_closes(pipe_name: str, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    process = _spawn_host(data_dir, pipe_name)
    try:
        process.stdin.close()
        assert process.wait(timeout=20) == 0
    finally:
        _terminate(process)
