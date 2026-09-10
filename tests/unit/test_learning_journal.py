"""LearningJournal 状态机、幂等入队与崩溃 reconcile 的机械验证。"""
from __future__ import annotations

import fcntl
import threading
from pathlib import Path
from types import SimpleNamespace

from llm_loop.methods.learning_journal import (
    LearningJournal,
    learning_job_id,
)
from llm_loop.methods.learning_plane import LearningPlane


def _mk(tmp_path: Path, *, max_attempts: int = 2, found: dict[str, str] | None = None) -> LearningJournal:
    found = found or {}
    return LearningJournal(
        tmp_path / "learning_journal.jsonl",
        max_attempts=max_attempts,
        candidate_lookup=lambda job_id: found.get(job_id),
    )


def test_job_id_is_deterministic_and_scoped():
    a = learning_job_id("episode:abc:1:aaaa")
    b = learning_job_id("episode:abc:1:aaaa")
    c = learning_job_id("episode:abc:2:bbbb")
    assert a == b and a != c and a.startswith("learn:")


def test_enqueue_creates_job_and_persists(tmp_path):
    journal = _mk(tmp_path)
    job = journal.enqueue(
        "episode:s1:3:xyz",
        session_id="s1",
        source_model="ollama/glm",
        trigger_facts={"rounds": 7, "tool_calls": 9},
    )
    assert job is not None and job.state == "queued"
    reloaded = LearningJournal(tmp_path / "learning_journal.jsonl")
    assert reloaded.job(job.job_id) is not None
    assert reloaded.job(job.job_id).source_episode_ref == "episode:s1:3:xyz"


def test_enqueue_idempotent_for_same_episode(tmp_path):
    journal = _mk(tmp_path)
    first = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    again = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    assert first.job_id == again.job_id
    lines = (tmp_path / "learning_journal.jsonl").read_text().splitlines()
    assert len([ln for ln in lines if '"queued"' in ln]) == 1  # 不追加重复 queued


def test_terminal_states_block_reenqueue(tmp_path):
    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    journal.mark_saved(job.job_id, "method:foo")
    assert journal.enqueue("episode:s1:3:xyz", session_id="s1") is None
    other = journal.enqueue("episode:s1:4:zzz", session_id="s1")
    journal.mark_none(other.job_id, "no_reusable_method")
    assert journal.enqueue("episode:s1:4:zzz", session_id="s1") is None


def test_failed_below_max_can_retry_then_blocks(tmp_path):
    journal = _mk(tmp_path, max_attempts=2)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    journal.mark_started(job.job_id)
    journal.mark_failed(job.job_id, "timeout")
    assert journal.runnable_jobs() != []
    journal.mark_started(job.job_id)
    journal.mark_failed(job.job_id, "timeout")
    assert journal.runnable_jobs() == []
    assert journal.enqueue("episode:s1:3:xyz", session_id="s1") is None


def test_attempt_counter_folds_across_reload(tmp_path):
    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    journal.mark_started(job.job_id)
    journal.mark_started(job.job_id)  # 崩溃重跑场景：两次 started
    reloaded = LearningJournal(
        tmp_path / "learning_journal.jsonl",
        max_attempts=2,
        candidate_lookup=lambda _: None,
    )
    assert reloaded.job(job.job_id).attempt == 2


def test_reconcile_started_with_existing_candidate_marks_saved(tmp_path):
    journal = _mk(tmp_path, found={})
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    journal.mark_started(job.job_id)
    # 崩溃后重启：lookup 发现该 job 已产出 candidate
    after = LearningJournal(
        tmp_path / "learning_journal.jsonl",
        max_attempts=2,
        candidate_lookup=lambda jid: "method:distilled-x" if jid == job.job_id else None,
    )
    changed = after.reconcile()
    assert f"{job.job_id}:saved(reconciled)" in changed
    assert after.job(job.job_id).state == "saved"
    assert after.job(job.job_id).candidate_ref == "method:distilled-x"
    assert after.enqueue("episode:s1:3:xyz", session_id="s1") is None  # 不重复学


def test_reconcile_without_candidate_requeues_or_fails(tmp_path):
    journal = _mk(tmp_path, max_attempts=2, found={})
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    journal.mark_started(job.job_id)
    changed = journal.reconcile()
    assert f"{job.job_id}:requeued" in changed
    assert journal.job(job.job_id).state == "queued"

    journal.mark_started(job.job_id)  # 第二次尝试又中断
    changed = LearningJournal(
        tmp_path / "learning_journal.jsonl", max_attempts=2, candidate_lookup=lambda _: None
    ).reconcile()
    assert f"{job.job_id}:failed(reconciled)" in changed


