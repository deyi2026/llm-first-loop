from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from llm_loop.resources.contracts import (
    ExecutionClass,
    ResourceKey,
    ResourceScopeKind,
    ServicePriority,
)
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.lfrt_runtime import (
    LFRTAdmissionRuntimeAdapter,
    LocalRuntimeTargetState,
)
from llm_loop.resources.local_runtime import LocalRuntimeConcurrencyAdapter
from llm_loop.resources.provider_calls import ProviderCallCoordinator, ResourceAdmissionError


def _client(base_url: str = "http://127.0.0.1:8901/v1"):
    return SimpleNamespace(base_url=base_url, provider="cognilocal", model="ornith")


def _payload(*, state="observed", managed=True, managed_port=8901, pid=123, prompt=1, decode=1):
    row = {
        "ok": True,
        "contract": "runtime-observation/v1",
        "state": state,
        "managed": managed,
    }
    if managed_port is not None:
        row["managed_port"] = managed_port
    if state == "observed":
        row["runtime"] = {
            "type": "mlx_lm.server",
            "pid": pid,
            "port": managed_port,
            "model": "Ornith-1.5-35B-A3B-MLX",
            "prompt_concurrency": prompt,
            "decode_concurrency": decode,
        }
    elif state == "unknown":
        row["reason"] = "listener_unknown"
    return row


def _runner(payload, calls):
    def run(argv, timeout_s):
        calls.append((argv, timeout_s))
        return 0, json.dumps(payload), ""
    return run


def test_lfrt_authority_classifies_remote_without_invoking_lfrt():
    calls = []
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(_payload(), calls))
    target = adapter.observe_target(
        _client("https://api.deepseek.com/v1"), provider_id="deepseek", model_id="m"
    )
    assert target.state is LocalRuntimeTargetState.NOT_APPLICABLE
    assert calls == []


def test_lfrt_authority_observed_projects_current_capacity_and_generation():
    calls = []
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(_payload(pid=123, prompt=3, decode=2), calls), clock=lambda: 50.0)
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.OBSERVED
    assert target.resource is not None
    assert target.resource.max_concurrency == 2
    assert target.resource.key == ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")
    assert target.generation == "pid:123"
    assert target.resource.provenance.source_ref == "lfrt-runtime-observation:8901:pid:123"
    assert calls == [(('/opt/lfrt', 'runtime-observation', '--json'), 2.0)]


def test_lfrt_authority_same_managed_port_unknown_is_managed_unknown():
    calls = []
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(_payload(state="unknown"), calls))
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.key == ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")
    assert target.reason == "listener_unknown"


def test_lfrt_authority_other_managed_port_is_not_applicable():
    calls = []
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(_payload(state="unknown", managed_port=8902), calls))
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("result", "expected_reason"),
    [
        ((1, "", "probe failed"), "observation_failed"),
        ((0, "", ""), "observation_failed"),
        ((0, "not-json", ""), "invalid_json"),
        ((0, json.dumps([]), ""), "invalid_contract"),
    ],
)
def test_lfrt_authority_probe_failures_stay_managed_unknown(result, expected_reason):
    def run(_argv, _timeout_s):
        return result

    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=run)
    target = adapter.observe_target(
        _client(), provider_id="cognilocal", model_id="ornith"
    )
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.key == ResourceKey(
        "cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901"
    )
    assert target.reason == expected_reason


def test_lfrt_authority_runner_exception_stays_managed_unknown():
    def run(_argv, _timeout_s):
        raise TimeoutError("probe timeout")

    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=run)
    target = adapter.observe_target(
        _client(), provider_id="cognilocal", model_id="ornith"
    )
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.reason == "observation_failed"


