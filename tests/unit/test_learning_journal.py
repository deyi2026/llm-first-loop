"""LearningJournal 状态机、幂等入队与崩溃 reconcile 的机械验证。"""
from __future__ import annotations

import fcntl
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.methods.learning_journal import (
    LearningJournal,
    learning_job_id,
)
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.resources.contracts import ResourceKey, ResourceScopeKind
from llm_loop.resources.foreground import ForegroundActivityProbe
from llm_loop.resources.governor import ResourceGovernor


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


def test_explicit_requeue_can_grant_one_repair_attempt_after_max_failure(tmp_path):
    """Operator repair is append-only and does not reopen automatic toxic retries."""
    journal = _mk(tmp_path, max_attempts=3)
    job = journal.enqueue("memory-extract:s1:37", session_id="s1", kind="memory_extract")
    assert job is not None
    for _ in range(3):
        journal.mark_started(job.job_id)
        journal.mark_failed(job.job_id, "worker_exception")

    exhausted = journal.job(job.job_id)
    assert exhausted is not None and exhausted.attempt == 3 and exhausted.state == "failed"
    assert journal.runnable_jobs() == []

    journal.mark_requeued(job.job_id, "operator_repair_verified")
    reopened = journal.job(job.job_id)
    assert reopened is not None and reopened.state == "queued" and reopened.attempt == 3
    assert [x.job_id for x in journal.runnable_jobs()] == [job.job_id]

    journal.mark_started(job.job_id)
    journal.mark_failed(job.job_id, "worker_exception")
    final = journal.job(job.job_id)
    assert final is not None and final.attempt == 4 and final.state == "failed"
    assert journal.runnable_jobs() == []


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
        body=(
            "## Trigger\nprobe roundtrip\n\n## Discriminator\nevidence refs reconcile\n\n"
            "## Short path\nfind_by_evidence\n\n## Stop conditions\nno match\n\n"
            "## Verification\nref found\n\n## Counterexamples\nstale refs"
        ),
        source_model="probe-model",
        evidence_refs=["learning:job-x", "other:ref"],
    )
    assert store.find_by_evidence("learning:job-x") == rec.method_ref
    assert store.find_by_evidence("other:ref") == rec.method_ref
    assert store.find_by_evidence("learning:missing") is None
    assert store.find_by_evidence("") is None


def test_factory_separates_learning_journal_producer_from_dedicated_consumer(tmp_path):
    """Task runtimes only enqueue; the dedicated Learning runtime owns Reflection consumption."""
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
    assert getattr(engine_off, "learning_journal", None) is None  # 关闭=无 Learning 队列/线程
    assert isinstance(engine_off.resource_governor, ResourceGovernor)
    assert engine_off.resource_governor.active_leases() == ()
    assert engine_off.provider_call_coordinator.governor is engine_off.resource_governor

    engine_on = build_engine(_mk(True))
    try:
        # Web/Feishu/CLI task runtimes may enqueue learning work but never consume it.
        assert engine_on.learning_plane is None
        journal = engine_on.learning_journal
        assert journal is not None
        assert journal._path.parent.name == "learning"  # sessions/learning/journal.jsonl
        assert journal.runnable_jobs() == []  # journal 与文件系统协同（惰性建文件，无积压）
    finally:
        engine_on.close()

    engine_learning = build_engine(_mk(True), runtime_role="learning")
    plane = engine_learning.learning_plane
    try:
        assert plane is not None and plane._thread.is_alive()
        assert plane._method_discovery is None  # semantic Method OFF = no hidden retrieval
        assert engine_learning.resource_governor is plane._resource_governor
        assert plane._provider_call_coordinator is engine_learning.provider_call_coordinator
        assert engine_learning.provider_call_coordinator.governor is engine_learning.resource_governor
        assert engine_learning.learning_journal is not None
    finally:
        engine_learning.close()
    assert plane._thread is None or not plane._thread.is_alive()

    method_on = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data-method-on"),
        extract_enabled=False,
        learning_plane_enabled=True,
        embedding_provider="hash",
        semantic_method_enabled=True,
    )
    engine_learning_method = build_engine(method_on, runtime_role="learning")
    method_plane = engine_learning_method.learning_plane
    try:
        assert method_plane is not None
        assert callable(method_plane._method_discovery)
    finally:
        engine_learning_method.close()


