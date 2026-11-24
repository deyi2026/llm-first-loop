"""Share only overlapping read-only computations; never retain a result cache."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from concurrent.futures import Future
from threading import Lock


class ConcurrentRead[T]:
    """Per-key in-flight sharing. The owner computes outside the registry lock."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[Hashable, Future[T]] = {}

    def read(self, key: Hashable, compute: Callable[[], T]) -> T:
        with self._lock:
            future = self._pending.get(key)
            owner = future is None
            if future is None:
                future = Future()
                self._pending[key] = future
        if not owner:
            return future.result()
        try:
            result = compute()
        except BaseException as exc:
            with self._lock:
                self._pending.pop(key, None)
                future.set_exception(exc)
            raise
        with self._lock:
            self._pending.pop(key, None)
            future.set_result(result)
        return result