def test_lfrt_authority_stopped_invalidates_stale_limit_and_fails_closed():
    key = ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")
    governor = ResourceGovernor()
    governor.set_concurrency_limit(key, 4, source_ref="old", generation="pid:7")
    authority = LFRTAdmissionRuntimeAdapter(
        "/opt/lfrt", runner=_runner(_payload(state="stopped"), [])
    )
    coordinator = ProviderCallCoordinator(
        governor,
        local_runtime=SimpleNamespace(observe=lambda *_a, **_k: None),
        admission_authority="lfrt",
        lfrt_runtime=authority,
    )
    with pytest.raises(ResourceAdmissionError, match="required_fact_unknown"):
        coordinator.build_request_for_client(
            _client(),
            execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND,
            owner_ref="task:stopped",
        )
    assert governor.concurrency_limit(key) is None
    assert governor.concurrency_limit_generation(key) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True, "contract": "runtime-observation/v2", "state": "observed", "managed": True, "managed_port": 8901},
        {"ok": False, "contract": "runtime-observation/v1", "state": "unknown", "managed": True, "managed_port": 8901},
        {"ok": True, "contract": "runtime-observation/v1", "state": "observed", "managed": True, "managed_port": 8901, "runtime": {"type": "other.server", "pid": 1, "port": 8901, "model": "x", "prompt_concurrency": 1, "decode_concurrency": 1}},
    ],
)
def test_lfrt_authority_incompatible_or_invalid_contract_fails_managed_unknown_for_loopback(payload):
    calls = []
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(payload, calls))
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN


def test_lfrt_managed_unknown_invalidates_stale_limit_and_fails_before_transport():
    key = ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")
    governor = ResourceGovernor()
    rows = [_payload(pid=123), _payload(state="unknown")]
    calls = []

    def run(argv, timeout_s):
        calls.append((argv, timeout_s))
        return 0, json.dumps(rows.pop(0)), ""

    authority = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=run)
    coordinator = ProviderCallCoordinator(
        governor,
        local_runtime=LocalRuntimeConcurrencyAdapter(listener_pids=lambda _p: (), process_command=lambda _p: ""),
        admission_authority="lfrt",
        lfrt_runtime=authority,
    )
    first = coordinator.build_request_for_client(
        _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:first",
    )
    assert first is not None
    assert governor.concurrency_limit(key) == 1
    assert governor.concurrency_limit_generation(key) == "pid:123"

    with pytest.raises(ResourceAdmissionError, match="required_fact_unknown"):
        coordinator.build_request_for_client(
            _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:second",
        )
    assert governor.concurrency_limit(key) is None
    assert governor.concurrency_limit_generation(key) is None


def test_lfrt_managed_unknown_never_enters_transport():
    calls = []
    authority = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(_payload(state="unknown"), calls))
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(), local_runtime=SimpleNamespace(observe=lambda *_a, **_k: None),
        admission_authority="lfrt", lfrt_runtime=authority,
    )
    entered = []
    with (
        pytest.raises(ResourceAdmissionError, match="required_fact_unknown"),
        coordinator.lease_for_client(
            _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:x",
        ),
    ):
        entered.append(True)
    assert entered == []


def test_default_legacy_authority_preserves_existing_remote_no_lease_behavior():
    class Legacy:
        def __init__(self):
            self.calls = 0

        def observe(self, *_a, **_k):
            self.calls += 1
            return None
    legacy = Legacy()
    coordinator = ProviderCallCoordinator(ResourceGovernor(), local_runtime=legacy)
    with coordinator.lease_for_client(
        _client("https://api.deepseek.com/v1"), execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:remote",
    ) as lease:
        assert lease is None
    assert legacy.calls == 1


def _legacy_state(*, pid: int = 123, limit: int = 1, port: int = 8901):
    from llm_loop.resources.contracts import (
        FactProvenance,
        FactSource,
        ObservedResourceState,
        RuntimeType,
    )
    return ObservedResourceState(
        key=ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, f"mlx-loopback:{port}"),
        provenance=FactProvenance(
            source=FactSource.RUNTIME_PROBE,
            source_ref=f"local-listener:{port}:pid:{pid}",
            recorded_at=1.0,
        ),
        runtime_type=RuntimeType.LOCAL,
        max_concurrency=limit,
    )