def test_learning_method_semantic_filters_unqualified_candidates(tmp_path) -> None:
    """Learning reuse recall admits only qualified/active Methods, not candidate noise."""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine
    from llm_loop.methods.store import MethodStore

    runtime_methods = tmp_path / "filtered-methods"
    seed_methods = tmp_path / "empty-seed"
    seed_methods.mkdir()
    store = MethodStore(runtime_methods, seed_dir=seed_methods)
    for i in range(35):
        store.save_candidate(
            name=f"candidate-noise-{i:02d}",
            description="service restart runtime provenance pid manifest import path",
            body=(
                "## Trigger\nnoise\n\n## Discriminator\nunqualified\n\n## Short path\nnone\n\n"
                "## Stop conditions\nalways\n\n## Verification\nnone\n\n## Counterexamples\nnone"
            ),
            source_model="test",
        )
    target = store.save_candidate(
        name="verified restart provenance",
        description="verify pid manifest git head and imported module path after restart",
        body=(
            "## Trigger\nafter service restart\n\n## Discriminator\nlong-lived replacement process\n\n"
            "## Short path\nverify pid manifest git head imported module path\n\n"
            "## Stop conditions\nidentity confirmed\n\n## Verification\nmanifest matches\n\n"
            "## Counterexamples\nstale config trust"
        ),
        source_model="test",
    )
    store.record_qualification(
        target.method_ref,
        task_ref="episode:qualification:1:independent",
        verdict="pass",
        mechanism="pass",
        task_benefit="pass",
        promotion="pass",
        evaluator="test",
    )
    store.update_status(target.method_ref, "qualified")

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "filtered-data"),
        methods_dir=str(runtime_methods),
        method_seed_dir=str(seed_methods),
        extract_enabled=False,
        learning_plane_enabled=True,
        embedding_provider="hash",
        semantic_method_enabled=True,
    )
    engine = build_engine(settings, runtime_role="learning")
    plane = engine.learning_plane
    try:
        assert plane is not None and callable(plane._method_discovery)
        rows, diag = plane._method_discovery(
            "service restart verify pid manifest imported module provenance", 6
        )
        assert [row["key"] for row in rows] == [target.method_ref]
        assert all(row["status"] in {"active", "qualified"} for row in rows)
        assert diag is not None and diag["eligible_method_count"] == 1
        assert diag["semantic_effective"] is True
    finally:
        engine.close()


def _resource_target(model_ref: str) -> tuple[str, str]:
    if "/" in model_ref:
        return tuple(model_ref.split("/", 1))  # type: ignore[return-value]
    return "test-provider", model_ref or "test-model"


def _plane_for_admission(tmp_path: Path, engine, journal: LearningJournal) -> LearningPlane:
    probe = ForegroundActivityProbe(engine, tmp_path / "sessions")
    governor = ResourceGovernor(foreground_probe=probe.active)
    return LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: (_ for _ in ()).throw(AssertionError("model call not expected")),
        resource_governor=governor,
        resource_target_resolver=_resource_target,
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
    probe = ForegroundActivityProbe(engine, sessions)
    governor = ResourceGovernor(foreground_probe=probe.active)
    plane = LearningPlane(
        journal=_mk(tmp_path),
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: object(),
        resource_governor=governor,
        resource_target_resolver=_resource_target,
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


def test_learning_plane_concurrency_lease_blocks_without_changing_job_state(tmp_path):
    """An occupied RG-1 Learning lane defers the job and leaves it queued."""
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
    request = plane._resource_request(job)
    blocker = plane._resource_governor.try_acquire(
        type(request)(
            request_id="learning:blocker",
            owner_ref="learning:blocker",
            execution_class=request.execution_class,
            service_priority=request.service_priority,
            provider_id=request.provider_id,
            model_id=request.model_id,
            resource_keys=request.resource_keys,
            submitted_at=request.submitted_at,
        )
    )
    assert blocker.lease is not None
    try:
        assert plane._try_execute(job) is False
        after = journal.job(job.job_id)
        assert after is not None and after.state == "queued" and after.attempt == 0
    finally:
        assert plane._resource_governor.release(blocker.lease) is True


def test_learning_plane_releases_resource_lease_when_reflection_raises(
    tmp_path, monkeypatch
):
    """Every exceptional ReflectionRun path releases the mechanical lease."""
    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1", source_model="provider/model")
    assert job is not None
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
        settings=SimpleNamespace(method_reflection_timeout_s=120.0),
    )
    plane = _plane_for_admission(tmp_path, engine, journal)
    plane._episode_store = SimpleNamespace(
        get=lambda *_args: {"messages": [{"role": "assistant", "content": "done"}]}
    )
    plane._model_resolver = lambda _model: object()

    def boom(**_kwargs):
        raise RuntimeError("reflection exploded")

    monkeypatch.setattr("llm_loop.methods.learning_plane.reflect_on_episode", boom)
    with pytest.raises(RuntimeError, match="reflection exploded"):
        plane._try_execute(job)
    assert plane._resource_governor.active_leases() == ()
    assert all(plane._resource_governor.in_flight(key) == 0 for key in plane._resource_request(job).resource_keys)


