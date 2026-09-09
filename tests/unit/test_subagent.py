"""EVO 第五项: 递归子代理（参考 FrontisAI/OpenRSI 四算子 + 执行反馈）测试.

验证:
- 子代理成功执行并回传结果（独立会话隔离 + 真实执行）
- 深度超限拒绝（如实标注）
- 轮数截断标注
- 子代理继承父执行域，不因 child 身份维护静态工具白名单
- spawn_subagent 非阻塞 handle + subagent_result 终态回执
- 父会话上下文不被污染（子代理独立 session）
- P1-5(审计发现 #10): 子代理执行后会话 id 恢复为父会话（成功/异常路径都恢复）
"""

from __future__ import annotations

import re
import threading
from typing import Any, cast

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner


def _child_id_from_spawn(receipt) -> str:
    match = re.search(r"\bchild_id=(subagent_[0-9a-f]+)\b", receipt.content)
    assert match, receipt.content
    return match.group(1)


def _await_child(runner: SubAgentRunner, receipt, wait_seconds: float = 2.0):
    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    return SubAgentResultTool(runner).execute(
        child_id=_child_id_from_spawn(receipt), wait_seconds=wait_seconds
    )


def test_runner_success_executes_tool_and_returns(build_test_engine):
    """子代理: 一轮工具（read_file）后给出最终回答."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)

    # 子代理消息序列: ① 调 read_file → ② 无工具调用给出回答
    def seq(calls):
        # 第一个 LLM 调用: 声明 read_file
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "/nonexistent/x"})],
            provider="fake",
        )

    fake._responses = [
        seq,
        LLMResponse(content="子代理完成: 文件不存在", tool_calls=[], provider="fake"),
    ]

    result = runner.run(task="检查文件是否存在", depth=0)

    assert result.refused is False
    assert result.truncated is False
    assert "子代理完成" in result.final_answer
    assert result.rounds == 2
    assert result.tool_calls and result.tool_calls[0]["name"] == "read_file"
    assert result.tool_calls[0]["status"] in {"success", "failure"}  # 真实执行状态
    # 子代理会话已落盘（独立 session，glob 会话目录）
    import pathlib

    sub_files = list(pathlib.Path(engine.session._dir).glob("subagent_*.json"))
    assert len(sub_files) >= 1, sub_files


def test_runner_does_not_inject_last_round_forced_close(build_test_engine):
    """max_rounds 是资源边界，不得在倒数轮偷偷追加“必须收口”程序提示。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="execute_command", arguments={"command": "echo one"})
            ],
            provider="fake",
        ),
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="c2", name="execute_command", arguments={"command": "echo two"})
            ],
            provider="fake",
        ),
    ]

    result = runner.run(task="自行判断何时收口", depth=0)

    assert result.outcome == "truncated"
    assert len(fake.calls) == 2
    second_wire = fake.calls[1]["messages"]
    # 没有父级 steer 时，第二轮只应有初始 task user + 上一轮完整 tool 协议；
    # 不允许 max_rounds-1 再注入额外 user/system 收口命令。
    assert [m["role"] for m in second_wire] == ["user", "assistant", "tool"]
    assert all("必须给出最终回答" not in str(m.get("content") or "") for m in second_wire)


def test_acceptance_is_guidance_not_programmatic_early_termination(build_test_engine):
    """自然语言 acceptance 不可由程序猜测“已满足”并抢走模型最终裁决轮。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=3
    )
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="execute_command", arguments={"command": "echo ok"})
            ],
            provider="fake",
        ),
        LLMResponse(content="我检查过验收条件后决定完成", tool_calls=[], provider="fake"),
    ]

    result = runner.run(task="执行并判断验收", depth=0, acceptance=["命令成功"])

    assert result.outcome == "completed"
    assert result.rounds == 2
    assert len(fake.calls) == 2, "程序不得因工具 SUCCESS 猜测 acceptance 已满足而跳过模型最终裁决"
    assert result.final_answer == "我检查过验收条件后决定完成"


def test_runner_preserves_assistant_tool_declaration_before_receipt(build_test_engine):
    """子代理下一轮必须看到完整 assistant(tool_calls)→tool(result) 协议配对。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="sub-c1",
                    name="execute_command",
                    arguments={"command": "echo paired"},
                )
            ],
            provider="fake",
        ),
        LLMResponse(content="完成", tool_calls=[], provider="fake"),
    ]

    result = runner.run(task="执行一次 echo 后收口", depth=0)
    assert result.final_answer == "完成"
    second_wire = fake.calls[1]["messages"]
    assert [m["role"] for m in second_wire[-3:]] == ["user", "assistant", "tool"]
    decl = second_wire[-2]
    receipt = second_wire[-1]
    assert decl["tool_calls"][0]["id"] == "sub-c1"
    assert decl["tool_calls"][0]["function"]["name"] == "execute_command"
    assert receipt["tool_call_id"] == "sub-c1"
    assert "paired" in receipt["content"]


