from __future__ import annotations

import copy

import pytest

from llm_loop.resources.lfrt_runtime import LFRTStatusObserver, parse_lfrt_status


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
