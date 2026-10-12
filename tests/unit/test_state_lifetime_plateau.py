from __future__ import annotations

import gc
import os
import subprocess
import threading
import tracemalloc
from types import SimpleNamespace

import llm_loop.core.session as session_mod
import llm_loop.llm.client as llm_client
import llm_loop.workspace.store as workspace_store_mod
from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.core.subagent_topology import SubAgentTopologyState
from llm_loop.event_log.store import EventStore
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.job_registry import JobRegistry
from llm_loop.tools.registry import ToolRegistry
from llm_loop.workspace.store import WorkspaceStore


class _FakeProc:
    def __init__(self, exit_code: int = 0) -> None:
        self.returncode = exit_code
        self.stdout = None
        self.stderr = None

    def wait(self) -> int:
        return self.returncode


def test_payload_trace_diagnostic_state_is_bounded(tmp_path, monkeypatch) -> None:
    """P4: optional deep-wire diagnostics may not retain every historical session/model."""
    monkeypatch.setenv("LLM_PAYLOAD_TRACE", "1")
    monkeypatch.setenv("LLM_PAYLOAD_TRACE_PATH", str(tmp_path / "payload_trace.jsonl"))
    monkeypatch.setattr(llm_client, "_PREFIX_TRACE_MAX_KEYS", 8)
    with llm_client._PREFIX_TRACE_LOCK:  # noqa: SLF001 - deterministic process-cache gate
        llm_client._PREFIX_TRACE_STATE.clear()  # noqa: SLF001
        llm_client._PREFIX_TRACE_SHAPE_STATE.clear()  # noqa: SLF001
    try:
        for i in range(64):
            messages = [{"role": "user", "content": f"message-{i}"}]
            llm_client._trace_payload_fingerprint(  # noqa: SLF001
                {"messages": messages, "tools": []},
                messages,
                session_id=f"session-{i:03d}",
                provider="test",
                model="model-a",
            )
        with llm_client._PREFIX_TRACE_LOCK:  # noqa: SLF001
            assert len(llm_client._PREFIX_TRACE_STATE) <= 8  # noqa: SLF001
            assert len(llm_client._PREFIX_TRACE_SHAPE_STATE) <= 8  # noqa: SLF001
            assert ("session-000", "model-a") not in llm_client._PREFIX_TRACE_STATE  # noqa: SLF001
            assert ("session-063", "model-a") in llm_client._PREFIX_TRACE_STATE  # noqa: SLF001
    finally:
        with llm_client._PREFIX_TRACE_LOCK:  # noqa: SLF001
            llm_client._PREFIX_TRACE_STATE.clear()  # noqa: SLF001
            llm_client._PREFIX_TRACE_SHAPE_STATE.clear()  # noqa: SLF001


def test_workspace_store_process_locks_release_with_store_lifetime(tmp_path) -> None:
    """P4: process lock coordination must not retain every historical data root."""
    gc.collect()
    baseline = len(workspace_store_mod._PROCESS_LOCKS)  # noqa: SLF001
    stores = []
    for i in range(64):
        stores.append(WorkspaceStore(tmp_path / f"data-{i:03d}"))
    assert len(workspace_store_mod._PROCESS_LOCKS) == baseline + 64  # noqa: SLF001

    stores.clear()
    gc.collect()
    assert len(workspace_store_mod._PROCESS_LOCKS) <= baseline  # noqa: SLF001


def test_run_state_idle_buckets_plateau_but_active_sessions_are_never_evicted() -> None:
    """P4: recent cross-turn facts may be cached, but all historical sessions may not be."""
    manager = RunStateManager(max_idle_buckets=8)

    for i in range(100):
        sid = f"session-{i:04d}"
        manager.activate(sid)
        token = current_session_id.set(sid)
        try:
            manager.bucket().state_round = i
        finally:
            current_session_id.reset(token)
        manager.release(sid)

    gc.collect()
    assert len(manager._buckets) <= 8  # noqa: SLF001
    assert manager.active_session_count() == 0

    active = [f"active-{i}" for i in range(12)]
    for sid in active:
        manager.activate(sid)
    assert set(active).issubset(manager._buckets)  # noqa: SLF001
    assert manager.active_session_count() == len(active)
    for sid in active:
        manager.release(sid)
    assert len(manager._buckets) <= 8  # noqa: SLF001


