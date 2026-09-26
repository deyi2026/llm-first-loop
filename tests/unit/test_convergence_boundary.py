"""Convergence signals are telemetry; concrete tools remain directly callable."""

from __future__ import annotations

from llm_loop.core.loop.engine_services.convergence_boundary import (
    ConvergenceFacts,
    evaluate_convergence_boundary,
)
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.builtin.convergence_decide import ConvergenceDecideTool
from tests.unit.test_err1210_recovery import _mk


def _tool_names(call: dict) -> list[str]:
    out: list[str] = []
    for item in call.get("tools") or []:
        if isinstance(item, dict) and item.get("name"):
            out.append(str(item["name"]))
            continue
        fn = item.get("function") if isinstance(item, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            out.append(str(fn["name"]))
    return out


def _capture_tools(fake) -> None:
    original = fake.chat

    def _chat(messages, tools, **kwargs):
        result = original(messages, tools, **kwargs)
        fake.calls[-1]["tools"] = tools
        return result

    fake.chat = _chat


def _read_resp(call_id: str, path: str = "/nonexistent/convergence-target") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name="read_file", arguments={"path": path})],
        provider="fake",
    )


def test_convergence_predicate_remains_mechanical_and_async_obligations_fail_open():
    assert evaluate_convergence_boundary(
        ConvergenceFacts(rounds=3, repeated_exact_call_count=3)
    ).reasons == ("repeated_exact_call",)
    assert evaluate_convergence_boundary(
        ConvergenceFacts(rounds=2, consecutive_empty_searches=2)
    ).reasons == ("consecutive_empty_search",)
    assert evaluate_convergence_boundary(
        ConvergenceFacts(rounds=6, context_ratio=0.8)
    ).reasons == ("high_context_pressure",)
    assert evaluate_convergence_boundary(
        ConvergenceFacts(goal_task_total=4, goal_open_tasks=0)
    ).reasons == ("goal_frontier_closed",)
    assert not evaluate_convergence_boundary(
        ConvergenceFacts(
            rounds=20,
            repeated_exact_call_count=10,
            context_ratio=0.95,
            outstanding_async_obligations=1,
        )
    ).arm


def test_factory_does_not_register_convergence_meta_router(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[LLMResponse(content="done", tool_calls=[], provider="fake")],
    )
    _capture_tools(fake)
    assert "convergence_decide" not in engine.registry.names()

    sid = engine.session.create()
    result = engine.run(sid, "任务")

    assert result.final_answer == "done"
    assert "convergence_decide" not in _tool_names(fake.calls[0])
    assert "read_file" in _tool_names(fake.calls[0])


def test_repeat_observation_keeps_real_tools_visible_and_executes_direct_call(
    tmp_path, monkeypatch
):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            # This round occurs after the repeated-exact-call convergence signal.
            # It must call the real tool directly, with no convergence_decide detour.
            _read_resp("c4", "/nonexistent/different-target"),
            LLMResponse(content="直接工具后收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()

    result = engine.run(sid, "真实任务")

    assert result.final_answer == "直接工具后收口"
    assert "read_file" in _tool_names(fake.calls[3])
    assert "convergence_decide" not in _tool_names(fake.calls[3])

    persisted = engine.session.load(sid)
    c4 = [m for m in persisted.messages if m.role == "tool" and m.tool_call_id == "c4"]
    assert len(c4) == 1
    assert c4[0].status is not ToolResultStatus.BLOCKED
    assert "reason_code=convergence_boundary" not in c4[0].content

    trace = str(engine.status.snapshot().get("action_trace", []))
    assert "convergence.observation" in trace
    assert "direct_tool_continued" in trace


def test_reordered_equivalent_args_arm_convergence_then_direct_tool_continues(
    tmp_path, monkeypatch
):
    target = "/nonexistent/convergence-target"

    def _resp(call_id: str, arguments: dict) -> LLMResponse:
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=call_id, name="read_file", arguments=arguments)],
            provider="fake",
        )

    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _resp("c1", {"path": target, "offset": 0, "limit": 1}),
            _resp("c2", {"limit": 1, "path": target, "offset": 0}),
            _resp("c3", {"offset": 0, "limit": 1, "path": target}),
            _resp("c4", {"path": target, "limit": 1, "offset": 0}),
            LLMResponse(content="done", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()

    result = engine.run(sid, "真实任务")

    assert result.final_answer == "done"
    trace = str(engine.status.snapshot().get("action_trace", []))
    assert "exact_call_count=3" in trace
    assert "convergence.observation" in trace
    assert "direct_tool_continued" in trace
    assert "read_file" in _tool_names(fake.calls[3])
    assert "convergence_decide" not in _tool_names(fake.calls[3])


def test_materially_different_args_do_not_arm_repeat_convergence(tmp_path, monkeypatch):
    engine, _fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1", "/nonexistent/a"),
            _read_resp("c2", "/nonexistent/b"),
            _read_resp("c3", "/nonexistent/c"),
            LLMResponse(content="done", tool_calls=[], provider="fake"),
        ],
    )
    sid = engine.session.create()

    result = engine.run(sid, "真实任务")

    assert result.final_answer == "done"
    trace = str(engine.status.snapshot().get("action_trace", []))
    assert "tool.repeat_observed" not in trace
    assert "reasons=repeated_exact_call" not in trace


def test_outstanding_async_obligation_does_not_change_direct_tool_surface(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            LLMResponse(content="answer", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    engine.registry.add_async_obligation_hook(
        lambda _sid: [{"kind": "child", "state": "running"}]
    )
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")

    assert result.final_answer == "answer"
    assert "read_file" in _tool_names(fake.calls[3])
    assert "convergence_decide" not in _tool_names(fake.calls[3])


def test_legacy_convergence_tool_is_replay_safe_but_not_routing_authority():
    tool = ConvergenceDecideTool()
    missing = tool.execute(decision="continue", unresolved="")
    cont = tool.execute(decision="continue", unresolved="still missing a fact")
    conclude = tool.execute(decision="conclude")

    assert missing.status is ToolResultStatus.FAILURE
    assert cont.status is ToolResultStatus.SUCCESS
    assert conclude.status is ToolResultStatus.SUCCESS
    assert "boundary_released=true" in cont.content


def test_legacy_convergence_schema_stays_parseable_for_historical_replay():
    assert ConvergenceDecideTool.parameters["type"] == "object"
    assert ConvergenceDecideTool.parameters["required"] == ["decision"]
    decision = ConvergenceDecideTool.parameters["properties"]["decision"]
    assert decision["enum"] == ["continue", "conclude"]
