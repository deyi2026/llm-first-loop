from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "erdc", root / "scripts/telemetry/effective_reasoning_duty_cycle.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _event(seq: int, kind: str, second: float, payload: dict) -> dict:
    base = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
    return {
        "seq": seq,
        "session_id": "s1",
        "type": kind,
        "ts": base.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if second == 0
        else (datetime.fromtimestamp(base.timestamp() + second, tz=UTC).isoformat()),
        "payload": payload,
    }


def test_gpu_equivalent_time_is_time_weighted() -> None:
    mod = _load()
    base = datetime(2026, 9, 8, tzinfo=UTC)
    samples = [
        {"_dt": base, "device_utilization_pct": 100},
        {"_dt": base.replace(microsecond=500000), "device_utilization_pct": 50},
        {
            "_dt": datetime.fromtimestamp(base.timestamp() + 1.0, tz=UTC),
            "device_utilization_pct": 0,
        },
    ]
    got = mod.summarize_gpu_interval(
        samples, base, datetime.fromtimestamp(base.timestamp() + 1.0, tz=UTC)
    )
    assert got["gpu_coverage_ms"] == 1000.0
    assert got["gpu_equivalent_ms"] == 750.0
    assert got["gpu_time_weighted_avg_pct"] == 75.0


def test_analyzer_keeps_novelty_mechanical_and_out_of_erdc_score() -> None:
    mod = _load()
    events = [
        _event(1, "request.meta", 0.0, {"round": 1}),
        _event(
            2,
            "request.usage",
            2.0,
            {
                "round": 1,
                "tokens_in": 100,
                "tokens_out": 10,
                "cache_read_tokens": 80,
                "uncached_prompt_tokens": 20,
                "timing": {"provider_total_ms": 2000.0, "first_delta_ms": 1000.0},
            },
        ),
        _event(
            3,
            "tool.execution.started",
            2.1,
            {"round": 1, "execution_id": "x", "tool_name": "probe"},
        ),
        _event(
            4,
            "tool.execution.finished",
            2.6,
            {
                "round": 1,
                "execution_id": "x",
                "tool_name": "probe",
                "status": "success",
                "result_state_sha256": "abc",
            },
        ),
        _event(5, "request.meta", 3.0, {"round": 2}),
        _event(
            6,
            "request.usage",
            4.0,
            {
                "round": 2,
                "tokens_in": 120,
                "tokens_out": 5,
                "cache_read_tokens": 100,
                "uncached_prompt_tokens": 20,
                "timing": {"provider_total_ms": 1000.0, "first_delta_ms": 500.0},
            },
        ),
        _event(
            7,
            "tool.execution.started",
            4.1,
            {"round": 2, "execution_id": "y", "tool_name": "probe"},
        ),
        _event(
            8,
            "tool.execution.finished",
            4.2,
            {
                "round": 2,
                "execution_id": "y",
                "tool_name": "probe",
                "status": "success",
                "result_state_sha256": "abc",
            },
        ),
        _event(9, "run.end", 4.5, {"reason": "completed"}),
    ]
    base = datetime(2026, 9, 8, tzinfo=UTC)
    samples = [
        {
            "_dt": datetime.fromtimestamp(base.timestamp() + n * 0.5, tz=UTC),
            "device_utilization_pct": 100,
        }
        for n in range(10)
    ]
    got = mod.analyze_session(events, samples)
    r1, r2 = got["runs"][0]["rounds"]
    assert r1["cache_reuse_ratio"] == 0.8
    assert r1["tool_wait_share_of_cycle"] == 0.1667
    assert r1["novel_observation_results"] == 1
    assert r1["repeated_observation_results"] == 0
    assert r2["novel_observation_results"] == 0
    assert r2["repeated_observation_results"] == 1
    assert r1["physical_erdc"] is not None
    assert "certainty" not in got["definitions"]
    assert "quality" not in got["definitions"]
    assert "observation" not in got["definitions"]["physical_erdc"]


def test_split_runs_allows_round_numbers_to_reset() -> None:
    mod = _load()
    events = [
        _event(1, "request.meta", 0, {"round": 1}),
        _event(2, "run.end", 1, {"reason": "completed"}),
        _event(3, "request.meta", 2, {"round": 1}),
        _event(4, "run.end", 3, {"reason": "completed"}),
    ]
    runs = mod.split_runs(events)
    assert len(runs) == 2
    assert runs[0][-1]["type"] == "run.end"
    assert runs[1][0]["type"] == "request.meta"
