"""Learning-plane idle facts for restart gating (缺口②: learning 空闲门).

单一路径事实源，供 ``service_control._target_busy_reason`` 与测试共用：

- ``consumer.lock``（flock）= 专属 learning 进程持有者是否活着；
- journal fold 的 ``admitted``/``started`` = 是否有 learning 任务在飞。

空闲判定 = 无进程持锁，或持锁但无在飞任务。进程死亡时 journal 里残留的
``started`` 是崩溃现场而非在飞任务——post-crash reconcile 会重跑，不构成
busy；busy probe 在无锁时直接返回空闲，不给重启引入死等。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from pathlib import Path

from llm_loop.methods.learning_journal import LearningJournal

logger = logging.getLogger(__name__)

INFLIGHT_STATES = frozenset({"admitted", "started"})

# Only the read-only service status view uses this one-entry cache.
_display_lock = threading.Lock()
_display_cache: tuple[Path, tuple[int, ...], str | None] | None = None


def learning_dir(sessions_dir: str | Path) -> Path:
    return Path(sessions_dir) / "learning"


def consumer_lock_path(sessions_dir: str | Path) -> Path:
    """Canonical exclusive-consumer lock path (learning_runtime holds it)."""
    return learning_dir(sessions_dir) / "consumer.lock"


def journal_path(sessions_dir: str | Path) -> Path:
    return learning_dir(sessions_dir) / "journal.jsonl"


def consumer_active(sessions_dir: str | Path) -> bool:
    """True iff some process currently holds the exclusive consumer flock.

    纯探测：成功抢到锁立即释放，绝不长期持有；无锁文件/不可读 → False
    （fail-open：探测失败不得让 restart 永久等不到 idle）。
    """
    path = consumer_lock_path(sessions_dir)
    try:
        handle = path.open("a+", encoding="utf-8")
    except OSError:
        return False
    try:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            return False
        with contextlib.suppress(OSError):  # pragma: no cover - unlock of held probe lock
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        handle.close()


def inflight_job_ids(sessions_dir: str | Path) -> list[str]:
    """Job ids in admitted/started per journal fold; [] when journal absent.

    崩溃残留同样会折出 ``started``——调用方必须结合 ``consumer_active``
    判定（见 ``learning_busy_reason``）。
    """
    path = journal_path(sessions_dir)
    if not path.is_file():
        return []
    try:
        journal = LearningJournal(path)
        return [job.job_id for job in journal.inflight_jobs()]
    except Exception:  # noqa: BLE001 - probe must not crash restart gating
        logger.warning("learning journal unreadable for idle probe: %s", path, exc_info=True)
        return []


def learning_busy_reason(sessions_dir: str | Path) -> str | None:
    """Restart-gate view: None = idle, else a human-readable busy reason.

    Busy 仅当 consumer 进程持锁且有在飞任务（admitted/started）。持锁但
    队列空 = consumer 空转，重启无损失；无锁 = 无 consumer（未部署或已
    停止），started 残留由 reconcile 处理。
    """
    if not consumer_active(sessions_dir):
        return None
    ids = inflight_job_ids(sessions_dir)
    if not ids:
        return None
    shown = ",".join(ids[:3]) + ("…" if len(ids) > 3 else "")
    return f"learning busy: inflight={len(ids)} ({shown})"


def _journal_stamp(path: Path) -> tuple[int, ...] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def learning_busy_reason_for_display(sessions_dir: str | Path) -> str | None:
    """Read-only status projection; never use for restart admission.

    Recheck the live consumer lock on every call. Reuse only an unchanged
    journal's compact result; never cache a failed or unstable fold. A single
    lock coalesces concurrent status readers without retaining historical jobs.
    """
    global _display_cache
    if not consumer_active(sessions_dir):
        return None
    path = journal_path(sessions_dir).absolute()
    with _display_lock:
        stamp = _journal_stamp(path)
        if stamp is None:
            return learning_busy_reason(sessions_dir)
        if _display_cache is not None and _display_cache[:2] == (path, stamp):
            return _display_cache[2]
        try:
            ids = [job.job_id for job in LearningJournal(path).inflight_jobs()]
        except Exception:  # noqa: BLE001 - same fail-open display semantics as the live probe
            logger.warning("learning journal unreadable for display probe: %s", path, exc_info=True)
            return None
        reason = None
        if ids:
            shown = ",".join(ids[:3]) + ("…" if len(ids) > 3 else "")
            reason = f"learning busy: inflight={len(ids)} ({shown})"
        if _journal_stamp(path) == stamp:
            _display_cache = (path, stamp, reason)
        return reason