@pytest.mark.parametrize(
    "legacy",
    [
        _legacy_state(pid=999, limit=1),
        _legacy_state(pid=123, limit=2),
        _legacy_state(pid=123, limit=1, port=8902),
    ],
)
def test_lfrt_authority_legacy_shadow_mismatch_vetoes_without_fallback(legacy):
    class Legacy:
        def observe(self, *_a, **_k):
            return legacy

    authority = LFRTAdmissionRuntimeAdapter(
        "/opt/lfrt", runner=_runner(_payload(pid=123, prompt=1, decode=1), [])
    )
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(
        governor,
        local_runtime=Legacy(),
        admission_authority="lfrt",
        lfrt_runtime=authority,
    )
    key = ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")
    governor.set_concurrency_limit(key, 7, source_ref="stale", generation="pid:88")
    with pytest.raises(ResourceAdmissionError, match="fact_conflict"):
        coordinator.build_request_for_client(
            _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:conflict",
        )
    assert governor.concurrency_limit(key) is None


def test_lfrt_authority_does_not_require_legacy_as_positive_fallback():
    class Legacy:
        def observe(self, *_a, **_k):
            return None

    authority = LFRTAdmissionRuntimeAdapter(
        "/opt/lfrt", runner=_runner(_payload(pid=123, prompt=1, decode=1), [])
    )
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(
        governor,
        local_runtime=Legacy(),
        admission_authority="lfrt",
        lfrt_runtime=authority,
    )
    request = coordinator.build_request_for_client(
        _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:lfrt-only",
    )
    assert request is not None
    assert governor.concurrency_limit(request.resource_keys[0]) == 1


@pytest.mark.parametrize("legacy_mode", ["none", "exception"])
def test_lfrt_authority_shadow_unavailable_does_not_block_positive_lfrt(legacy_mode):
    class Legacy:
        def observe(self, *_a, **_k):
            if legacy_mode == "exception":
                raise RuntimeError("shadow unavailable")
            return None

    authority = LFRTAdmissionRuntimeAdapter(
        "/opt/lfrt", runner=_runner(_payload(pid=123, prompt=2, decode=1), [])
    )
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(
        governor,
        local_runtime=Legacy(),
        admission_authority="lfrt",
        lfrt_runtime=authority,
    )
    request = coordinator.build_request_for_client(
        _client(),
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        owner_ref=f"task:{legacy_mode}",
    )
    assert request is not None
    assert governor.concurrency_limit(request.resource_keys[0]) == 1


def test_lfrt_revalidation_rejects_generation_change_without_renewing_old_lease_fact():
    rows = [_payload(pid=123), _payload(pid=124)]
    def run(_argv, _timeout):
        return 0, json.dumps(rows.pop(0)), ""
    class Legacy:
        def __init__(self): self.pid = 123
        def observe(self, *_a, **_k): return _legacy_state(pid=self.pid)
    legacy = Legacy()
    governor = ResourceGovernor()
    coordinator = ProviderCallCoordinator(
        governor, local_runtime=legacy, admission_authority="lfrt",
        lfrt_runtime=LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=run),
    )
    request = coordinator.build_request_for_client(
        _client(), execution_class=ExecutionClass.BACKGROUND_LEARNING,
        service_priority=ServicePriority.P3_BACKGROUND_LEARNING, owner_ref="learning:x",
    )
    assert request is not None
    key = request.resource_keys[0]
    assert governor.concurrency_limit_generation(key) == "pid:123"
    legacy.pid = 124
    with pytest.raises(ResourceAdmissionError, match="fact_conflict"):
        coordinator.revalidate_request_for_client(
            _client(), request, expected_generation="pid:123"
        )
    assert governor.concurrency_limit(key) is None
    assert governor.concurrency_limit_generation(key) is None


