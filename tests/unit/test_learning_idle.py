"""缺口②-1: learning 空闲门的 durable busy probe.

Busy 仅当 consumer 进程持锁且有 admitted/started 在飞任务；进程死亡的
started 残留由 post-crash reconcile 重跑，不构成 busy（否则重启学习进程
后第二次重启会永远等不到 idle）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.methods.learning_journal import LearningJob, LearningJournal
from llm_loop.runtime.learning_idle import (
    consumer_active,
    consumer_lock_path,
    inflight_job_ids,
    journal_path,
    learning_busy_reason,
    learning_busy_reason_for_display,
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


def test_display_probe_cache_is_exact_and_gate_stays_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = LearningJournal(journal_path(tmp_path))
    job = journal.enqueue("episode:display:1", session_id="display")
    assert job is not None
    journal.mark_started(job.job_id)
    original = LearningJournal.inflight_jobs
    calls = 0

    def counted(self: LearningJournal) -> list[LearningJob]:
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(LearningJournal, "inflight_jobs", counted)
    with _HeldConsumerLock(tmp_path):
        expected = learning_busy_reason(tmp_path)
        assert expected is not None
        assert learning_busy_reason_for_display(tmp_path) == expected
        assert learning_busy_reason_for_display(tmp_path) == expected
        assert calls == 2
        assert learning_busy_reason(tmp_path) == expected
        assert calls == 3  # admission never consumes the display cache
        journal.mark_failed(job.job_id, "done")
        assert learning_busy_reason_for_display(tmp_path) is None
        assert calls == 4
        assert learning_busy_reason_for_display(tmp_path) is None
        assert calls == 4
        # Replace the journal; the original fold semantics remain.
        replacement = journal_path(tmp_path).with_suffix(".replacement")
        replacement.write_text('{"event":"queued","job_id":"new"}\n{"event":"started","job_id":"new"}\n', encoding="utf-8")
        replacement.replace(journal_path(tmp_path))
        assert "new" in (learning_busy_reason_for_display(tmp_path) or "")
        assert calls == 5
    assert learning_busy_reason_for_display(tmp_path) is None  # live consumer lock is rechecked
    assert calls == 5


def test_display_probe_does_not_cache_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enqueue_started(tmp_path)
    original = LearningJournal.inflight_jobs
    calls = 0

    def flaky(self: LearningJournal) -> list[LearningJob]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("test read failure")
        return original(self)

    monkeypatch.setattr(LearningJournal, "inflight_jobs", flaky)
    with _HeldConsumerLock(tmp_path):
        assert learning_busy_reason_for_display(tmp_path) is None
        assert learning_busy_reason_for_display(tmp_path) is not None
        assert calls == 2


def test_service_display_coalesces_learning_and_all_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_loop.runtime import service_control as sc

    calls = 0

    def display_probe(path: Path) -> str:
        nonlocal calls
        calls += 1
        return "learning busy: test"

    monkeypatch.setattr(sc, "learning_busy_reason_for_display", display_probe)
    view = sc.compose_lifecycle_evidence_view(sc.ManagedServiceDeploymentStore(tmp_path / "data"))
    assert calls == 1
    assert view["idle_state"]["learning"]["state"] == "confirmed_busy"
    assert view["idle_state"]["all"]["state"] == "confirmed_busy"
    assert sc._target_idle_state(target="learning", runtime_root=str(tmp_path))[0] == "confirmed_idle"
    assert calls == 1  # physical gate does not use the display probe


def test_display_probe_coalesces_concurrent_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _enqueue_started(tmp_path)
    original = LearningJournal.inflight_jobs
    calls = 0

    def counted(self: LearningJournal) -> list[LearningJob]:
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(LearningJournal, "inflight_jobs", counted)
    with _HeldConsumerLock(tmp_path), ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(learning_busy_reason_for_display, [tmp_path] * 8))
    assert calls == 1
    assert results[0] is not None and all(x == results[0] for x in results)


def test_display_probe_does_not_cache_changed_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enqueue_started(tmp_path)
    original = LearningJournal.inflight_jobs
    calls = 0

    def changed(self: LearningJournal) -> list[LearningJob]:
        nonlocal calls
        calls += 1
        result = original(self)
        if calls == 1:
            self.mark_failed(result[0].job_id, "changed during display fold")
        return result

    monkeypatch.setattr(LearningJournal, "inflight_jobs", changed)
    with _HeldConsumerLock(tmp_path):
        assert learning_busy_reason_for_display(tmp_path) is not None
        assert learning_busy_reason_for_display(tmp_path) is None
        assert learning_busy_reason_for_display(tmp_path) is None
    assert calls == 2