def test_llm_exception_does_not_create_orphan_tool_frame(build_test_engine):
    """LLM transport/provider 异常不是 tool result，下一轮 history 不得出现 orphan tool。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )

    def _boom(calls):
        raise RuntimeError("provider-down")

    fake._responses = [
        _boom,
        LLMResponse(content="恢复后完成", tool_calls=[], provider="fake"),
    ]
    result = runner.run(task="先失败一次再恢复", depth=0)
    assert result.outcome == "completed"
    assert len(fake.calls) == 2
    assert [m["role"] for m in fake.calls[1]["messages"]] == ["user"]


def test_terminal_assistant_is_persisted_in_child_session(build_test_engine):
    """父级拿到的 final_answer 必须同时存在于 child durable history。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    fake._responses = [LLMResponse(content="最终可交付答案", tool_calls=[], provider="fake")]
    result = runner.run(task="直接回答", depth=0)
    assert result.outcome == "completed"
    sub_files = list(engine.session._dir.glob("subagent_*.json"))
    assert len(sub_files) == 1
    child = engine.session.load(sub_files[0].stem)
    assert child.messages[-1].role == "assistant"
    assert child.messages[-1].content == "最终可交付答案"


def test_all_llm_failures_report_failed_not_truncated_or_success(build_test_engine):
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )

    def _boom(calls):
        raise RuntimeError("provider-down")

    fake._responses = [_boom, _boom]
    receipt = SpawnSubAgentTool(runner).execute(task="provider 故障")
    assert receipt.status.value == "success"
    assert "child_state=running" in receipt.content
    terminal = _await_child(runner, receipt)
    assert terminal.status.value == "failure"
    assert "child_outcome=failed" in terminal.content
    assert "连续调用失败" in terminal.content


def test_subagent_default_scope_is_full_registry_and_explicit_parent_scope_is_preserved(
    build_test_engine,
):
    """Child identity adds no tool penalty; explicit parent scope still cannot be expanded."""
    engine, fake = build_test_engine([])
    from llm_loop.core.run_context import current_tool_discovery_scope
    from llm_loop.tools.registry import GetToolSchemaTool

    engine.registry.register(GetToolSchemaTool(engine.registry))
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)

    class _OutsideTool:
        name = "outside_control_tool"
        description = "用于验证父执行域继承"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            return "outside"

    engine.registry.register(_OutsideTool())

    # No parent scope => complete registry, including the newly registered tool.
    fake._responses = [LLMResponse(content="完成", tool_calls=[], provider="fake")]
    result = runner.run(task="检查默认能力面", depth=0)
    assert result.outcome == "completed"
    projected = {t["function"]["name"] for t in fake.calls[-1]["tools"]}
    assert "outside_control_tool" in projected

    # Explicit parent scope is a real authorization boundary and must survive delegation.
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="schema-outside",
                    name="get_tool_schema",
                    arguments={"tool_name": "outside_control_tool"},
                )
            ],
            provider="fake",
        ),
        LLMResponse(content="完成", tool_calls=[], provider="fake"),
    ]
    token = current_tool_discovery_scope.set(frozenset({"get_tool_schema", "read_file"}))
    try:
        scoped = runner.run(task="检查显式父域", depth=0)
    finally:
        current_tool_discovery_scope.reset(token)
    assert scoped.outcome == "completed"
    scoped_names = {t["function"]["name"] for t in fake.calls[-2]["tools"]}
    assert scoped_names == {"get_tool_schema", "read_file"}
    receipt = next(m for m in fake.calls[-1]["messages"] if m["role"] == "tool")
    assert "当前执行域不可用" in receipt["content"]
    assert "outside_control_tool" in receipt["content"]


