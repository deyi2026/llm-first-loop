from __future__ import annotations

import copy

import pytest

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    ObservedResourceState,
    ResourceKey,
    ResourceScopeKind,
    RuntimeType,
)
from llm_loop.resources.lfrt_runtime import (
    LFRTStatusObserver,
    compare_lfrt_with_legacy,
    parse_lfrt_status,
)
from llm_loop.resources.local_runtime import LocalRuntimeIdentityObservation


def _payload() -> dict:
    return {
        "ok": True,
        "cmd": "status",
        "ts": "2026-09-16T08:43:38",
        "data": {
            "launchd": {
                "known": True,
                "registered": True,
                "state": "running",
                "pid": 52430,
            },
            "process": {
                "pid": 52430,
                "flags": {
                    "model": "~/.lmstudio/models/ornith-ai/Ornith-1.5-35B-A3B-MLX",
                    "port": "8901",
                    "prompt-concurrency": "1",
                    "decode-concurrency": "1",
                },
            },
            "server": {
                "port_listening": True,
                "listener": {"known": True, "pid": 52430},
                "health": True,
            },
            "config": {
                "model_path": "~/.lmstudio/models/ornith-ai/Ornith-1.5-35B-A3B-MLX",
                "aliases": ["ornith-1.5-35b-a3b-mlx", "ornith-ai/Ornith-1.5-35B-A3B-MLX"],
                "concurrency": {"prompt": 1, "decode": 1},
                "port": 8901,
            },
        },
    }


def test_parser_projects_validated_live_facts_and_uses_live_capacity() -> None:
    snapshot = parse_lfrt_status(_payload(), observed_at=123.0)

    assert snapshot is not None
    assert snapshot.observed_at == 123.0
    assert snapshot.source_ref == "lfrt-status:8901:pid:52430"
    assert snapshot.launchd_pid == snapshot.listener_pid == snapshot.process_pid == 52430
    assert snapshot.port == 8901
    assert snapshot.model_identity == "Ornith-1.5-35B-A3B-MLX"
    assert snapshot.live_prompt_concurrency == 1
    assert snapshot.live_decode_concurrency == 1
    assert snapshot.max_concurrency == 1
    assert snapshot.endpoint_healthy is True
    assert snapshot.drift is False


def test_parser_reports_config_drift_without_replacing_live_capacity() -> None:
    payload = _payload()
    payload["data"]["config"]["concurrency"] = {"prompt": 8, "decode": 8}

    snapshot = parse_lfrt_status(payload, observed_at=1.0)

    assert snapshot is not None
    assert snapshot.max_concurrency == 1
    assert snapshot.configured_prompt_concurrency == 8
    assert snapshot.configured_decode_concurrency == 8
    assert snapshot.drift is True


@pytest.mark.parametrize(
    ("mutate",),
    [
        (lambda p: p.update(ok=False),),
        (lambda p: p.update(cmd="health"),),
        (lambda p: p["data"]["launchd"].update(known=False),),
        (lambda p: p["data"]["launchd"].update(state="waiting"),),
        (lambda p: p["data"]["server"]["listener"].update(known=False),),
        (lambda p: p["data"]["server"]["listener"].update(pid=999),),
        (lambda p: p["data"]["process"].update(pid=998),),
        (lambda p: p["data"]["process"]["flags"].pop("prompt-concurrency"),),
        (lambda p: p["data"]["process"]["flags"].update(**{"decode-concurrency": "0"}),),
        (lambda p: p["data"]["process"]["flags"].update(port="8902"),),
        (lambda p: p["data"]["server"].update(health="yes"),),
    ],
)
def test_parser_fails_unknown_on_incomplete_or_conflicting_mechanical_facts(mutate) -> None:
    payload = copy.deepcopy(_payload())
    mutate(payload)
    assert parse_lfrt_status(payload, observed_at=1.0) is None


def test_observer_executes_only_fixed_read_only_status_argv() -> None:
    calls = []

    def runner(argv: tuple[str, ...], timeout_s: float):
        calls.append((argv, timeout_s))
        import json

        return 0, json.dumps(_payload()), ""

    observer = LFRTStatusObserver(
        "/opt/lfrt/lfrt", runner=runner, clock=lambda: 456.0, timeout_s=1.5
    )

    snapshot = observer.observe()

    assert snapshot is not None
    assert snapshot.observed_at == 456.0
    assert calls == [(('/opt/lfrt/lfrt', 'status', '--json'), 1.5)]


