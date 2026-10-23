"""Authenticated named-pipe bridge between the native host and the app.

The desktop application listens on a Windows named pipe. The native messaging
host (spawned by Chrome/Edge) connects to it, so the browser never talks to a
network socket and the application never opens a listening TCP port.

Two decisions here are security-relevant:

* ``multiprocessing.connection`` provides the HMAC challenge/response handshake,
  so a process that does not know the shared token cannot send a message. But its
  ``send``/``recv`` helpers transport **pickle** payloads, and unpickling
  attacker-controlled data is remote code execution. This module therefore uses
  only ``send_bytes``/``recv_bytes`` with JSON on top, which keeps the handshake
  and drops the code-execution primitive.
* ``recv_bytes`` is called with a hard byte cap, so a hostile client cannot make
  the app allocate an unbounded buffer.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
from multiprocessing.connection import AuthenticationError, Client, Listener
from pathlib import Path
from typing import Any, Callable

from ..config.defaults import MAX_BRIDGE_BYTES

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32
_MIN_TOKEN_LENGTH = 32


class BridgeError(RuntimeError):
    pass


# -- token -----------------------------------------------------------------
def ensure_token(path: Path) -> bytes:
    """Load or create the shared bridge token."""
    try:
        if path.exists():
            existing = path.read_bytes().strip()
            if len(existing) >= _MIN_TOKEN_LENGTH:
                return existing
    except OSError:
        logger.warning("could not read bridge token, regenerating", exc_info=True)
    token = secrets.token_hex(TOKEN_BYTES).encode("ascii")
    try:
        return _write_token(path, token)
    except OSError:  # pragma: no cover - environmental
        logger.warning("could not persist bridge token to %s", path, exc_info=True)
        return token


def _write_token(path: Path, token: bytes) -> bytes:
    """Write the token, tighten its ACL, then move it into place.

    The ACL is applied to a temporary file and the result is read back before
    the rename. If tightening the permissions ever made the file unreadable the
    temporary copy is discarded, so a botched ACL can never lock the app out of
    its own token.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_bytes(token)
        tightened = _restrict_permissions(temp)
        if tightened and temp.read_bytes().strip() != token:
            raise OSError("token became unreadable after applying permissions")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - environmental
            pass

    # Another process may have created the token at the same instant; whatever
    # is on disk now is the value both sides must agree on.
    try:
        stored = path.read_bytes().strip()
    except OSError:  # pragma: no cover - environmental
        return token
    return stored if len(stored) >= _MIN_TOKEN_LENGTH else token


def _restrict_permissions(path: Path) -> bool:
    """Restrict the token to the current user. Returns True when applied.

    ``os.chmod`` only toggles the read-only attribute on Windows, so it is used
    on POSIX and ``icacls`` is used on Windows: inheritance is removed and the
    current account keeps full control. Failure is logged and treated as "not
    applied" - the file still inherits the user-only ACL of ``%LOCALAPPDATA%``.
    """
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
            return True
        except OSError:  # pragma: no cover - environmental
            return False

    account = os.environ.get("USERNAME")
    if not account:
        return False
    domain = os.environ.get("USERDOMAIN")
    principal = f"{domain}\\{account}" if domain else account
    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, no shell, no user input
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
            check=False,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environmental
        logger.debug("could not tighten the bridge token ACL", exc_info=True)
        return False
    if completed.returncode != 0:  # pragma: no cover - environmental
        logger.debug(
            "icacls returned %s: %s",
            completed.returncode,
            completed.stderr.decode("utf-8", "replace").strip(),
        )
        return False
    return True