def test_load_skips_corrupt_lines(tmp_path):
    path = tmp_path / "learning_journal.jsonl"
    path.write_text(
        "{ not json\n"
        '{"event": "queued", "job_id": "learn:1", "source_episode_ref": "episode:a", "session_id": "s"}\n'
        "\n"
        '{"event": "orphan", "job_id": "learn:missing-queued"}\n',
        encoding="utf-8",
    )
    journal = LearningJournal(path)
    assert journal.job("learn:1") is not None
    assert journal.job("learn:missing-queued") is None


def test_none_reason_truncated(tmp_path):
    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1")
    journal.mark_none(job.job_id, "x" * 5000)
    assert len(journal.job(job.job_id).reason) == 300


def test_find_by_evidence_roundtrip(tmp_path):
    """find_by_evidence 反查 save_candidate 写入的 evidence_refs（journal reconcile 用）."""
    from llm_loop.methods.store import MethodStore

    store = MethodStore(tmp_path)
    assert store.find_by_evidence("learning:job-x") is None  # 空库未命中
    rec = store.save_candidate(
        name="Probe Candidate",
        description="probe",
        body="# Probe\n正文",
        source_model="probe-model",
        evidence_refs=["learning:job-x", "other:ref"],
    )
    assert store.find_by_evidence("learning:job-x") == rec.method_ref
    assert store.find_by_evidence("other:ref") == rec.method_ref
    assert store.find_by_evidence("learning:missing") is None
    assert store.find_by_evidence("") is None


def test_factory_assembles_learning_plane_only_when_enabled(tmp_path):
    """factory 装配：默认关闭零挂载；开启时 journal+plane 就绪且可停."""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    def _mk(enabled: bool) -> Settings:
        return Settings(
            llm_api_key="k",
            llm_base_url="https://x.invalid/v1",
            llm_model="m",
            data_dir=str(tmp_path / ("data-on" if enabled else "data-off")),
            extract_enabled=False,
            learning_plane_enabled=enabled,
        )

    engine_off = build_engine(_mk(False))
    assert engine_off.learning_plane is None
    assert getattr(engine_off, "learning_journal", None) is None  # 关闭=完全静默

    engine_on = build_engine(_mk(True))
    try:
        plane = engine_on.learning_plane
        assert plane is not None and plane._thread.is_alive()
        journal = engine_on.learning_journal
        assert journal is not None
        assert journal._path.parent.name == "learning"  # sessions/learning/journal.jsonl
        assert journal.runnable_jobs() == []  # journal 与文件系统协同（惰性建文件，无积压）
    finally:
        if engine_on.learning_plane is not None:
            engine_on.learning_plane.stop()
    assert engine_on.learning_plane._thread is None or not engine_on.learning_plane._thread.is_alive()


def _plane_for_admission(tmp_path: Path, engine, journal: LearningJournal) -> LearningPlane:
    return LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: (_ for _ in ()).throw(AssertionError("model call not expected")),
        sessions_dir=tmp_path / "sessions",
        poll_interval_s=1.0,
        quiet_period_s=0.0,
    )


def test_learning_plane_foreground_gate_uses_run_activity_not_tool_registry(tmp_path):
    """ToolRegistry being truthy is not foreground activity; runner/sync facts are."""
    engine = SimpleNamespace(
        registry=object(),  # production ToolRegistry is normally truthy
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    plane = _plane_for_admission(tmp_path, engine, _mk(tmp_path))
    assert plane.foreground_busy() is False

    engine.runner = SimpleNamespace(has_running=lambda: True)
    assert plane.foreground_busy() is True

    engine.runner = SimpleNamespace(has_running=lambda: False)
    engine._sync_active.add("foreground-session")
    assert plane.foreground_busy() is True


def test_learning_plane_requeues_when_foreground_arrives_after_admission(tmp_path):
    """Foreground appearing in the admission/start gap wins without a model call."""
    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1", source_model="provider/model")
    assert job is not None
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    plane = _plane_for_admission(tmp_path, engine, journal)
    activity = iter((False, True))
    plane.foreground_busy = lambda: next(activity)  # type: ignore[method-assign]

    assert plane._try_execute(job) is False
    after = journal.job(job.job_id)
    assert after is not None and after.state == "queued"
    assert after.attempt == 0


def test_learning_plane_detects_held_run_lock_in_nested_workspace(tmp_path):
    """Cross-process foreground leases live below workspace partitions, not sessions root."""
    sessions = tmp_path / "sessions"
    nested = sessions / "workspace-a"
    nested.mkdir(parents=True)
    lock_path = nested / "session-1.run.lock"
    lock_path.touch()
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    plane = LearningPlane(
        journal=_mk(tmp_path),
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: object(),
        sessions_dir=sessions,
        poll_interval_s=1.0,
        quiet_period_s=0.0,
    )

    with lock_path.open("r") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert plane.foreground_busy() is True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    assert plane.foreground_busy() is False