def test_job_registry_terminal_handles_are_bounded(tmp_path, monkeypatch) -> None:
    """P4: completed process/output handles are a bounded convenience cache, not durable SoT."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    registry = JobRegistry(event_store=None)
    registry._max_terminal_jobs = 8  # noqa: SLF001 - deterministic small plateau gate

    created: list[str] = []
    for i in range(64):
        job_id = registry.create(_FakeProc(), f"echo {i}")
        created.append(job_id)
        registry._watch_completion(job_id)  # noqa: SLF001 - deterministic terminal transition

    gc.collect()
    assert registry.active_count() == 0
    assert len(registry._jobs) <= 8  # noqa: SLF001
    assert registry.get(created[-1]) is not None


def test_session_identity_verification_cache_is_bounded_and_revalidates(tmp_path) -> None:
    """P4: verified identity is a disk-backed performance cache, not ownership SoT."""
    identity_root = tmp_path / "identity-root"
    store = SessionStore(identity_root / "workspace-a" / "sessions", identity_root=identity_root)
    store._identity_cache_max = 8  # noqa: SLF001 - deterministic small plateau gate
    ids = [f"session-{i:04d}" for i in range(64)]
    for sid in ids:
        store.claim_session_id(sid)

    assert len(store._identity_verified) <= 8  # noqa: SLF001
    store.claim_session_id(ids[0])
    assert len(store._identity_verified) <= 8  # noqa: SLF001


def test_session_meta_cache_is_bounded_even_when_listing_many_durable_sessions(
    tmp_path, monkeypatch
) -> None:
    """P4: durable Session files may scale; parsed metadata cache must plateau."""
    monkeypatch.setattr(session_mod, "_SESSION_META_CACHE_MAX", 8, raising=False)
    with session_mod._SESSION_META_CACHE_LOCK:  # noqa: SLF001
        session_mod._SESSION_META_CACHE.clear()  # noqa: SLF001
    store = SessionStore(tmp_path / "sessions")
    for _ in range(32):
        store.create()

    assert len(store.list_sessions()) == 32
    with session_mod._SESSION_META_CACHE_LOCK:  # noqa: SLF001
        assert len(session_mod._SESSION_META_CACHE) <= 8  # noqa: SLF001


def test_100_1k_10k_durable_sessions_grow_on_disk_while_ram_caches_plateau(
    tmp_path, monkeypatch
) -> None:
    """P4: 10K durable sessions may grow on disk without mirroring history in process RAM."""
    monkeypatch.setattr(session_mod, "_SESSION_META_CACHE_MAX", 32, raising=False)
    with session_mod._SESSION_META_CACHE_LOCK:  # noqa: SLF001
        session_mod._SESSION_META_CACHE.clear()  # noqa: SLF001

    store = SessionStore(tmp_path / "workspace-a" / "sessions", identity_root=tmp_path)
    store._identity_cache_max = 32  # noqa: SLF001 - qualification-sized recent window
    current_bytes: dict[int, int] = {}
    tracemalloc.start()
    try:
        for i in range(1, 10_001):
            store.create()
            if i not in {100, 1_000, 10_000}:
                continue

            # Exercise the real metadata listing path, then release the 10K-item result
            # before sampling process retention.  The returned list itself is caller-
            # owned result data, not a SessionStore cache.
            metas = store.list_sessions()
            assert len(metas) == i
            del metas
            gc.collect()

            assert len(store._identity_verified) <= 32  # noqa: SLF001
            with session_mod._SESSION_META_CACHE_LOCK:  # noqa: SLF001
                assert len(session_mod._SESSION_META_CACHE) <= 32  # noqa: SLF001
            with os.scandir(store.root) as entries:
                disk_sessions = sum(
                    1
                    for entry in entries
                    if entry.is_file()
                    and entry.name.endswith(".json")
                    and entry.name != store._SHARED_SESSION_FILE  # noqa: SLF001
                )
            assert disk_sessions == i
            current_bytes[i] = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()

    # By 1K both reconstructible caches are at capacity.  9K more durable identities
    # must not recreate the Python 3.13 pathlib high-cardinality retention regression.
    assert current_bytes[10_000] - current_bytes[1_000] < 256 * 1024


def test_engine_retires_per_session_runtime_hints_with_run_state_lru(build_test_engine) -> None:
    """P4: engine/cache diagnostic hints track the bounded recent-session window."""
    engine, _fake = build_test_engine([{"content": f"done-{i}"} for i in range(24)])
    engine._run_state_mgr._max_idle_buckets = 8  # noqa: SLF001

    for i in range(24):
        sid = engine.session.create()
        result = engine.run(sid, f"turn-{i}")
        assert result.final_answer == f"done-{i}"

    assert engine._run_state_mgr.active_session_count() == 0  # noqa: SLF001
    assert len(engine._run_state_mgr._buckets) <= 8  # noqa: SLF001
    assert len(engine._cache_last_model_by_session) <= 8  # noqa: SLF001
    assert len(getattr(engine, "_last_request_msg_count_by_session", {})) <= 8  # noqa: SLF001


def test_100_1k_10k_ephemeral_state_plateaus(tmp_path, monkeypatch, capsys) -> None:
    """P4 main gate: fixed active window must not retain all historical session/job state."""

    def _rss_kb() -> int | None:
        try:
            raw = subprocess.check_output(  # noqa: S603 - fixed local diagnostic command
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                text=True,
            ).strip()
            return int(raw) if raw else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    manager = RunStateManager(max_idle_buckets=32)
    events = EventStore(tmp_path / "events", enabled=True)
    events._rotate_checked_at_max_sessions = 32  # noqa: SLF001
    jobs = JobRegistry(event_store=None)
    jobs._max_terminal_jobs = 32  # noqa: SLF001
    monkeypatch.setattr(jobs, "_notify_completion", lambda _job_id: None)
    identities = SessionStore(tmp_path / "sessions")
    identities._identity_cache_max = 32  # noqa: SLF001
    subagents = SubAgentRunner(  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        registry=ToolRegistry(),
        session_store=SessionStore(tmp_path / "subagent-sessions"),
    )
    subagents._max_handles = 32  # noqa: SLF001

    baseline_threads = threading.active_count()
    checkpoints: dict[int, dict[str, int | None]] = {}
    tracemalloc.start()
    try:
        for i in range(1, 10_001):
            sid = f"plateau-{i:05d}"
            manager.activate(sid)
            manager.release(sid)

            # Read-cache and its single-flight lock table see 10K distinct durable ids.
            assert events.read_cached(sid) == []
            events._note_rotate_checked(sid, float(i))  # noqa: SLF001

            job_id = jobs.create(_FakeProc(), f"echo {i}")
            jobs._watch_completion(job_id)  # noqa: SLF001 - deterministic terminal transition

            # The real revalidation behavior has its own disk-backed test above; here we
            # stress only the process-local performance cache at 10K cardinality.
            identities._remember_identity_verified(sid)  # noqa: SLF001
            subagents._cache_durable_topology(  # noqa: SLF001
                SubAgentTopologyState(
                    child_id=f"subagent_{i:012d}",
                    parent_id="parent-plateau",
                    generation=f"g-{i}",
                    terminal=True,
                    outcome="completed",
                    last_seq=i,
                )
            )

            if i in {100, 1_000, 10_000}:
                gc.collect()
                current_bytes, peak_bytes = tracemalloc.get_traced_memory()
                checkpoints[i] = {
                    "run_buckets": len(manager._buckets),  # noqa: SLF001
                    "event_cache": len(events._read_cache),  # noqa: SLF001
                    "event_locks": len(events._read_cache_build_locks),  # noqa: SLF001
                    "rotate_cache": len(events._rotate_checked_at),  # noqa: SLF001
                    "terminal_jobs": len(jobs._jobs),  # noqa: SLF001
                    "identity_cache": len(identities._identity_verified),  # noqa: SLF001
                    "topology_cache": len(subagents._durable_topology),  # noqa: SLF001
                    "threads": threading.active_count(),
                    "tracemalloc_current": current_bytes,
                    "tracemalloc_peak": peak_bytes,
                    "rss_kb": _rss_kb(),
                }

                assert manager.active_session_count() == 0
                assert len(manager._buckets) <= 32  # noqa: SLF001
                assert len(events._read_cache) <= events._read_cache_max_sessions  # noqa: SLF001
                assert len(events._read_cache_build_locks) <= events._read_cache_max_sessions  # noqa: SLF001
                assert len(events._rotate_checked_at) <= 32  # noqa: SLF001
                assert jobs.active_count() == 0
                assert len(jobs._jobs) <= 32  # noqa: SLF001
                assert len(identities._identity_verified) <= 32  # noqa: SLF001
                assert len(subagents._durable_topology) <= 32  # noqa: SLF001
                assert threading.active_count() <= baseline_threads + 1
    finally:
        tracemalloc.stop()

    # Once all mechanical caches have hit capacity by 1K, 9K more identities must not
    # produce material traced-memory growth.  RSS is recorded for diagnosis only because
    # allocator high-water behavior is platform dependent.
    assert int(checkpoints[10_000]["tracemalloc_current"] or 0) - int(
        checkpoints[1_000]["tracemalloc_current"] or 0
    ) < 256 * 1024
    print({"p4_plateau": checkpoints})
    captured = capsys.readouterr().out
    assert "p4_plateau" in captured
    with capsys.disabled():
        print(captured.strip())