def test_learning_plane_passes_method_discovery_to_reflection(tmp_path, monkeypatch):
    """Dedicated consumer must pass the exact configured discovery callback to Reflection."""
    from llm_loop.methods.reflection import ReflectionOutcome

    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:4:method", session_id="s1", source_model="provider/model")
    assert job is not None
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
        settings=SimpleNamespace(method_reflection_timeout_s=120.0),
    )
    plane = _plane_for_admission(tmp_path, engine, journal)
    plane._episode_store = SimpleNamespace(
        get=lambda *_args: {"messages": [{"role": "assistant", "content": "done"}]}
    )
    plane._model_resolver = lambda _model: object()
    def sentinel(query, limit):
        return [], {"semantic_requested": True}

    plane._method_discovery = sentinel
    captured: dict[str, object] = {}

    def fake_reflect(**kwargs):
        captured.update(kwargs)
        return ReflectionOutcome(
            attempted=True,
            triggered=True,
            reason="no_new_method",
            method_discovery_diagnostics={
                "semantic_requested": True,
                "semantic_effective": False,
            },
        )

    monkeypatch.setattr("llm_loop.methods.learning_plane.reflect_on_episode", fake_reflect)
    assert plane._try_execute(job) is True
    assert captured["method_discovery"] is sentinel
    after = journal.job(job.job_id)
    assert after is not None and after.state == "none"


def test_learning_plane_unresolved_resource_target_cancels_without_attempt(tmp_path):
    """Unknown routing facts are not guessed: the job is terminalized (cancelled)
    without consuming an attempt, instead of yield-remaining queued forever at the
    head of runnable_jobs (queue-head starvation, EVO-20260928-e312b78f)."""
    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1", source_model="missing/model")
    assert job is not None
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    plane = _plane_for_admission(tmp_path, engine, journal)
    plane._resource_target_resolver = lambda _model: (_ for _ in ()).throw(ValueError("unknown"))
    assert plane._try_execute(job) is False
    after = journal.job(job.job_id)
    assert after is not None and after.state == "cancelled" and after.attempt == 0
    assert "model_unresolved:missing/model" in (after.reason or "")
    assert plane._resource_governor.active_leases() == ()


def test_learning_plane_authoritative_managed_unknown_does_not_fallback_to_rg1(tmp_path):
    from llm_loop.resources.provider_calls import ResourceAdmissionError

    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1", source_model="cognilocal/ornith")
    assert job is not None
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    probe = ForegroundActivityProbe(engine, tmp_path / "sessions")
    governor = ResourceGovernor(foreground_probe=probe.active)

    class Coordinator:
        def build_request_for_client(self, *_args, **_kwargs):
            raise ResourceAdmissionError("provider resource admission failed: required_fact_unknown")

    plane = LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: object(),
        resource_governor=governor,
        resource_target_resolver=_resource_target,
        provider_call_coordinator=Coordinator(),  # type: ignore[arg-type]
        poll_interval_s=1.0,
        quiet_period_s=0.0,
    )
    assert plane._try_execute(job) is False
    after = journal.job(job.job_id)
    assert after is not None and after.state == "queued" and after.attempt == 0
    fallback = ResourceKey(
        "cognilocal", ResourceScopeKind.RUNTIME, "rg1-learning-process:ornith"
    )
    assert governor.concurrency_limit(fallback) is None
    assert governor.active_leases() == ()


def test_learning_plane_revalidates_authority_before_started_and_requeues_on_generation_change(tmp_path):
    from llm_loop.resources.contracts import AdmissionRequest, ExecutionClass, ServicePriority
    from llm_loop.resources.provider_calls import ResourceAdmissionError

    journal = _mk(tmp_path)
    job = journal.enqueue("episode:s1:3:xyz", session_id="s1", source_model="cognilocal/ornith")
    assert job is not None
    engine = SimpleNamespace(
        registry=object(), runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(), _sync_active=set(),
        settings=SimpleNamespace(method_reflection_timeout_s=120.0),
    )
    probe = ForegroundActivityProbe(engine, tmp_path / "sessions")
    governor = ResourceGovernor(foreground_probe=probe.active)
    key = ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")

    class Coordinator:
        def build_request_for_client(self, *_args, **_kwargs):
            governor.set_concurrency_limit(key, 1, source_ref="lfrt:pid:1", generation="pid:1")
            return AdmissionRequest(
                request_id="learning:authority", owner_ref="learning:x",
                execution_class=ExecutionClass.BACKGROUND_LEARNING,
                service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
                provider_id="cognilocal", model_id="ornith", resource_keys=(key,),
                submitted_at=1.0,
            )
        def revalidate_request_for_client(self, *_args, **_kwargs):
            governor.invalidate_concurrency_limit(key)
            raise ResourceAdmissionError("provider resource admission failed: fact_conflict")

    plane = LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: {"messages": [{"role": "assistant", "content": "done"}]}),
        method_store=SimpleNamespace(), engine=engine,
        model_resolver=lambda _model: object(), resource_governor=governor,
        resource_target_resolver=_resource_target,
        provider_call_coordinator=Coordinator(),  # type: ignore[arg-type]
        poll_interval_s=1.0, quiet_period_s=0.0,
    )
    assert plane._try_execute(job) is False
    after = journal.job(job.job_id)
    assert after is not None and after.state == "queued" and after.attempt == 0
    assert governor.active_leases() == ()
