"""Background execution helpers.

File moves can block for seconds (large cross-volume copies), so every
filesystem operation runs on a dedicated worker thread and reports back through
Qt signals. The UI thread never touches the disk.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class _QueueThread(QThread):
    result = Signal(object)
    error = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: "queue.Queue[tuple[Callable[..., Any], tuple, dict] | None]" = queue.Queue()
        self._stop = threading.Event()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._queue.put((fn, args, kwargs))

    def run(self) -> None:  # noqa: D401
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            fn, args, kwargs = item
            try:
                value = fn(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("background task failed")
                self.error.emit(type(exc).__name__, str(exc))
            else:
                self.result.emit(value)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)


class TaskRunner(QObject):
    """Serialises background work and forwards results to the UI thread."""

    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = _QueueThread(self)
        self._thread.result.connect(self.succeeded)
        self._thread.error.connect(self.failed)
        self._thread.start()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._thread.submit(fn, *args, **kwargs)

    def shutdown(self, timeout_ms: int = 4000) -> None:
        if not self._thread.isRunning():
            return
        self._thread.stop()
        self._thread.wait(timeout_ms)