def test_runner_depth_limit_refused(build_test_engine):
    """深度超限: 如实拒绝，不执行."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_depth=2
    )
    result = runner.run(task="再拆一层", depth=2)
    assert result.refused is True
    assert "递归深度超限" in result.final_answer
    assert fake.calls == []  # 未发生任何 LLM 调用


def test_runner_max_iterations_truncated(build_test_engine):
    """轮数超限: 截断并如实标注."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    # 每轮都声明工具调用（永不收敛）→ 触发截断
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "/x"})],
            provider="fake",
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c2", name="read_file", arguments={"path": "/y"})],
            provider="fake",
        ),
    ]
    result = runner.run(task="死循环任务", depth=0)
    assert result.truncated is True
    assert result.outcome == "truncated"
    assert "轮数上限" in result.final_answer
    assert result.rounds == 2


def test_runner_uses_registry_tool_safety_without_child_whitelist(build_test_engine):
    """child 身份不再另设白名单；edit_file 仍完整经过 registry/tool 自身安全链。"""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="edit_file", arguments={"path": "/x", "content": "y"})
            ],
            provider="fake",
        ),
        LLMResponse(content="结束", tool_calls=[], provider="fake"),
    ]
    result = runner.run(task="尝试改文件", depth=0)
    assert result.tool_calls[0]["name"] == "edit_file"
    # child 身份不额外 block；真实安全/授权仍由 edit_file + registry 承担。
    assert result.tool_calls[0]["status"] != "blocked"
    assert result.truncated is False


def test_runner_recursive_spawn(build_test_engine):
    """递归委派走 nonblocking handle：子代理 spawn→await 孙代理→整合，depth 自动+1。"""
    engine, _fake = build_test_engine([])
    import threading

    class _ConcurrentFake:
        def __init__(self):
            self.calls: list[dict] = []
            self._guard = threading.Lock()

        def chat(self, messages, tools, **kwargs):
            del kwargs
            with self._guard:
                self.calls.append({"messages": messages, "tools": tools})
            joined = "\n".join(str(m.get("content", "")) for m in messages)
            if "孙子任务" in joined:
                return LLMResponse(content="孙代理完成", tool_calls=[], provider="fake")
            tool_receipts = [m for m in messages if m.get("role") == "tool"]
            if not tool_receipts:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="spawn-grand", name="spawn_subagent", arguments={"task": "孙子任务"}
                        )
                    ],
                    provider="fake",
                )
            last = str(tool_receipts[-1].get("content", ""))
            if "child_state=running" in last:
                child_id = re.search(r"child_id=(subagent_[0-9a-f]+)", last)
                assert child_id, last
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="await-grand",
                            name="subagent_result",
                            arguments={"child_id": child_id.group(1), "wait_seconds": 2},
                        )
                    ],
                    provider="fake",
                )
            assert "child_outcome=completed" in last, last
            return LLMResponse(content="子代理整合完成: 孙子已完成", tool_calls=[], provider="fake")

    llm = _ConcurrentFake()
    runner = SubAgentRunner(
        llm=cast(Any, llm), registry=engine.registry, session_store=engine.session, max_depth=3
    )
    from llm_loop.tools.builtin.agent_message import AgentMessageTool
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    engine.registry.add_session_cancel_hook(runner.cancel_parent)
    engine.registry.register(SpawnSubAgentTool(runner))
    engine.registry.register(AgentMessageTool(runner))
    engine.registry.register(SubAgentResultTool(runner))
    result = runner.run(task="父任务", depth=0)
    assert result.refused is False
    assert "子代理整合完成" in result.final_answer
    assert [x["name"] for x in result.tool_calls] == ["spawn_subagent", "subagent_result"]
    # 子代理 + 孙代理会话都落盘，且孙代理真实 depth=1。
    import pathlib

    sub_files = list(pathlib.Path(engine.session._dir).glob("subagent_*.json"))
    assert len(sub_files) >= 2, sub_files
    import json

    child_depths: list[int] = []
    for path in sub_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for message in payload.get("messages", []):
            md = message.get("metadata") or {}
            if md.get("injection_kind") == "subagent_task":
                child_depths.append(int(md.get("subagent_depth", -1)))
                break
    child_depths.sort()
    assert child_depths[:2] == [0, 1]