def test_lfrt_revalidation_same_generation_is_read_only_for_installed_fact():
    rows = [_payload(pid=123), _payload(pid=123)]
    def run(_argv, _timeout):
        return 0, json.dumps(rows.pop(0)), ""
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(), local_runtime=SimpleNamespace(observe=lambda *_a, **_k: _legacy_state(pid=123)),
        admission_authority="lfrt",
        lfrt_runtime=LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=run),
    )
    request = coordinator.build_request_for_client(
        _client(), execution_class=ExecutionClass.BACKGROUND_LEARNING,
        service_priority=ServicePriority.P3_BACKGROUND_LEARNING, owner_ref="learning:x",
    )
    assert request is not None
    key = request.resource_keys[0]
    before = (
        coordinator.governor.concurrency_limit(key),
        coordinator.governor.concurrency_limit_source(key),
        coordinator.governor.concurrency_limit_generation(key),
    )
    coordinator.revalidate_request_for_client(
        _client(), request, expected_generation="pid:123"
    )
    after = (
        coordinator.governor.concurrency_limit(key),
        coordinator.governor.concurrency_limit_source(key),
        coordinator.governor.concurrency_limit_generation(key),
    )
    assert after == before


def test_lfrt_authority_observes_every_request_without_ttl_cache():
    calls = []
    authority = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(_payload(pid=123), calls))
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=SimpleNamespace(observe=lambda *_a, **_k: _legacy_state(pid=123)),
        admission_authority="lfrt", lfrt_runtime=authority,
    )
    for n in range(3):
        request = coordinator.build_request_for_client(
            _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
            service_priority=ServicePriority.P0_FOREGROUND, owner_ref=f"task:{n}",
        )
        assert request is not None
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("runner_result", "expected_reason"),
    [
        ((1, "", "boom"), "observation_failed"),
        ((0, "{not-json", ""), "invalid_json"),
        ((0, "", ""), "observation_failed"),
    ],
)
def test_lfrt_authority_command_or_json_failure_is_managed_unknown(runner_result, expected_reason):
    adapter = LFRTAdmissionRuntimeAdapter(
        "/opt/lfrt", runner=lambda _argv, _timeout: runner_result
    )
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.reason == expected_reason
    assert target.key == ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")


def test_lfrt_authority_config_unavailable_cannot_prove_loopback_unmanaged():
    payload = {
        "ok": True,
        "contract": "runtime-observation/v1",
        "state": "unknown",
        "managed": False,
        "reason": "config_unavailable",
    }
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(payload, []))
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.reason == "managed_target_unknown"


def test_lfrt_authority_stopped_managed_runtime_is_not_not_applicable():
    adapter = LFRTAdmissionRuntimeAdapter(
        "/opt/lfrt", runner=_runner(_payload(state="stopped"), [])
    )
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.reason == "runtime_stopped"


@pytest.mark.parametrize(
    "runtime_patch",
    [
        {"pid": 0},
        {"port": 8902},
        {"model": ""},
        {"prompt_concurrency": 0},
        {"decode_concurrency": -1},
    ],
)
def test_lfrt_authority_rejects_partial_or_conflicting_observed_runtime(runtime_patch):
    payload = _payload()
    payload["runtime"].update(runtime_patch)
    adapter = LFRTAdmissionRuntimeAdapter("/opt/lfrt", runner=_runner(payload, []))
    target = adapter.observe_target(_client(), provider_id="cognilocal", model_id="ornith")
    assert target.state is LocalRuntimeTargetState.MANAGED_BUT_UNKNOWN
    assert target.key == ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901")


def test_legacy_default_never_invokes_supplied_lfrt_authority_adapter():
    class LFRTMustNotRun:
        def observe_target(self, *_a, **_k):
            raise AssertionError("LFRT authority must be dormant while legacy is selected")
    class Legacy:
        def observe(self, *_a, **_k):
            return _legacy_state(pid=123)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(), local_runtime=Legacy(), lfrt_runtime=LFRTMustNotRun()
    )
    request = coordinator.build_request_for_client(
        _client(), execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND, owner_ref="task:legacy",
    )
    assert request is not None


def test_lfrt_authority_requires_absolute_executable_path():
    with pytest.raises(ValueError, match="absolute"):
        LFRTAdmissionRuntimeAdapter("relative/lfrt")
