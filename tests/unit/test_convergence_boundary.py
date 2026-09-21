"""P0-B prompt-neutral multi-round convergence decision boundary."""

from __future__ import annotations

from llm_loop.core.loop.engine_services.convergence_boundary import (
    ConvergenceFacts,
    evaluate_convergence_boundary,
)
from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
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
    """Test-only: the shared fake intentionally omits tools from its call log."""
    original = fake.chat

    def _chat(messages, tools, **kwargs):
        result = original(messages, tools, **kwargs)
        fake.calls[-1]["tools"] = tools
        return result

    fake.chat = _chat


def _read_resp(call_id: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="read_file",
                arguments={"path": "/nonexistent/convergence-target"},
            )
        ],
        provider="fake",
    )


def test_boundary_predicate_is_mechanical_and_async_obligations_fail_open():
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


def test_normal_round_hides_decision_tool(tmp_path, monkeypatch):
    engine, fake = _mk(tmp_path, monkeypatch, responses=[LLMResponse(content="done", tool_calls=[], provider="fake")])
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "任务")
    assert result.final_answer == "done"
    assert "convergence_decide" not in _tool_names(fake.calls[0])


def test_repeat_boundary_next_round_exposes_only_decision_tool_without_prompt_injection(
    tmp_path, monkeypatch
):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            LLMResponse(content="收口回答", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "收口回答"
    assert _tool_names(fake.calls[3]) == ["convergence_decide"]
    wire = "\n".join(
        str(m.get("content") or "")
        for call in fake.calls
        for m in call.get("messages") or []
    )
    assert "收敛边界" not in wire
    assert "convergence.boundary" not in wire


def test_continue_decision_reopens_normal_tool_surface(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="decision-1",
                        name="convergence_decide",
                        arguments={
                            "decision": "continue",
                            "unresolved": "还未取得目标文件内容",
                        },
                    )
                ],
                provider="fake",
            ),
            LLMResponse(content="继续后的回答", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "继续后的回答"
    assert _tool_names(fake.calls[3]) == ["convergence_decide"]
    assert "read_file" in _tool_names(fake.calls[4])
    assert "convergence_decide" not in _tool_names(fake.calls[4])


def test_outstanding_async_obligation_suppresses_boundary(tmp_path, monkeypatch):
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


def test_simulated_weak_model_canary_converges_in_bounded_rounds(tmp_path, monkeypatch):
    """Weak-model canary: repetitive exploration must hit one clean decision boundary."""
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("weak-1"),
            _read_resp("weak-2"),
            _read_resp("weak-3"),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="weak-decision",
                        name="convergence_decide",
                        arguments={
                            "decision": "continue",
                            "unresolved": "缺少一次不同来源的事实核验",
                        },
                    )
                ],
                provider="fake",
            ),
            LLMResponse(content="弱模型最终收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()

    result = engine.run(sid, "模拟弱模型长任务")

    assert result.final_answer == "弱模型最终收口"
    assert len(fake.calls) == 5
    assert _tool_names(fake.calls[3]) == ["convergence_decide"]
    assert "read_file" in _tool_names(fake.calls[4])
    wire = "\n".join(
        str(message.get("content") or "")
        for call in fake.calls
        for message in call.get("messages") or []
    )
    assert "convergence.boundary" not in wire
    assert "收敛边界" not in wire


def test_boundary_blocks_hallucinated_hidden_tool_at_execution_layer(tmp_path, monkeypatch):
    """Boundary is a capability fence: hidden ordinary tools cannot execute by hallucination."""
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _read_resp("hallucinated-hidden-call"),
            LLMResponse(content="边界后收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()

    result = engine.run(sid, "真实任务")

    assert result.final_answer == "边界后收口"
    assert _tool_names(fake.calls[3]) == ["convergence_decide"]
    assert _tool_names(fake.calls[4]) == ["convergence_decide"]
    persisted = engine.session.load(sid)
    blocked = [
        message
        for message in persisted.messages
        if message.role == "tool"
        and message.tool_call_id == "hallucinated-hidden-call"
    ]
    assert len(blocked) == 1
    assert blocked[0].status.value == "blocked"
    assert "reason_code=convergence_boundary" in blocked[0].content
