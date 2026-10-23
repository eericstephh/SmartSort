"""Native messaging host entry point.

This module is executed as a separate process by Chrome/Edge. It speaks the
native messaging framing on stdin/stdout and forwards validated messages to the
running desktop application over an authenticated named pipe.

Rules this module follows:

* nothing except framed messages is ever written to stdout (logging goes to a
  file), because any stray byte corrupts the browser's protocol stream;
* the browser's message is never executed, evaluated or used to build a shell
  command;
* if the desktop app is not running the host replies with a structured error
  instead of crashing, so the extension can show a useful message.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

from ..config.defaults import APP_VERSION, PIPE_NAME
from .bridge_server import (
    BridgeError,
    connect,
    ensure_token,
    recv_payload,
    send_payload,
)
from .protocol import ProtocolError, error_response, read_message, write_message

logger = logging.getLogger("smartsort.native_host")


def _configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = []
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
                )
            )
        except OSError:
            handlers = []
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _binary_streams() -> tuple[Any, Any]:
    """Return binary stdin/stdout and make sure no text layer interferes."""
    stdin = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else sys.stdin
    stdout = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    if sys.platform == "win32":
        try:
            import msvcrt

            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        except (OSError, ValueError, AttributeError):  # pragma: no cover
            logger.debug("could not switch stdio to binary mode", exc_info=True)
    return stdin, stdout


class BridgeClient:
    """Lazily connected, auto-reconnecting client for the app bridge."""

    def __init__(self, pipe_name: str, token: bytes) -> None:
        self._pipe_name = pipe_name
        self._token = token
        self._connection: Any = None

    def _ensure(self) -> Any:
        if self._connection is not None:
            return self._connection
        self._connection = connect(self._pipe_name, self._token)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # pragma: no cover
                pass
            self._connection = None

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        for attempt in (1, 2):
            try:
                connection = self._ensure()
                # JSON framing, not pickle: the app never unpickles anything
                # that crossed the pipe.
                send_payload(connection, message)
                return recv_payload(connection, timeout=30.0)
            except (BridgeError, OSError, EOFError) as exc:
                self.close()
                if attempt == 2:
                    logger.warning("bridge request failed: %s", exc)
                    return error_response(
                        "app_not_running",
                        "SmartSort desktop application is not running",
                    )
        return error_response("app_not_running")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smartsort-host", add_help=False)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--pipe-name", default=PIPE_NAME)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--version", action="store_true")
    args, _unknown = parser.parse_known_args(argv)

    if args.version:
        # Diagnostics only: the browser never passes arguments, and we exit
        # before touching the protocol stream.
        print(f"smartsort-host {APP_VERSION}")
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else None
    log_file = Path(args.log_file) if args.log_file else None
    _configure_logging(log_file)

    token_path = (data_dir / "bridge.token") if data_dir else _default_token_path()
    if token_path is None:
        _safe_write(error_response("configuration_error", "cannot resolve the data directory"))
        return 2

    token = ensure_token(token_path)
    client = BridgeClient(args.pipe_name, token)
    stdin, stdout = _binary_streams()

    logger.info("native host started (version %s)", APP_VERSION)
    try:
        while True:
            try:
                message = read_message(stdin)
            except ProtocolError as exc:
                logger.warning("protocol error: %s", exc)
                _safe_write(error_response(exc.code, exc.detail))
                return 1
            if message is None:
                logger.info("browser closed the port")
                break
            response = client.request(message)
            _safe_write(response)
    except KeyboardInterrupt:  # pragma: no cover
        return 0
    finally:
        client.close()
        logger.info("native host exiting")
    return 0


def _default_token_path() -> Path | None:
    try:
        from ..config.paths import bridge_token_path

        return bridge_token_path()
    except Exception:  # pragma: no cover
        return None


def _safe_write(payload: dict[str, Any]) -> None:
    _stdin, stdout = _binary_streams()
    try:
        write_message(stdout, payload)
    except (OSError, ValueError):
        # The browser may have closed the pipe already; nothing else to do.
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
