"""Dedicated Learning Plane runtime.

Task-facing runtimes only append durable learning jobs.  This process is the sole
normal Reflection consumer and has no user ingress, chat session, scheduler, or
ordinary tool loop.  It deliberately shares the canonical data/Method stores so
completed ReflectionRuns remain visible to Web without joining the Task plane.
"""

from __future__ import annotations

import fcntl
import logging
import signal
import threading

from llm_loop.config import load_settings
from llm_loop.factory import build_engine
from llm_loop.runtime.learning_idle import consumer_lock_path

logger = logging.getLogger(__name__)


def main() -> int:
    settings = load_settings()
    lock_path = consumer_lock_path(settings.sessions_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("Learning consumer owner already active: %s", lock_path)
        lock_fh.close()
        return 2

    engine = build_engine(settings, runtime_role="learning")
    if not settings.learning_plane_enabled or engine.learning_plane is None:
        logger.warning("Learning runtime started with LEARNING_PLANE_ENABLED=0; exiting")
        engine.close()
        return 0

    stop = threading.Event()

    def _request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _request_stop)

    logger.info("Dedicated Learning runtime ready")
    try:
        while not stop.wait(1.0):
            plane = engine.learning_plane
            thread = getattr(plane, "_thread", None)
            if thread is not None and not thread.is_alive():
                logger.error("Learning consumer thread stopped unexpectedly")
                return 1
        return 0
    finally:
        engine.close()
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fh.close()


if __name__ == "__main__":
    raise SystemExit(main())
