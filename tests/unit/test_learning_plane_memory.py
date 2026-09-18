"""P0-C: kind=memory_extract 任务由 LearningPlane 执行的契约测试.

覆盖：入队→执行→saved/none 终态；未装配 extractor 的 fail-closed；mid-call 前台
抢占（worker 被抛弃、任务 requeue、前台优先不被阻塞）。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.resources.foreground import ForegroundActivityProbe
from llm_loop.resources.governor import ResourceGovernor


def _resource_target(model_ref: str) -> tuple[str, str]:
    if "/" in model_ref:
        return tuple(model_ref.split("/", 1))  # type: ignore[return-value]
    return "test-provider", model_ref or "test-model"


def _engine_ns(busy_holder: dict[str, bool] | None = None):
    holder = busy_holder if busy_holder is not None else {"busy": False}

    return (
        SimpleNamespace(
            registry=object(),
            runner=SimpleNamespace(has_running=lambda: holder["busy"]),
            _sync_guard=threading.Lock(),
            _sync_active=set(),
        ),
        holder,
    )


def _mk_plane(tmp_path, journal: LearningJournal, memory_extractor, busy_holder=None):
    engine, holder = _engine_ns(busy_holder)
    probe = ForegroundActivityProbe(engine, tmp_path / "sessions")
    governor = ResourceGovernor(foreground_probe=probe.active)
    plane = LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: (_ for _ in ()).throw(
            AssertionError("model client not expected for memory jobs")
        ),
        resource_governor=governor,
        resource_target_resolver=_resource_target,
        memory_extractor=memory_extractor,
        poll_interval_s=1.0,
        quiet_period_s=0.0,
    )
    return plane, holder


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


class _FakeExtractor:
    def __init__(self, entries: int = 0, skipped: int = 0, gate: threading.Event | None = None):
        self.calls: list[tuple[str, str]] = []
        self.entries = entries
        self.skipped = skipped
        self.gate = gate

    def extract_session(self, session_id: str, *, trigger: str):
        self.calls.append((session_id, trigger))
        if self.gate is not None:
            while not self.gate.is_set():
                if self.gate.wait(0.02):
                    break
        return SimpleNamespace(
            entries=[object() for _ in range(self.entries)], skipped_duplicates=self.skipped
        )


def test_memory_extract_job_executes_and_marks_saved(tmp_path):
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    extractor = _FakeExtractor(entries=2, skipped=1)
    plane, _holder = _mk_plane(tmp_path, journal, extractor)

    assert plane._try_execute(job) is True
    assert extractor.calls == [("s1", "interval")]
    after = journal.job(job.job_id)
    assert after is not None and after.state == "saved"
    assert after.candidate_ref == "memory-extract:s1:entries=2"


def test_memory_extract_job_without_new_entries_marks_none(tmp_path):
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    extractor = _FakeExtractor(entries=0, skipped=3)
    plane, _holder = _mk_plane(tmp_path, journal, extractor)

    assert plane._try_execute(job) is True
    after = journal.job(job.job_id)
    assert after is not None and after.state == "none"
    assert "no_new_entries" in (after.reason or "")
    assert "skipped_duplicates=3" in (after.reason or "")


def test_memory_extract_job_without_wired_extractor_fails_closed(tmp_path):
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    plane, _holder = _mk_plane(tmp_path, journal, memory_extractor=None)

    assert plane._try_execute(job) is True
    after = journal.job(job.job_id)
    assert after is not None and after.state == "failed"
    assert after.reason == "memory_extractor_not_wired"


def test_memory_extract_job_preempted_by_foreground_mid_call(tmp_path):
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = _enqueue_memory_job(journal)
    started = threading.Event()
    gate = threading.Event()

    class _GatedExtractor(_FakeExtractor):
        def extract_session(self, session_id: str, *, trigger: str):
            self.calls.append((session_id, trigger))
            started.set()
            while not gate.is_set():
                if gate.wait(0.02):
                    break
            return SimpleNamespace(entries=[], skipped_duplicates=0)

    extractor = _GatedExtractor()
    plane, holder = _mk_plane(tmp_path, journal, extractor)

    done = threading.Event()
    outcome: list[bool] = []

    def _run():
        outcome.append(plane._try_execute(job))
        done.set()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    assert started.wait(5.0), "extract worker never started"
    holder["busy"] = True  # foreground arrives mid-call
    assert done.wait(5.0), "learning thread did not yield to foreground"
    assert outcome == [False]
    after = journal.job(job.job_id)
    assert after is not None and after.state == "queued"  # requeue = 回到 queued 态
    # 前台不被学习线程阻塞：_try_execute 已返回，被抛弃的 worker 自行收尾
    gate.set()
    worker.join(5.0)
    assert not worker.is_alive()
    assert extractor.calls == [("s1", "interval")]


def test_maybe_trigger_enqueue_then_plane_consumes(tmp_path):
    """端到端：MemoryExtractor.maybe_trigger 入队 → LearningPlane 消费执行."""
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.memory.extractor import MemoryExtractor
    from llm_loop.memory.store import MemoryStore
    from tests.unit.test_extractor import _FakeLLMExtract  # noqa: F401  复用既有 fake

    answer = (
        '[[memory]] {"type": "fact", "content": "部署契约以回执为准", '
        '"keywords": ["契约"]} [[/memory]]'
    )

    class _LLM:
        def chat(self, messages, tools):
            return LLMResponse(content=answer, tool_calls=[], provider="fake")

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    sid = store.create()
    for i in range(25):
        store.append(sid, Message(role="user", content=f"m{i}", source=MessageSource.USER))

    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    extractor = MemoryExtractor(
        llm_client=_LLM(),
        memory=MemoryStore(tmp_path / "memory"),
        session_store=store,
        interval_msgs=20,
        cooldown_s=0,
        audit_dir=tmp_path / "audit",
        learning_journal=journal,
    )
    extractor.model_ref = "provider/model"
    assert extractor.maybe_trigger(sid) is True
    plane, _holder = _mk_plane(tmp_path, journal, extractor)
    runnable = journal.runnable_jobs()
    assert len(runnable) == 1
    assert plane._try_execute(runnable[0]) is True
    after = journal.job(runnable[0].job_id)
    assert after is not None and after.state == "saved"
    assert after.candidate_ref.endswith("entries=1")
