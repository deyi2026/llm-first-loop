"""缺口②-1: learning 空闲门的 durable busy probe.

Busy 仅当 consumer 进程持锁且有 admitted/started 在飞任务；进程死亡的
started 残留由 post-crash reconcile 重跑，不构成 busy（否则重启学习进程
后第二次重启会永远等不到 idle）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.runtime.learning_idle import (
    consumer_active,
    consumer_lock_path,
    inflight_job_ids,
    journal_path,
    learning_busy_reason,
)

_LOCK_CHILD = """
import fcntl, sys
path = sys.argv[1]
fh = open(path, "a+", encoding="utf-8")
fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
print("held", flush=True)
sys.stdin.readline()
"""


class _HeldConsumerLock:
    """跨进程持锁（生产形态）：子进程持 consumer flock，退出即释放.

    同进程内两个 fd 的 flock 在 macOS 上不互斥（按进程判定），与生产的
    "控制 worker 探测、learning 进程持锁"形态不符，故必须真子进程。
    """

    def __init__(self, tmp_path: Path) -> None:
        import subprocess
        import sys

        path = consumer_lock_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _LOCK_CHILD, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self._proc.stdout is not None
        marker = self._proc.stdout.readline().strip()
        assert marker == "held", marker

    def release(self) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write("\n")
        self._proc.stdin.flush()
        assert self._proc.wait(timeout=10) == 0

    def __enter__(self) -> _HeldConsumerLock:
        return self

    def __exit__(self, *exc: object) -> None:
        if self._proc.poll() is None:
            self.release()


def _enqueue_started(tmp_path: Path) -> LearningJournal:
    journal = LearningJournal(journal_path(tmp_path))
    job = journal.enqueue("episode:s1:3:abc", session_id="s1")
    assert job is not None
    journal.mark_admitted(job.job_id)
    journal.mark_started(job.job_id)
    return journal


def test_consumer_active_reflects_flock_holder(tmp_path: Path) -> None:
    assert consumer_active(tmp_path) is False  # 无锁文件 → 未部署/已停止
    with _HeldConsumerLock(tmp_path):
        assert consumer_active(tmp_path) is True
    assert consumer_active(tmp_path) is False


def test_inflight_only_admitted_or_started(tmp_path: Path) -> None:
    journal = LearningJournal(journal_path(tmp_path))
    queued = journal.enqueue("episode:s1:3:abc", session_id="s1")
    assert queued is not None
    assert inflight_job_ids(tmp_path) == []  # queued 是积压不是在飞

    journal.mark_admitted(queued.job_id)
    assert inflight_job_ids(tmp_path) == [queued.job_id]

    journal.mark_started(queued.job_id)
    assert inflight_job_ids(tmp_path) == [queued.job_id]

    journal.mark_failed(queued.job_id, "done-for-test")
    assert inflight_job_ids(tmp_path) == []


def test_inflight_empty_when_journal_absent_or_corrupt(tmp_path: Path) -> None:
    assert inflight_job_ids(tmp_path) == []
    path = journal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert inflight_job_ids(tmp_path) == []


def test_busy_requires_lock_plus_inflight(tmp_path: Path) -> None:
    # 崩溃残留：锁已被释放（进程死亡），started 折叠仍在 → 不 busy
    _enqueue_started(tmp_path)
    assert learning_busy_reason(tmp_path) is None

    # 持锁但队列空转 → 不 busy
    with _HeldConsumerLock(tmp_path):
        journal = LearningJournal(journal_path(tmp_path))
        for job in journal.inflight_jobs():
            journal.mark_failed(job.job_id, "drained-for-test")
        assert learning_busy_reason(tmp_path) is None

    # 持锁 + 在飞 → busy（真在飞，重启须等排空或 fail-closed）
    journal2 = LearningJournal(journal_path(tmp_path))
    live = journal2.enqueue("episode:s2:1:def", session_id="s2")
    assert live is not None
    journal2.mark_admitted(live.job_id)
    with _HeldConsumerLock(tmp_path):
        reason = learning_busy_reason(tmp_path)
    assert reason is not None
    assert "learning busy" in reason
    assert "inflight=1" in reason


def test_target_busy_reason_includes_learning_for_learning_and_all(
    tmp_path: Path,
) -> None:
    from llm_loop.runtime import service_control as sc

    runtime_root = tmp_path
    sessions = tmp_path / "data" / "sessions"

    # learning 目标：无 consumer → idle（learning 无门回归被打破）
    assert sc._target_busy_reason(target="learning", runtime_root=str(runtime_root)) == ""

    journal = LearningJournal(journal_path(sessions))
    job = journal.enqueue("episode:s3:9:xyz", session_id="s3")
    assert job is not None
    journal.mark_admitted(job.job_id)
    journal.mark_started(job.job_id)

    with _HeldConsumerLock(sessions):
        reason = sc._target_busy_reason(target="learning", runtime_root=str(runtime_root))
        assert "learning busy" in reason
        all_reason = sc._target_busy_reason(target="all", runtime_root=str(runtime_root))
        assert "learning busy" in all_reason

    assert sc._target_busy_reason(target="web", runtime_root=str(runtime_root)) == ""
