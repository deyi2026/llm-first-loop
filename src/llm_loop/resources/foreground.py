"""Mechanical foreground activity sensing used by the RG-1 Learning bridge."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import Any


def active_run_locks(sessions_dir: str | Path) -> list[Path]:
    """Return whole-run lease files that are mechanically held right now.

    ``*.run.lock`` files are stable/tombstoned by design, so file existence is not
    activity. A non-blocking shared flock succeeds only when no foreground owner
    holds the exclusive whole-run lease. Inspection uncertainty is treated as busy.
    """
    busy: list[Path] = []
    try:
        lock_paths = list(Path(sessions_dir).rglob("*.run.lock"))
    except Exception:  # noqa: BLE001 - uncertainty must yield to foreground
        return [Path(sessions_dir) / "<scan-uncertain>.run.lock"]

    for lock_path in lock_paths:
        if not lock_path.exists():
            continue
        try:
            fd = lock_path.open("r")
        except OSError:
            busy.append(lock_path)
            continue
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                busy.append(lock_path)
        finally:
            fd.close()
    return busy


def _locks_dir_busy(sessions_dir: str | Path) -> bool:
    """True when any workspace partition holds an exclusive whole-run lease."""
    return bool(active_run_locks(sessions_dir))


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
