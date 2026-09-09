"""LoopEngine 级 nonblocking subagent handle/steer/result 闭环。"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import replace

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse


def test_parent_llm_can_spawn_continue_steer_await_and_finalize(build_test_engine):
    """父 LLM 真正四轮可达：spawn→agent_message→subagent_result→normal final。"""
    engine, fake = build_test_engine([])
    from llm_loop.core.run_context import current_session_id

    runner = engine.registry.get("spawn_subagent")._runner
    seen: list[tuple[str, list[str]]] = []
    seen_guard = threading.Lock()

    def _chat(messages, tools, **kwargs):
        del tools, kwargs
        sid = current_session_id.get()
        with seen_guard:
            seen.append((sid, [m.get("role", "") for m in messages]))

        if sid.startswith("subagent_"):
            tool_receipts = [m for m in messages if m.get("role") == "tool"]
            if not tool_receipts:
                # child 第一轮故意等父模型下一轮真正执行 agent_message；不是等父
                # fake “计划发送”，因此证明 parent LLM 在 spawn 返回后确实继续了。
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    with runner._children_guard:
                        pending = list(runner._agent_inbox.get(sid, []))
                    if pending:
                        break
                    time.sleep(0.01)
                assert pending and pending[-1][2] == "优先验证 A，再收口"
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="child-read",
                            name="read_file",
                            arguments={"path": "/nonexistent-async-engine"},
                        )
                    ],
                    provider="fake",
                )
            assert any(
                m.get("role") == "user" and "优先验证 A，再收口" in str(m.get("content", ""))
                for m in messages
            ), messages
            return LLMResponse(content="child-steered-done", tool_calls=[], provider="fake")

        # parent main loop：根据真实 tool receipt 选择下一动作。
        tool_receipts = [m for m in messages if m.get("role") == "tool"]
        if not tool_receipts:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="parent-spawn",
                        name="spawn_subagent",
                        arguments={"task": "后台检查一个事实，等待父级可能的纠偏"},
                    )
                ],
                provider="fake",
            )
        last = str(tool_receipts[-1].get("content", ""))
        if "child_state=running" in last and "child_id=" in last:
            match = re.search(r"child_id=(subagent_[0-9a-f]+)", last)
            assert match, last
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="parent-steer",
                        name="agent_message",
                        arguments={
                            "target_id": match.group(1),
                            "content": "优先验证 A，再收口",
                        },
                    )
                ],
                provider="fake",
            )
        if "已排队到直接 child" in last:
            spawn_receipt = next(
                str(m.get("content", ""))
                for m in tool_receipts
                if "child_state=running" in str(m.get("content", ""))
            )
            match = re.search(r"child_id=(subagent_[0-9a-f]+)", spawn_receipt)
            assert match, spawn_receipt
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="parent-await",
                        name="subagent_result",
                        arguments={"child_id": match.group(1), "wait_seconds": 2},
                    )
                ],
                provider="fake",
            )
        assert "child_outcome=completed" in last, last
        assert "child-steered-done" in last, last
        return LLMResponse(content="parent-final-after-child", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    parent_sid = engine.session.create()
    result = engine.run(parent_sid, "请派子代理后台处理，并在运行中纠偏后回收结果")

    assert result.final_answer.startswith("parent-final-after-child")
    assert [item["name"] for item in result.tool_calls] == [
        "spawn_subagent",
        "agent_message",
        "subagent_result",
    ]
    parent_calls = [roles for sid, roles in seen if sid == parent_sid]
    child_calls = [roles for sid, roles in seen if sid.startswith("subagent_")]
    assert len(parent_calls) == 4
    assert len(child_calls) == 2


def test_terminal_unread_child_does_not_override_parent_model_final(build_test_engine):
    """terminal child 结果是否读取由模型决定；程序不得丢弃 parent 的 no-tool final。"""
    engine, fake = build_test_engine([])
    from llm_loop.core.run_context import current_session_id

    runner = engine.registry.get("spawn_subagent")._runner
    parent_sid = engine.session.create()
    parent_round = 0

    def _chat(messages, tools, **kwargs):
        nonlocal parent_round
        del tools, kwargs
        sid = current_session_id.get()
        if sid.startswith("subagent_"):
            return LLMResponse(content="fast-child-done", tool_calls=[], provider="fake")
        parent_round += 1
        if parent_round == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="spawn-fast", name="spawn_subagent", arguments={"task": "快速完成"})
                ],
                provider="fake",
            )
        # 等 child 真正 terminal，证明 unread terminal handle 也不能变成 completion gate。
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with runner._children_guard:
                owned = [h for h in runner._handles.values() if h.parent_id == parent_sid]
                if owned and all(h.state != "running" for h in owned):
                    break
            time.sleep(0.01)
        assert owned and all(h.state == "completed" for h in owned)
        assert all(not h.collected for h in owned)
        return LLMResponse(
            content="parent-final-without-reading-child", tool_calls=[], provider="fake"
        )

    fake.chat = _chat  # type: ignore[method-assign]
    result = engine.run(parent_sid, "可派 child；是否采用 child 结果由你自己判断")
    assert result.final_answer.startswith("parent-final-without-reading-child")
    assert parent_round == 2
    assert [item["name"] for item in result.tool_calls] == ["spawn_subagent"]


def test_model_final_cancels_still_running_child_without_reopening_model_round(build_test_engine):
    """模型 final 保持权威；程序只机械取消仍运行 child，防止答复后继续副作用。"""
    engine, fake = build_test_engine([])
    from llm_loop.core.run_context import current_session_id

    runner = engine.registry.get("spawn_subagent")._runner
    parent_sid = engine.session.create()
    child_entered = threading.Event()
    release_child = threading.Event()
    executed = threading.Event()
    parent_round = 0

    class _LateEffect:
        name = "web_search"
        description = "parent final 后不得执行的探针"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            del kwargs
            executed.set()
            return "should-not-run"

    engine.registry.register(_LateEffect())

    def _chat(messages, tools, **kwargs):
        nonlocal parent_round
        del messages, tools, kwargs
        sid = current_session_id.get()
        if sid.startswith("subagent_"):
            child_entered.set()
            assert release_child.wait(2.0)
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="late-effect", name="web_search", arguments={})],
                provider="fake",
            )
        parent_round += 1
        if parent_round == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="spawn-running", name="spawn_subagent", arguments={"task": "等待"})
                ],
                provider="fake",
            )
        assert child_entered.wait(2.0)
        return LLMResponse(content="parent-model-final", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    result = engine.run(parent_sid, "派 child 后你仍可自主决定直接结束")
    assert result.final_answer.startswith("parent-model-final")
    assert parent_round == 2
    release_child.set()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with runner._children_guard:
            owned = [h for h in runner._handles.values() if h.parent_id == parent_sid]
            if owned and all(h.state != "running" for h in owned):
                break
        time.sleep(0.01)
    assert owned
    assert all(h.cancel_requested for h in owned)
    assert all(h.state == "cancelled" for h in owned)
    assert not executed.is_set()


def test_abnormal_parent_exit_cancels_background_child_before_late_effect(build_test_engine):
    """parent 非 completed 退出时 structured child 必须级联 cancel，不能后台继续副作用。"""
    engine, fake = build_test_engine([])
    from llm_loop.core.run_context import current_session_id

    runner = engine.registry.get("spawn_subagent")._runner
    engine.settings = replace(engine.settings, max_iterations=1)
    release_child = threading.Event()
    child_entered = threading.Event()
    executed = threading.Event()

    class _LateEffect:
        name = "web_search"
        description = "异常 parent 退出后不得执行的副作用探针"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            del kwargs
            executed.set()
            return "should-not-run"

    engine.registry.register(_LateEffect())

    def _chat(messages, tools, **kwargs):
        del messages, tools, kwargs
        sid = current_session_id.get()
        if sid.startswith("subagent_"):
            child_entered.set()
            release_child.wait(2.0)
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="late-effect", name="web_search", arguments={})],
                provider="fake",
            )
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="spawn-before-max",
                    name="spawn_subagent",
                    arguments={"task": "等待后尝试一个工具"},
                )
            ],
            provider="fake",
        )

    fake.chat = _chat  # type: ignore[method-assign]
    parent_sid = engine.session.create()
    result = engine.run(parent_sid, "只允许一轮，因此 spawn 后 parent 将异常收束")
    assert result.truncated is True or "轮数" in result.final_answer

    # parent 已离开正常 loop；无论 child 此刻已进 LLM 还是尚未调度，release 后都不得执行动作。
    release_child.set()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with runner._children_guard:
            owned = [h for h in runner._handles.values() if h.parent_id == parent_sid]
            terminal = bool(owned) and all(h.state != "running" for h in owned)
        if terminal:
            break
        time.sleep(0.01)
    assert owned, "spawn 应留下可审计 handle"
    assert all(h.cancel_requested for h in owned)
    assert all(h.collected for h in owned), "异常 parent 退出即放弃 settlement obligation"
    assert all(h.state == "cancelled" for h in owned)
    assert not executed.is_set(), "parent 已异常退出后 child 不得继续执行新副作用"