def test_spawn_depth_is_program_owned_even_if_model_forges_value():
    """模型传 depth=99/0 都不能改变真实层级；schema 也不暴露 depth。"""
    from llm_loop.subagent.runner import _CURRENT_SUBAGENT_DEPTH
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    seen: list[int] = []

    class _CaptureRunner:
        def start(self, **kwargs):
            seen.append(int(kwargs["depth"]))
            return {
                "accepted": True,
                "child_id": f"subagent_{len(seen):012x}",
                "state": "running",
                "depth": int(kwargs["depth"]),
                "detail": "ok",
            }

        def cancel_parent(self, session_id: str) -> int:
            return 0

    tool = SpawnSubAgentTool(_CaptureRunner())
    assert "depth" not in tool.parameters["properties"]
    tool.execute(task="top", depth=99)
    tok = _CURRENT_SUBAGENT_DEPTH.set(1)
    try:
        tool.execute(task="nested", depth=0)
    finally:
        _CURRENT_SUBAGENT_DEPTH.reset(tok)
    assert seen == [0, 2]


def test_spawn_subagent_tool_receipt(build_test_engine):
    """spawn_subagent 只确认 accepted/running；终态由 subagent_result 独立回收。"""
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_depth=3
    )
    tool = SpawnSubAgentTool(runner)
    fake._responses = [LLMResponse(content="完成: 42", tool_calls=[], provider="fake")]
    result = tool.execute(task="计算答案")
    assert result.status.value == "success"
    assert "child_state=running" in result.content
    assert "本回执不是任务结算" in result.content
    assert "depth=0" in result.content
    terminal = _await_child(runner, result)
    assert terminal.status.value == "success"
    assert "child_outcome=completed" in terminal.content
    assert "rounds=1" in terminal.content
    assert "[子代理回答]" in terminal.content
    assert "完成: 42" in terminal.content


def test_spawn_truncated_is_failure_not_false_success(build_test_engine):
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=1
    )
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "/x"})],
            provider="fake",
        )
    ]
    started = SpawnSubAgentTool(runner).execute(task="无法在一轮内收口")
    assert started.status.value == "success"
    result = _await_child(runner, started)
    assert result.status.value == "failure"
    assert "child_outcome=truncated" in result.content


def test_spawn_subagent_tool_missing_task(build_test_engine):
    """缺 task 参数: 如实失败."""
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    tool = SpawnSubAgentTool(runner)
    result = tool.execute()
    assert result.status.value == "failure"
    assert "task" in result.content


def test_runner_restores_parent_session_id(build_test_engine):
    """P1-5(审计发现 #10): 子代理执行后会话 id 恢复为父会话（不再串台）.

    子代理执行期间有效 registry._session_id 由 ContextVar 指向子会话；共享显式
    fallback 保持父会话，不再被并发 child 临时改写。退出后 ContextVar 恢复父会话。
    """
    from llm_loop.core.run_context import current_session_id

    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)

    # 探针工具（在子代理受限工具集内，且测试引擎未注册 web_search）:
    # 记录子代理执行瞬间的会话（contextvar 优先值 + 显式回退字段）
    captured: list[tuple[str, str]] = []

    class _ProbeTool:
        name = "web_search"
        description = "探针（子代理会话断言）"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            captured.append((engine.registry._session_id, engine.registry._session_id_explicit))
            return "探针结果"

    engine.registry.register(_ProbeTool())
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="web_search", arguments={})],
            provider="fake",
        ),
        LLMResponse(content="子代理完成", tool_calls=[], provider="fake"),
    ]

    parent_sid = "parent_test_session"
    engine.registry.set_session_id(parent_sid)
    prev_ctx = current_session_id.get()
    current_session_id.set(parent_sid)  # 模拟 engine.run 包装层（值快照 set，与引擎一致）
    try:
        result = runner.run(task="探针任务", depth=0)
        assert result.truncated is False
        # 执行期间: 有效会话来自 child ContextVar；共享 fallback 保持 parent。
        assert captured, "探针工具应被执行"
        assert captured[0][0].startswith("subagent_"), captured
        assert captured[0][1] == parent_sid, captured
        # 执行结束: 恢复父会话（显式字段 + contextvar + 属性读取三者一致）
        assert engine.registry._session_id_explicit == parent_sid
        assert current_session_id.get() == parent_sid
        assert engine.registry._session_id == parent_sid
    finally:
        current_session_id.set(prev_ctx)


