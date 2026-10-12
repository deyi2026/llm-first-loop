"""P1-B RoundReachabilityRecorder factual-chain tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.loop.engine_services.tool_reachability import (
    DEFAULT_LOG_PATH,
    RoundReachabilityRecorder,
    tool_schema_names,
)


def _recorder(tmp_path):
    return RoundReachabilityRecorder(path=str(tmp_path / "obs" / "tool_reachability.jsonl"))


def test_round_factual_chain_jsonl(tmp_path):
    rec = _recorder(tmp_path)
    rec.begin_round(session_id="s1", round_no=3)
    rec.record_projection(
        registered=["a", "b"], candidate=["a", "b"], final_callable=["a"], quarantined=["b"]
    )
    rec.record_emission(
        [
            {
                "tool_call_id": "c1",
                "name": "a",
                "raw_arguments": '{"k":1}',
                "arguments": {"k": 1},
                "valid": True,
            }
        ]
    )
    rec.record_executed(
        [{"tool_call_id": "c1", "name": "a", "status": "success", "blocked": False}]
    )
    assert rec.flush() is True
    d = json.loads((tmp_path / "obs" / "tool_reachability.jsonl").read_text())
    assert d["registered_tools"] == ["a", "b"]
    assert d["candidate_tools"] == ["a", "b"]
    assert d["final_provider_callable_tools"] == ["a"]
    assert d["quarantined_tools"] == ["b"]
    assert d["emissions"][0]["raw_arguments"] == '{"k":1}'
    assert d["executed"][0]["status"] == "success"
    for retired in (
        "eligibility_mode",
        "promotion_mode",
        "promoted_tools",
        "promotion_state",
        "schema_lookups",
        "capability_required_tools",
        "capability_would_select_tools",
    ):
        assert retired not in d


def test_fail_open_unwritable_path(tmp_path):
    rec = RoundReachabilityRecorder(path=str(tmp_path))
    rec.begin_round()
    rec.record_emission([])
    assert rec.flush() is False and rec.last_flushed == {}


def test_env_off_disables(monkeypatch):
    monkeypatch.setenv("TOOL_REACHABILITY_LOG", "off")
    rec = RoundReachabilityRecorder()
    rec.begin_round(session_id="s")
    assert rec.flush() is False


def test_retry_clones_only_factual_projection(tmp_path):
    rec = _recorder(tmp_path)
    rec.begin_round(session_id="s", round_no=1)
    rec.record_projection(
        registered=["a", "b"], candidate=["a", "b"], final_callable=["a"], quarantined=["b"]
    )
    rec.ensure_attempt(kind="primary", model="m", provider="p")
    rec.finalize("provider_error")
    rec.begin_attempt_from_last_projection(
        kind="same_model_retry", attempt_index=1, model="m", provider="p"
    )
    cur = rec.current
    assert cur["registered_tools"] == ["a", "b"] and cur["quarantined_tools"] == ["b"]
    assert cur["emissions"] == [] and cur["executed"] == []


def test_tool_schema_names_openai_style():
    schemas = [{"type": "function", "function": {"name": "f1"}}, {"name": "f2"}, "garbage", {}]
    assert tool_schema_names(schemas) == ["f1", "f2"]
    assert tool_schema_names(None) == []
    assert DEFAULT_LOG_PATH.endswith("tool_reachability.jsonl")


def test_recorder_init_in_tool_cycle():
    svc = ToolCycleService(SimpleNamespace())
    assert isinstance(svc._round_obs, RoundReachabilityRecorder)
