from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from llm_loop.resources.contracts import (
    AdmissionOutcome,
    ExecutionClass,
    FactProvenance,
    FactSource,
    ObservedResourceState,
    ResourceKey,
    ResourceScopeKind,
    RuntimeType,
    ServicePriority,
)
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.local_runtime import LocalRuntimeConcurrencyAdapter
from llm_loop.resources.provider_calls import ProviderCallCoordinator


def _client(
    *,
    base_url: str = "http://127.0.0.1:8901/v1",
    provider: str = "cognilocal",
    model: str = "ornith-ai/Ornith-1.5-35B-A3B-MLX",
):
    return SimpleNamespace(base_url=base_url, provider=provider, model=model)


def _state(provider: str = "cognilocal", port: int = 8901, limit: int = 1):
    return ObservedResourceState(
        key=ResourceKey(provider, ResourceScopeKind.RUNTIME, f"mlx-loopback:{port}"),
        provenance=FactProvenance(
            source=FactSource.RUNTIME_PROBE,
            source_ref=f"local-listener:{port}:pid:35751",
            recorded_at=time.time(),
        ),
        runtime_type=RuntimeType.LOCAL,
        max_concurrency=limit,
    )


class _StaticAdapter:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def observe(self, client, *, provider_id: str, model_id: str):
        self.calls.append((client, provider_id, model_id))
        return self.state


def test_local_adapter_reads_exact_listener_process_flags_without_provider_name_inference():
    listener_calls = []
    command_calls = []

    def listeners(port: int):
        listener_calls.append(port)
        return (35751,)

    def command(pid: int):
        command_calls.append(pid)
        return (
            "/opt/homebrew/bin/python -m mlx_lm.server "
            "--model /srv/models/Ornith-1.5-35B-A3B-MLX "
            "--port 8901 --max-tokens 4096 --prompt-cache-size 8 "
            "--prompt-concurrency 1 --decode-concurrency 1"
        )

    adapter = LocalRuntimeConcurrencyAdapter(
        listener_pids=listeners,
        process_command=command,
        clock=lambda: 123.0,
    )
    state = adapter.observe(_client(), provider_id="cognilocal", model_id="ornith")
    assert state is not None
    assert state.runtime_type is RuntimeType.LOCAL
    assert state.max_concurrency == 1
    assert state.key == ResourceKey(
        "cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901"
    )
    assert state.provenance.source is FactSource.RUNTIME_PROBE
    assert state.provenance.recorded_at == 123.0
    assert state.provenance.source_ref == "local-listener:8901:pid:35751"
    assert listener_calls == [8901]
    assert command_calls == [35751]


def test_local_adapter_does_not_probe_cloud_or_guess_missing_or_ambiguous_capacity():
    probes = []
    adapter = LocalRuntimeConcurrencyAdapter(
        listener_pids=lambda port: probes.append(port) or (1,),
        process_command=lambda _pid: "python -m mlx_lm.server --port 8901",
    )
    assert (
        adapter.observe(
            _client(base_url="https://remote-deepseek.invalid/v1", provider="deepseek"),
            provider_id="deepseek",
            model_id="deepseek-v4-flash",
        )
        is None
    )
    assert probes == []

    assert adapter.observe(_client(), provider_id="cognilocal", model_id="ornith") is None

    ambiguous = LocalRuntimeConcurrencyAdapter(
        listener_pids=lambda _port: (10, 11),
        process_command=lambda _pid: "python -m mlx_lm.server --port 8901 --prompt-concurrency 1 --decode-concurrency 1",
    )
    assert ambiguous.observe(_client(), provider_id="cognilocal", model_id="ornith") is None


def test_local_adapter_uses_conservative_bound_from_explicit_prompt_and_decode_concurrency():
    adapter = LocalRuntimeConcurrencyAdapter(
        listener_pids=lambda _port: (9,),
        process_command=lambda _pid: (
            "python -m mlx_lm.server --port=8901 "
            "--prompt-concurrency=3 --decode-concurrency 2"
        ),
    )
    state = adapter.observe(_client(), provider_id="cognilocal", model_id="ornith")
    assert state is not None and state.max_concurrency == 2


def test_coordinator_serializes_same_local_runtime_and_releases_on_exception():
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    client = _client()
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def first():
        with pytest.raises(RuntimeError, match="boom"), coordinator.lease_for_client(
            client,
            execution_class=ExecutionClass.SUBAGENT,
            service_priority=ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
            owner_ref="subagent:one",
        ):
            entered.set()
            assert release.wait(2)
            raise RuntimeError("boom")

    def second():
        assert entered.wait(2)
        with coordinator.lease_for_client(
            client,
            execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND,
            owner_ref="task:two",
        ) as lease:
            assert lease is not None
            second_entered.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    assert entered.wait(2)
    time.sleep(0.03)
    assert not second_entered.is_set()
    release.set()
    t1.join(2)
    t2.join(2)
    assert not t1.is_alive() and not t2.is_alive()
    assert second_entered.is_set()
    assert governor.active_leases() == ()