@pytest.mark.parametrize(
    ("result",),
    [
        ((1, "", "failed"),),
        ((0, "", ""),),
        ((0, "not-json", ""),),
        ((0, "{}", ""),),
        ((0, '{"ok":true,"cmd":"status","data":{}}', "warning"),),
    ],
)
def test_observer_fails_unknown_on_command_or_payload_failure(result) -> None:
    observer = LFRTStatusObserver(
        "/opt/lfrt/lfrt", runner=lambda _argv, _timeout: result
    )
    assert observer.observe() is None


def test_observer_fails_unknown_when_runner_raises() -> None:
    def runner(_argv: tuple[str, ...], _timeout_s: float):
        raise TimeoutError("timeout")

    assert LFRTStatusObserver("/opt/lfrt/lfrt", runner=runner).observe() is None


def test_observer_requires_absolute_executable_and_positive_timeout() -> None:
    with pytest.raises(ValueError, match="absolute"):
        LFRTStatusObserver("runtime/lfrt")
    with pytest.raises(ValueError, match="positive"):
        LFRTStatusObserver("/opt/lfrt/lfrt", timeout_s=0)


def _legacy_state(*, pid: int = 52430, capacity: int = 1) -> ObservedResourceState:
    return ObservedResourceState(
        key=ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, "mlx-loopback:8901"),
        provenance=FactProvenance(
            source=FactSource.RUNTIME_PROBE,
            source_ref=f"local-listener:8901:pid:{pid}",
            recorded_at=123.0,
        ),
        runtime_type=RuntimeType.LOCAL,
        max_concurrency=capacity,
    )


def _legacy_identity(*, pid: int = 52430, model: str = "Ornith-1.5-35B-A3B-MLX"):
    return LocalRuntimeIdentityObservation(
        identity=f"mlx_lm.server/{model}",
        source_ref=f"local-listener:8901:pid:{pid}",
    )


def test_shadow_parity_matches_without_changing_legacy_authority() -> None:
    lfrt = parse_lfrt_status(_payload(), observed_at=123.0)

    report = compare_lfrt_with_legacy(lfrt, _legacy_state(), _legacy_identity())

    assert report.status == "match"
    assert report.mismatches == ()
    assert report.lfrt_source_ref == "lfrt-status:8901:pid:52430"
    assert report.legacy_source_ref == "local-listener:8901:pid:52430"


def test_shadow_parity_reports_mismatch_mechanically() -> None:
    lfrt = parse_lfrt_status(_payload(), observed_at=123.0)

    report = compare_lfrt_with_legacy(
        lfrt,
        _legacy_state(pid=999, capacity=2),
        _legacy_identity(pid=999, model="Other-Model"),
    )

    assert report.status == "mismatch"
    assert report.mismatches == (
        "listener_pid",
        "max_concurrency",
        "runtime_identity",
        "identity_source",
    )


@pytest.mark.parametrize("missing", ["lfrt", "state", "identity"])
def test_shadow_parity_is_unknown_when_either_observer_is_incomplete(missing: str) -> None:
    lfrt = parse_lfrt_status(_payload(), observed_at=123.0)
    state = _legacy_state()
    identity = _legacy_identity()
    if missing == "lfrt":
        lfrt = None
    elif missing == "state":
        state = None
    else:
        identity = None

    report = compare_lfrt_with_legacy(lfrt, state, identity)

    assert report.status == "unknown"
    assert report.mismatches == ()


def test_parser_rejects_listener_pid_when_port_listening_claim_is_false() -> None:
    payload = _payload()
    payload["data"]["server"]["port_listening"] = False
    assert parse_lfrt_status(payload, observed_at=1.0) is None


def test_parser_rejects_fractional_numeric_facts_instead_of_truncating() -> None:
    payload = _payload()
    payload["data"]["config"]["port"] = 8901.5
    assert parse_lfrt_status(payload, observed_at=1.0) is None


@pytest.mark.parametrize("config_body", [None, "{not-json", "[]"])
def test_default_runner_does_not_invoke_lfrt_when_config_load_could_write(
    tmp_path, config_body
) -> None:
    executable = tmp_path / "lfrt"
    marker = tmp_path / "invoked"
    executable.write_text(
        "#!/bin/sh\nprintf invoked > " + str(marker) + "\nprintf '{\"ok\":true}'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    if config_body is not None:
        (tmp_path / "config.json").write_text(config_body, encoding="utf-8")

    observer = LFRTStatusObserver(executable)

    assert observer.observe() is None
    assert not marker.exists()
    assert not (tmp_path / "config.json.bak").exists()