def test_parent_stop_cancels_child_before_post_llm_tool_execution(build_test_engine):
    """spawn 已返回 handle 后父 Stop 仍取消 child；LLM 回来后不得执行新副作用。"""

    from llm_loop.core.run_context import current_session_id
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    engine, fake = build_test_engine([])
    tool = engine.registry.get("spawn_subagent")
    assert isinstance(tool, SpawnSubAgentTool)

    entered = threading.Event()
    release = threading.Event()
    executed = threading.Event()

    class _ProbeTool:
        name = "web_search"
        description = "取消后不得执行的探针工具"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            executed.set()
            return "should-not-run"

    engine.registry.register(_ProbeTool())

    def _blocking_chat(messages, tools, **kwargs):
        entered.set()
        assert release.wait(2.0)
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id="late", name="web_search", arguments={})],
            provider="fake",
        )

    fake.chat = _blocking_chat  # type: ignore[method-assign]
    parent_sid = "parent-cancel-subagent"
    tok = current_session_id.set(parent_sid)
    try:
        started = engine.registry.execute(
            ToolCall(
                id="spawn-cancel",
                name="spawn_subagent",
                arguments={"task": "等待后再调用工具"},
            )
        )
    finally:
        current_session_id.reset(tok)
    assert started.status.value == "success"
    child_id = _child_id_from_spawn(started)
    assert entered.wait(2.0)
    # 关键：spawn future 此时已经结束，仍走真实 Registry Stop 入口取消 background child。
    assert engine.registry.cancel_session(parent_sid) >= 1
    release.set()
    assert not executed.is_set(), "Stop 后 child 不得执行 LLM 刚返回的动作"
    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    tok = current_session_id.set(parent_sid)
    try:
        terminal = SubAgentResultTool(tool._runner).execute(child_id=child_id, wait_seconds=2)
    finally:
        current_session_id.reset(tok)
    assert terminal.status.value == "failure"
    assert "child_outcome=cancelled" in terminal.content