def test_coordinator_preserves_remote_provider_behavior_until_rg3():
    governor = ResourceGovernor()
    adapter = _StaticAdapter(None)
    coordinator = ProviderCallCoordinator(governor, local_runtime=adapter)
    cloud = _client(
        base_url="https://remote-minimax.invalid/v1",
        provider="minimax",
        model="MiniMax-M3",
    )
    with coordinator.lease_for_client(
        cloud,
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        owner_ref="task:cloud",
    ) as lease:
        assert lease is None
    assert governor.active_leases() == ()


def test_coordinator_can_build_learning_request_on_same_runtime_key_as_task():
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    client = _client()
    task = coordinator.build_request_for_client(
        client,
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        owner_ref="task:s1",
    )
    learning = coordinator.build_request_for_client(
        client,
        execution_class=ExecutionClass.BACKGROUND_LEARNING,
        service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
        owner_ref="learning:j1",
    )
    assert task is not None and learning is not None
    assert task.resource_keys == learning.resource_keys
    assert task.provider_id == learning.provider_id == "cognilocal"


def test_coordinator_priority_waiting_orders_foreground_before_subagent():
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    client = _client()
    blocker = coordinator.build_request_for_client(
        client,
        execution_class=ExecutionClass.BACKGROUND_LEARNING,
        service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
        owner_ref="learning:blocker",
    )
    assert blocker is not None
    decision = governor.try_acquire(blocker)
    assert decision.outcome is AdmissionOutcome.ADMITTED and decision.lease is not None

    order = []

    def wait(execution_class, priority, owner):
        with coordinator.lease_for_client(
            client,
            execution_class=execution_class,
            service_priority=priority,
            owner_ref=owner,
        ):
            order.append(owner)
            time.sleep(0.01)

    sub = threading.Thread(
        target=wait,
        args=(ExecutionClass.SUBAGENT, ServicePriority.P1_ACTIVE_TASK_AUXILIARY, "subagent"),
    )
    fg = threading.Thread(
        target=wait,
        args=(ExecutionClass.FOREGROUND_TASK, ServicePriority.P0_FOREGROUND, "foreground"),
    )
    sub.start()
    deadline = time.time() + 1
    while time.time() < deadline and not governor.pending_request_ids():
        time.sleep(0.005)
    fg.start()
    deadline = time.time() + 1
    while time.time() < deadline and len(governor.pending_request_ids()) < 2:
        time.sleep(0.005)
    governor.release(decision.lease)
    sub.join(2)
    fg.join(2)
    assert order == ["foreground", "subagent"]


def test_learning_request_shares_qualified_local_runtime_key(tmp_path):
    from llm_loop.methods.learning_journal import LearningJournal
    from llm_loop.methods.learning_plane import LearningPlane

    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    client = _client(model="ornith")
    journal = LearningJournal(tmp_path / "learning.jsonl")
    job = journal.enqueue(
        "episode:s1:1:abc",
        session_id="s1",
        source_model="cognilocal/ornith",
    )
    assert job is not None
    plane = LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=SimpleNamespace(),
        model_resolver=lambda _ref: client,
        resource_governor=governor,
        resource_target_resolver=lambda _ref: ("cognilocal", "ornith"),
        provider_call_coordinator=coordinator,
        quiet_period_s=0.0,
    )
    learning = plane._resource_request(job)
    task = coordinator.build_request_for_client(
        client,
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        owner_ref="task:s1",
    )
    assert task is not None
    assert learning.resource_keys == task.resource_keys
    assert learning.resource_keys[0].scope_id == "mlx-loopback:8901"


def test_two_real_task_call_sites_serialize_on_one_qualified_local_runtime(build_test_engine):
    from llm_loop.llm.client import LLMResponse

    first_entered = threading.Event()
    release_first = threading.Event()

    def blocking_first(_calls):
        first_entered.set()
        assert release_first.wait(2)
        return LLMResponse(content="first", tool_calls=[], provider="fake")

    engine, fake = build_test_engine([blocking_first, {"content": "second"}])
    fake.provider = "cognilocal"
    fake.model = "ornith"
    fake.base_url = "http://127.0.0.1:8901/v1"
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    engine.provider_call_coordinator = coordinator
    s1 = engine.session.create()
    s2 = engine.session.create()
    results = {}

    def run(sid: str, text: str):
        results[sid] = engine.run(sid, text)

    t1 = threading.Thread(target=run, args=(s1, "one"))
    t2 = threading.Thread(target=run, args=(s2, "two"))
    t1.start()
    assert first_entered.wait(2)
    t2.start()
    deadline = time.time() + 1
    while time.time() < deadline and not governor.pending_request_ids():
        time.sleep(0.005)
    assert len(fake.calls) == 1
    assert governor.active_leases()[0].execution_class is ExecutionClass.FOREGROUND_TASK
    assert governor.in_flight(_state().key) == 1
    release_first.set()
    t1.join(3)
    t2.join(3)
    assert not t1.is_alive() and not t2.is_alive()
    assert len(fake.calls) == 2
    assert results[s1].final_answer == "first"
    assert results[s2].final_answer == "second"
    assert governor.active_leases() == ()


