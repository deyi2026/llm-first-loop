"""缺口②-2: LearningPlane 进程内准入（learning 屏障退避 + 自动恢复）.

learning 重启被受理（learning 屏障存在）后：新任务不再准入（保持 queued，
不 busy-wait）；屏障释放后无需干预自动恢复执行。探测异常 fail-open——
learning 自身故障不得把退避变成永久停摆。
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.resources.foreground import ForegroundActivityProbe
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.runtime.admission_barrier import AdmissionBarrierRegistry


def _resource_target(model_ref: str) -> tuple[str, str]:
    if "/" in model_ref:
        return tuple(model_ref.split("/", 1))  # type: ignore[return-value]
    return "test-provider", model_ref or "test-model"


def _fake_barrier(op: str = "op-1"):
    return SimpleNamespace(service="learning", operation_id=op, reason="restart")


def _mk_plane(
    tmp_path: Path, journal: LearningJournal, extractor, gate
) -> LearningPlane:
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    probe = ForegroundActivityProbe(engine, tmp_path / "sessions")
    return LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: (_ for _ in ()).throw(
            AssertionError("model client not expected for memory jobs")
        ),
        resource_governor=ResourceGovernor(foreground_probe=probe.active),
        resource_target_resolver=_resource_target,
        memory_extractor=extractor,
        poll_interval_s=1.0,
        quiet_period_s=0.0,
        restart_admission_blocked=gate,
    )


class _FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def extract_session(self, session_id: str, *, trigger: str):
        self.calls.append((session_id, trigger))
        return SimpleNamespace(entries=[], skipped_duplicates=0)


def _enqueue_memory_job(journal: LearningJournal, sid: str = "s1"):
    job = journal.enqueue(
        f"memory-extract:{sid}:25",
        session_id=sid,
        source_model="provider/model",
        kind="memory_extract",
        trigger_facts={"kind": "memory_extract", "trigger": "interval", "message_count": 25},
    )
    assert job is not None
    return job


def test_barrier_blocks_admission_and_auto_resumes(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    extractor = _FakeExtractor()
    held: dict[str, object] = {"barrier": _fake_barrier()}
    plane = _mk_plane(tmp_path, journal, extractor, gate=lambda: held["barrier"])

    # 屏障存在：任务保持 queued，不执行、不占用（同 foreground 退避语义）
    assert plane._try_execute(job) is False
    assert extractor.calls == []
    after = journal.job(job.job_id)
    assert after is not None and after.state == "queued"

    # 屏障释放（释放单点撤销后）：无需任何干预，自动恢复执行
    held["barrier"] = None
    assert plane._try_execute(job) is True
    assert extractor.calls == [("s1", "interval")]
    done = journal.job(job.job_id)
    assert done is not None and done.state == "none"  # entries=0 → none


def test_barrier_probe_failure_fails_open(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    extractor = _FakeExtractor()

    def _boom():
        raise OSError("probe i/o error")

    plane = _mk_plane(tmp_path, journal, extractor, gate=_boom)
    # 探测异常按无屏障处理（fail-open）：任务正常执行
    assert plane._try_execute(job) is True
    assert extractor.calls == [("s1", "interval")]


def test_unwired_gate_keeps_legacy_behavior(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    extractor = _FakeExtractor()
    plane = _mk_plane(tmp_path, journal, extractor, gate=None)
    assert plane._try_execute(job) is True
    assert extractor.calls == [("s1", "interval")]


def test_real_barrier_file_holds_then_releases(tmp_path: Path) -> None:
    """工厂真实接线形态：registry establish/release 驱动同一 gate."""
    data_dir = tmp_path / "data"
    registry = AdmissionBarrierRegistry(data_dir)
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    extractor = _FakeExtractor()

    from llm_loop.runtime.admission_barrier import task_admission_barrier

    plane = _mk_plane(
        tmp_path,
        journal,
        extractor,
        gate=lambda: task_admission_barrier(data_dir, "learning_job"),
    )

    registry.establish("learning", operation_id="op-99")
    try:
        assert plane._try_execute(job) is False
        assert extractor.calls == []
    finally:
        assert registry.release("learning", operation_id="op-99") is True

    assert plane._try_execute(job) is True
    assert extractor.calls == [("s1", "interval")]
