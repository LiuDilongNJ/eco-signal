from __future__ import annotations

import threading
from collections.abc import Callable

TASK_CANCELLED_MESSAGE = "Task cancelled by user"


class TaskCancelledError(Exception):
    """Raised when a background task reaches a safe cancellation point."""


class CancellationToken:
    """Thread-safe cancellation signal shared by async and synchronous work."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        if self._event.is_set():
            return
        self._event.set()
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            callback()

    def add_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)
        if self.is_cancelled:
            callback()

    def remove_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancelledError("Task cancellation requested")