def test_subagent_real_call_site_holds_p1_provider_lease(tmp_path):
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.subagent.runner import SubAgentRunner
    from llm_loop.tools.registry import ToolRegistry

    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    seen = []

    class _SubLLM:
        provider = "cognilocal"
        model = "ornith"
        base_url = "http://127.0.0.1:8901/v1"

        def chat(self, _messages, tools):
            del tools
            leases = governor.active_leases()
            assert len(leases) == 1
            seen.append((leases[0].execution_class, leases[0].service_priority))
            return LLMResponse(content="child done", tool_calls=[], provider="fake")

    runner = SubAgentRunner(
        llm=_SubLLM(),  # type: ignore[arg-type]
        registry=ToolRegistry(),
        session_store=SessionStore(tmp_path / "sessions"),
        max_iterations=1,
        provider_call_coordinator=coordinator,
    )
    result = runner.run("child task")
    assert result.final_answer == "child done"
    assert seen == [(ExecutionClass.SUBAGENT, ServicePriority.P1_ACTIVE_TASK_AUXILIARY)]
    assert governor.active_leases() == ()


def test_foreground_stream_lease_lives_until_close_and_before_call_sees_lease():
    from llm_loop.resources.provider_calls import foreground_task_provider_stream

    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    owner = SimpleNamespace(provider_call_coordinator=coordinator)
    client = _client(model="ornith")
    before_seen = []

    def before_call():
        leases = governor.active_leases()
        assert len(leases) == 1
        before_seen.append(leases[0].execution_class)

    def stream_call(**_kwargs):
        yield SimpleNamespace(text="x")
        return "terminal-response"

    it = foreground_task_provider_stream(
        owner,
        client,
        stream_call,
        {},
        owner_ref="task:stream",
        before_call=before_call,
    )
    first = next(it)
    assert first.text == "x"
    assert before_seen == [ExecutionClass.FOREGROUND_TASK]
    assert len(governor.active_leases()) == 1
    it.close()
    assert governor.active_leases() == ()


def test_foreground_stream_preserves_stopiteration_return_value_and_releases():
    from llm_loop.resources.provider_calls import foreground_task_provider_stream

    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    owner = SimpleNamespace(provider_call_coordinator=coordinator)

    def stream_call(**_kwargs):
        if False:
            yield None
        return "complete-response"

    it = foreground_task_provider_stream(
        owner,
        _client(model="ornith"),
        stream_call,
        {},
        owner_ref="task:stream-terminal",
    )
    with pytest.raises(StopIteration) as stopped:
        next(it)
    assert stopped.value.value == "complete-response"
    assert governor.active_leases() == ()


def test_recovery_controller_real_retry_call_site_holds_p0_lease(build_test_engine):
    from llm_loop.llm.client import LLMResponse

    engine, _ = build_test_engine([])
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(governor, local_runtime=_StaticAdapter(_state()))
    engine.provider_call_coordinator = coordinator
    seen = []

    class _RetryClient:
        provider = "cognilocal"
        model = "ornith"
        base_url = "http://127.0.0.1:8901/v1"

        def chat(self, **_kwargs):
            leases = governor.active_leases()
            assert len(leases) == 1
            seen.append((leases[0].execution_class, leases[0].service_priority))
            return LLMResponse(content="recovered", tool_calls=[], provider="fake")

    resp, retry_exc = engine._recovery._retry_consume_stream(
        llm_client=_RetryClient(),
        messages=[{"role": "user", "content": "u1\n\nu2"}],
        tools_param=[],
        chat_model_arg="ornith",
        timeout_s=1.0,
        session_id="s-retry",
        round_no=2,
        attempt_index=1,
        transform={"wire_shape_changed": True},
    )
    assert retry_exc is None
    assert resp is not None and resp.content == "recovered"
    assert seen == [(ExecutionClass.FOREGROUND_TASK, ServicePriority.P0_FOREGROUND)]
    assert governor.active_leases() == ()
