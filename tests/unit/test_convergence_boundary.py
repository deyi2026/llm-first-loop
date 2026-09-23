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

# ============================================== R2 三件套（antidrift_impl 批1）


def _decide(call_id: str, unresolved: str = "", decision: str = "continue") -> LLMResponse:
    args = {"decision": decision}
    if unresolved:
        args["unresolved"] = unresolved
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id=call_id, name="convergence_decide", arguments=args)
        ],
        provider="fake",
    )


def _receipt(engine, sid: str, call_id: str) -> str:
    persisted = engine.session.load(sid)
    matched = [
        m
        for m in persisted.messages
        if m.role == "tool" and m.tool_call_id == call_id
    ]
    assert len(matched) == 1
    return str(matched[0].content)


def test_t1_7_boundary_receipt_contains_three_fact_segments(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _decide("d1", "首轮未决事实：目标文件仍未读到"),
            LLMResponse(content="收口回答", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    # T1-12 分量：probe 注入后回执含队列压力事实
    engine.interjection_pressure_probe = lambda sid: {
        "count": 2,
        "oldest_enqueued_at": 1758600000.0,
    }
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "收口回答"
    content = _receipt(engine, sid, "d1")
    # 既有判定行保留在前（[状态: success] 前缀为 tool_result_to_message 既有渲染）
    assert content.startswith(
        "[状态: success] convergence_decision=continue; boundary_released=true"
    )
    # 三件套三段（vitals 与 RunState 同源计数：第 4 轮、fake 未提供 usage→如实 0）
    assert "[run_vitals] rounds=4; wall_clock_s=" in content
    assert "; tokens_in=0; tokens_out=0; source=request.usage" in content
    assert "[self_history_mirror] entries=0; truncated_oldest_count=0" in content
    assert "[queue_pressure] waiting_count=2; oldest_enqueued_at=" in content


def test_t1_8_mirror_contains_prior_unresolved_verbatim_in_order(tmp_path, monkeypatch):
    u1 = '第一次 continue 的未决事实甲（含 "引号"）'
    u2 = "第二次 continue 的未决事实乙"
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _decide("d1", u1),
            _read_resp("c4"),
            _read_resp("c5"),
            _read_resp("c6"),
            _decide("d2", u2),
            _read_resp("c7"),
            _read_resp("c8"),
            _read_resp("c9"),
            _decide("d3", "第三次 continue 的未决事实丙"),
            LLMResponse(content="三轮后收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "三轮后收口"

    receipt_d2 = _receipt(engine, sid, "d2")
    assert "[self_history_mirror] entries=1; truncated_oldest_count=0" in receipt_d2
    assert f"1. {u1}" in receipt_d2

    receipt_d3 = _receipt(engine, sid, "d3")
    assert "[self_history_mirror] entries=2; truncated_oldest_count=0" in receipt_d3
    # 镜像含前 2 条 unresolved 逐字原文，按发生顺序（第 N+1 次回执恰含前 N 次）
    assert f"1. {u1}" in receipt_d3
    assert f"2. {u2}" in receipt_d3
    assert receipt_d3.index(u1) < receipt_d3.index(u2)


def test_t1_9_convergence_decide_schema_unchanged_verbatim():
    from llm_loop.tools.builtin.convergence_decide import ConvergenceDecideTool

    assert ConvergenceDecideTool.parameters == {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["continue", "conclude"],
                "description": (
                    "continue=仍有具体未解决事实；conclude=我判定可以收口"
                    "（自陈，非完成裁决）。"
                ),
            },
            "unresolved": {
                "type": "string",
                "maxLength": 1200,
                "description": (
                    "仍需继续的具体未解决事实/缺失证据；仅 continue 必填，"
                    "conclude 可空；不得写泛化的“继续检查”。"
                ),
            },
        },
        "required": ["decision"],
    }


def test_t1_10_continue_still_releases_boundary_with_facts_attached(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _decide("d1", "仍缺目标文件内容"),
            _read_resp("c4"),
            LLMResponse(content="放行后收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "放行后收口"
    # 放行语义不变：continue 后下一轮工具面恢复全量（无论三件套内容）
    assert "read_file" in _tool_names(fake.calls[4])
    assert "convergence_decide" not in _tool_names(fake.calls[4])
    assert "[run_vitals]" in _receipt(engine, sid, "d1")


def test_t1_10_conclude_receipt_also_carries_facts(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _decide("d9", decision="conclude"),
            LLMResponse(content="conclude 后直接回答", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "conclude 后直接回答"
    content = _receipt(engine, sid, "d9")
    assert content.startswith("[状态: success] convergence_decision=conclude")
    assert "[run_vitals]" in content
    # conclude 无 unresolved → 不入镜像累积
    assert "[self_history_mirror] entries=0; truncated_oldest_count=0" in content
    assert "[queue_pressure] unavailable(reason=no_queue_binding)" in content


def test_t1_11_assembler_failure_falls_open_to_plain_receipt(tmp_path, monkeypatch):
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _decide("d1", "fail-open 场景的未决事实"),
            LLMResponse(content="照常收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)

    def _boom(*args, **kwargs):
        raise RuntimeError("assembler down")

    monkeypatch.setattr(
        "llm_loop.core.loop.engine_services.tool_cycle."
        "render_convergence_receipt_addendum",
        _boom,
    )
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    # run 不中断，照常收口
    assert result.final_answer == "照常收口"
    content = _receipt(engine, sid, "d1")
    # fail-open 回退=现状回执逐字（含既有渲染前缀），无三件套
    assert content == (
        "[状态: success] convergence_decision=continue; boundary_released=true"
    )
    assert "[run_vitals]" not in content