# -- framing ---------------------------------------------------------------
def send_payload(connection: Any, payload: dict[str, Any]) -> None:
    """Send one JSON payload. Never pickles."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BRIDGE_BYTES:
        raise BridgeError(f"payload of {len(body)} bytes exceeds the bridge limit")
    connection.send_bytes(body)


def recv_payload(connection: Any, timeout: float | None = None) -> dict[str, Any]:
    """Receive one JSON payload, bounded by ``MAX_BRIDGE_BYTES``.

    Raises :class:`BridgeError` for anything malformed; ``EOFError`` and
    ``OSError`` are allowed through so callers can treat a closed pipe as an
    ordinary disconnect.
    """
    if timeout is not None and not connection.poll(timeout):
        raise BridgeError("timed out waiting for the bridge")
    body = connection.recv_bytes(MAX_BRIDGE_BYTES)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError("bridge payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise BridgeError("bridge payload must be a JSON object")
    return payload


def connect(pipe_name: str, token: bytes, timeout: float = 5.0) -> Any:
    """Connect to a running bridge. Raises :class:`BridgeError` on failure."""
    try:
        return Client(pipe_name, family="AF_PIPE", authkey=token)
    except (OSError, EOFError, AuthenticationError) as exc:
        raise BridgeError(f"cannot connect to the SmartSort bridge: {exc}") from exc


class BridgeServer:
    """Accepts authenticated connections and dispatches validated messages."""

    def __init__(
        self,
        pipe_name: str,
        authkey: bytes,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        max_connections: int = 8,
    ) -> None:
        self._pipe_name = pipe_name
        self._authkey = authkey
        self._handler = handler
        self._max_connections = max(1, max_connections)
        self._listener: Listener | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._clients: set[threading.Thread] = set()
        self._clients_lock = threading.Lock()
        self._connection_count = 0
        self.last_error: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            self._listener = Listener(self._pipe_name, family="AF_PIPE", authkey=self._authkey)
        except OSError as exc:
            self.last_error = str(exc)
            raise BridgeError(f"cannot listen on {self._pipe_name}: {exc}") from exc
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._accept_loop, name="smartsort-bridge", daemon=True
        )
        self._thread.start()
        logger.info("bridge listening on %s", self._pipe_name)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("listener close failed", exc_info=True)
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        with self._clients_lock:
            clients = list(self._clients)
        for client_thread in clients:
            client_thread.join(timeout / 2 if timeout else 0.5)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def connection_count(self) -> int:
        """Number of client connections currently being served."""
        with self._clients_lock:
            return self._connection_count

    # -- internals ---------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            listener = self._listener
            if listener is None:
                break
            try:
                connection = listener.accept()
            except AuthenticationError:
                logger.warning("rejected bridge connection with an invalid token")
                continue
            except (OSError, EOFError):
                if not self._stop.is_set():
                    logger.debug("bridge accept loop ended", exc_info=True)
                break
            except Exception:  # pragma: no cover - defensive
                logger.exception("unexpected bridge accept failure")
                break

            thread = threading.Thread(
                target=self._serve,
                args=(connection,),
                name="smartsort-bridge-client",
                daemon=True,
            )
            with self._clients_lock:
                over_limit = self._connection_count >= self._max_connections
                if not over_limit:
                    self._clients.add(thread)
                    self._connection_count += 1
            if over_limit:
                # Bounded concurrency: an authenticated client that opens
                # connections and never closes them must not spawn threads
                # without limit.
                logger.warning(
                    "refusing bridge connection: %d already open", self._max_connections
                )
                try:
                    connection.close()
                except Exception:  # pragma: no cover - defensive
                    pass
                continue
            thread.start()

    def _serve(self, connection: Any) -> None:
        try:
            with connection:
                while not self._stop.is_set():
                    try:
                        message = recv_payload(connection)
                    except (EOFError, OSError):
                        break
                    except BridgeError as exc:
                        logger.warning("dropping bridge connection: %s", exc)
                        break
                    try:
                        response = self._handler(message)
                    except Exception:
                        # The exception text stays in the local log. Sending it
                        # back would hand internal detail to the client.
                        logger.exception("bridge handler raised")
                        response = {"ok": False, "error": "internal_error"}
                    try:
                        send_payload(connection, response)
                    except (OSError, EOFError, BridgeError):
                        break
        finally:
            current = threading.current_thread()
            with self._clients_lock:
                self._clients.discard(current)
                self._connection_count = max(0, self._connection_count - 1)
