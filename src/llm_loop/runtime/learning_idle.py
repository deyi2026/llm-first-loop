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
from pathlib import Path

from llm_loop.methods.learning_journal import LearningJournal

logger = logging.getLogger(__name__)

INFLIGHT_STATES = frozenset({"admitted", "started"})


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
