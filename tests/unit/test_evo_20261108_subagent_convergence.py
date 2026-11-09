"""EVO-20261108-b5fead21（human-approved 2026-11-08 21:38）①② 落地测试.

① 轮次预算将尽且无三态结论 token 时，运行时注入一次【运行时收敛提醒·
   非真人/父级新授权】软提示（不改授权边界；有结论则不注入）。
② truncated 结果细分 truncation_detail:
   completed_with_verdict（结论已在、收尾未完成）/ exhausted_without_verdict
   （未收敛），并在 subagent_result 回执给出处置口径。
"""
from __future__ import annotations

from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import (
    SubAgentResult,
    SubAgentRunner,
    assistant_verdict_marker,
    convergence_reminder_threshold,
)

_REMINDER_LABEL = "运行时收敛提醒"


def _tool_only(cid: str, command: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=cid, name="execute_command", arguments={"command": command})],
        provider="fake",
    )


def _wires_with_reminder(fake) -> list[int]:
    return [
        idx
        for idx, call in enumerate(fake.calls)
        if any(
            _REMINDER_LABEL in str(m.get("content") or "")
            for m in call.get("messages", [])
            if m.get("role") == "user"
        )
    ]


# ── 判据单元（机械判定，不证明结论真伪） ────────────────────────────────


def test_verdict_marker_detects_uppercase_tokens_only():
    msgs = [
        Message(role="assistant", content="分析 passing 中的 FAILED 场景与 blocked 状态", source=MessageSource.SYSTEM),
        Message(role="assistant", content="结论: PASS", source=MessageSource.SYSTEM),
    ]
    assert assistant_verdict_marker(msgs) == "PASS"


def test_verdict_marker_ignores_substring_and_non_assistant():
    msgs = [
        Message(role="user", content="请给出 PASS/FAIL/BLOCK", source=MessageSource.USER),
        Message(role="assistant", content="FAILED passing blocked", source=MessageSource.SYSTEM),
        Message(role="assistant", content="细节不足，failure mode 待查", source=MessageSource.SYSTEM),
    ]
    assert assistant_verdict_marker(msgs) == ""
    assert assistant_verdict_marker([]) == ""


def test_convergence_threshold_values():
    assert convergence_reminder_threshold(20) == 5
    assert convergence_reminder_threshold(8) == 3
    assert convergence_reminder_threshold(4) == 3
    assert convergence_reminder_threshold(2) == 3
    assert convergence_reminder_threshold(None) == 0


def test_result_payload_roundtrips_truncation_detail():
    result = SubAgentResult(
        final_answer="x",
        outcome="truncated",
        truncated=True,
        truncation_detail="exhausted_without_verdict",
    )
    payload = SubAgentRunner._result_payload(result)
    back = SubAgentRunner._result_from_payload(payload)
    assert back.truncation_detail == "exhausted_without_verdict"
    assert back.outcome == "truncated"
    # 旧版本持久化 payload（无该键）→ 空串，向后兼容。
    legacy = dict(payload)
    legacy.pop("truncation_detail")
    assert SubAgentRunner._result_from_payload(legacy).truncation_detail == ""


# ── ① loop 级注入 ─────────────────────────────────────────────────────


def test_reminder_injected_once_when_budget_low_and_no_verdict(build_test_engine):
    """8 轮预算、全程只有工具调用: 阈值 3 → 首个含提醒的 wire 是第 5 轮，且只出现一次。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=8
    )
    fake._responses = [
        _tool_only(f"c{i}", f"echo {i}") for i in range(1, 9)
    ]

    result = runner.run(task="永不收敛的取证任务", depth=0)

    assert result.outcome == "truncated"
    assert len(fake.calls) == 8
    # 首个含提醒的 wire 是 rounds=5（剩余 3 轮恰达阈值）；此前轮次不得出现。
    # 注入后消息留在 transcript 里，后续 wire 都会带上——"只注入一次"以
    # 最终 wire 中带标签 user 消息数量 == 1 为准。
    hit = _wires_with_reminder(fake)
    assert hit and hit[0] == 4 and hit == list(range(4, 8)), hit
    final_user = [
        m
        for m in fake.calls[7]["messages"]
        if m.get("role") == "user"
    ]
    labeled = [m for m in final_user if _REMINDER_LABEL in str(m.get("content") or "")]
    assert len(labeled) == 1, [str(m.get("content"))[:40] for m in final_user]
    assert "非真人/父级新授权" in str(labeled[0].get("content"))
    assert "必须给出最终回答" not in str(labeled[0].get("content"))


def test_reminder_suppressed_once_verdict_token_present(build_test_engine):
    """transcript 已出现三态结论 token（哪怕结论尚不完整）→ 不注入提醒。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=8
    )
    responses = [_tool_only(f"c{i}", f"echo {i}") for i in range(1, 9)]
    responses[2] = LLMResponse(
        content="初步结论: FAIL（细节待补）",
        tool_calls=[ToolCall(id="c3", name="execute_command", arguments={"command": "echo 3"})],
        provider="fake",
    )
    fake._responses = responses

    result = runner.run(task="先给结论再继续取证", depth=0)

    assert result.outcome == "truncated"
    assert _wires_with_reminder(fake) == []


# ── ② 截断细分 ────────────────────────────────────────────────────────


def test_truncation_detail_exhausted_without_verdict(build_test_engine):
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    fake._responses = [_tool_only("c1", "echo 1"), _tool_only("c2", "echo 2")]

    result = runner.run(task="无结论死循环", depth=0)

    assert result.truncated is True
    assert result.truncation_detail == "exhausted_without_verdict"
    assert "exhausted_without_verdict" in result.final_answer


def test_truncation_detail_completed_with_verdict(build_test_engine):
    """中途已写出结论 token、但收尾前预算耗尽 → completed_with_verdict。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    fake._responses = [
        LLMResponse(
            content="结论: BLOCK——预算内无法完成验证，缺口: 缺 X 证据",
            tool_calls=[ToolCall(id="c1", name="execute_command", arguments={"command": "echo 1"})],
            provider="fake",
        ),
        _tool_only("c2", "echo 2"),
    ]

    result = runner.run(task="审查并给出三态结论", depth=0)

    assert result.truncated is True
    assert result.truncation_detail == "completed_with_verdict"


def test_subagent_result_receipt_surfaces_truncation_detail(build_test_engine):
    """端到端: spawn → 截断 → subagent_result 回执含 [截断细分] 处置口径。"""
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    fake._responses = [_tool_only("c1", "echo 1"), _tool_only("c2", "echo 2")]
    started = SpawnSubAgentTool(runner).execute(task="预算内无法收敛")
    assert started.status.value == "success"

    import re as _re

    match = _re.search(r"child_id=(subagent_[0-9a-f]+)", started.content)
    assert match, started.content
    terminal = SubAgentResultTool(runner).execute(child_id=match.group(1), wait_seconds=5)

    assert terminal.status.value == "failure"
    assert "child_outcome=truncated" in terminal.content
    assert "[截断细分]" in terminal.content
    assert "exhausted_without_verdict" in terminal.content
    assert "重派" in terminal.content
