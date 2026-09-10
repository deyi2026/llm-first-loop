"""Mechanical foreground activity sensing used by the RG-1 Learning bridge."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import Any


def _locks_dir_busy(sessions_dir: str | Path) -> bool:
    """True when any workspace partition holds an exclusive whole-run lease."""
    try:
        for lock_path in Path(sessions_dir).rglob("*.run.lock"):
            if not lock_path.exists():
                continue
            try:
                fd = lock_path.open("r")
            except OSError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                return True
            finally:
                fd.close()
    except Exception:  # noqa: BLE001 - admission uncertainty yields to foreground
        return True
    return False


class ForegroundActivityProbe:
    """Read only mechanical run activity facts; never inspect task semantics."""

    def __init__(self, engine: Any, sessions_dir: str | Path) -> None:
        self._engine = engine
        self._sessions_dir = Path(sessions_dir)

    def active(self) -> bool:
        runner = getattr(self._engine, "runner", None)
        try:
            has_running = getattr(runner, "has_running", None)
            if callable(has_running) and bool(has_running()):
                return True
        except Exception:  # noqa: BLE001
            return True

        guard = getattr(self._engine, "_sync_guard", None)
        active = getattr(self._engine, "_sync_active", None)
        if guard is not None and active is not None:
            try:
                with guard:
                    if bool(active):
                        return True
            except Exception:  # noqa: BLE001
                return True
        return _locks_dir_busy(self._sessions_dir)