def test_background_handle_hard_cap_refuses_only_new_resource(build_test_engine):
    """running handle 达硬上限时拒绝新 background resource，不淘汰活跃 child。"""
    engine, fake = build_test_engine([])
    runner = engine.registry.get("spawn_subagent")._runner
    runner._max_handles = 1
    entered = threading.Event()
    release = threading.Event()

    def _chat(messages, tools, **kwargs):
        del messages, tools, kwargs
        entered.set()
        assert release.wait(2.0)
        return LLMResponse(content="done", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set("parent-cap")
    try:
        first = runner.start(task="占住唯一 background slot")
        assert first["accepted"] is True
        assert entered.wait(2.0)
        second = runner.start(task="应被资源边界拒绝")
        assert second["accepted"] is False
        assert second["state"] == "refused"
        assert "资源已达硬上限" in str(second["detail"])
        assert runner.active_children("parent-cap") == [first["child_id"]]
        runner.cancel_parent("parent-cap")
    finally:
        current_session_id.reset(tok)
        release.set()


def test_runner_restores_parent_session_on_exception(build_test_engine):
    """P1-5(审计发现 #10): 子代理内部异常时同样恢复父会话（finally 兜底）."""
    from llm_loop.core.run_context import current_session_id

    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    parent_sid = "parent_test_session"
    engine.registry.set_session_id(parent_sid)
    prev_ctx = current_session_id.get()
    current_session_id.set(parent_sid)

    def _boom(*args, **kwargs):
        raise RuntimeError("子代理内部异常（测试注入）")

    runner._execute_subagent = _boom  # type: ignore[method-assign] — 注入异常路径
    try:
        with pytest.raises(RuntimeError):
            runner.run(task="探针任务", depth=0)
        # 异常穿透后父会话仍被恢复（try/finally 覆盖所有返回路径）
        assert engine.registry._session_id_explicit == parent_sid
        assert current_session_id.get() == parent_sid
    finally:
        current_session_id.set(prev_ctx)


def test_runner_acceptance_injected(build_test_engine):
    """2026-08-18: acceptance 验收清单注入子代理系统提示（对齐 dsh_task 协议 v2）."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)

    def seq(calls):
        # 记录收到的消息，断言验收清单已注入
        import json

        msgs = (
            json.dumps([m.to_llm_dict() for m in calls], ensure_ascii=False)
            if hasattr(calls[0], "to_llm_dict")
            else str(calls)
        )
        captured.append(msgs)
        return LLMResponse(content="完成", tool_calls=[], provider="fake")

    captured: list[str] = []
    fake._responses = [seq]
    result = runner.run(
        task="实现一个函数",
        depth=0,
        acceptance=["函数签名正确", "有 docstring", "单测通过"],
    )
    assert result.refused is False
    joined = " ".join(captured)
    assert "父代理委派任务·非真人新授权" in joined
    assert "验收条件（供交付核对）" in joined
    assert "1. 函数签名正确" in joined
    assert "2. 有 docstring" in joined
    assert "3. 单测通过" in joined


def test_spawn_tool_acceptance_param(build_test_engine):
    """spawn_subagent acceptance 透传到 background child，终态经 result 回收。"""
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    fake._responses = [LLMResponse(content="按验收完成", tool_calls=[], provider="fake")]
    tool = engine.registry.get("spawn_subagent")
    assert isinstance(tool, SpawnSubAgentTool), type(tool)
    r = tool.execute(task="实现函数", acceptance=["签名正确", "有 docstring"])
    assert r.status.name == "SUCCESS"
    terminal = _await_child(tool._runner, r)
    assert terminal.status.name == "SUCCESS"
    assert "按验收完成" in terminal.content
    child_id = _child_id_from_spawn(r)
    child = engine.session.load(child_id)
    assert "1. 签名正确" in child.messages[0].content
    assert "2. 有 docstring" in child.messages[0].content


def test_spawn_subagent_not_falsely_timed_out_by_atomic_registry_limit():
    """nonblocking start 使用自身短启动边界，不继承 registry 的原子 20ms 超时。"""
    import time

    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
    from llm_loop.tools.registry import ToolRegistry

    class _SlowRunner:
        def start(self, **kwargs):
            time.sleep(0.08)
            return {
                "accepted": True,
                "child_id": "subagent_000000000001",
                "state": "running",
                "depth": int(kwargs["depth"]),
                "detail": "started",
            }

    reg = ToolRegistry(tool_timeout_s=0.02)
    reg.register(SpawnSubAgentTool(_SlowRunner()))
    result = reg.execute(
        ToolCall(id="spawn-1", name="spawn_subagent", arguments={"task": "慢子任务"})
    )
    assert result.status.value == "success"
    assert "child_state=running" in result.content


def test_subagent_parent_id_mounted(build_test_engine, monkeypatch):
    """2026-08-18 会话树修复（c09dc9e）: 子代理创建时挂载父会话 parent_id."""
    from llm_loop.core.run_context import current_session_id as _csid

    engine, fake = build_test_engine([])
    fake._responses = [LLMResponse(content="完成", tool_calls=[], provider="fake")]
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    # 模拟父会话 run 上下文（engine.run_stream 设置 current_session_id）
    parent_sid = "parent-session-123"
    tok = _csid.set(parent_sid)
    try:
        result = runner.run(task="测试", depth=0)
        assert result.refused is False
    finally:
        _csid.reset(tok)
    # 验证子代理会话 parent_id = 父会话
    import pathlib

    sub_files = sorted(pathlib.Path(engine.session._dir).glob("subagent_*.json"))
    assert sub_files, "子代理会话应已落盘"
    latest = sub_files[-1]
    import json as _json

    sess_json = _json.loads(latest.read_text(encoding="utf-8"))
    assert sess_json.get("parent_id") == parent_sid, sess_json.get("parent_id")


def test_subagent_tools_have_type_field(build_test_engine):
    """2026-08-18 修复: 子代理 tools 参数必须含 type='function'（裸 schema → DeepSeek 400）."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    fake._responses = [LLMResponse(content="完成", tool_calls=[], provider="fake")]
    result = runner.run(task="测试", depth=0)
    assert result.refused is False
    assert fake.calls, "子代理应有 LLM 调用"
    # 断言所有 tools 都带 type='function' + function 包装
    for call in fake.calls:
        tools = call.get("tools") or []
        assert tools, "tools 不应为空"
        for t in tools:
            assert t.get("type") == "function", f"缺 type=function: {t}"
            assert "function" in t and "name" in t["function"], f"缺 function.name: {t}"
