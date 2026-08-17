"""EVO 第五项: 递归子代理（参考 FrontisAI/OpenRSI 四算子 + 执行反馈）测试.

验证:
- 子代理成功执行并回传结果（独立会话隔离 + 真实执行）
- 深度超限拒绝（如实标注）
- 轮数截断标注
- 子代理工具受限（edit_file 被拒）
- spawn_subagent 工具回执格式（五态 + 轨迹摘要 + 深度标注）
- 父会话上下文不被污染（子代理独立 session）
- P1-5(审计发现 #10): 子代理执行后会话 id 恢复为父会话（成功/异常路径都恢复）
"""
from __future__ import annotations

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner


def test_runner_success_executes_tool_and_returns(build_test_engine):
    """子代理: 一轮工具（read_file）后给出最终回答."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )

    # 子代理消息序列: ① 调 read_file → ② 无工具调用给出回答
    def seq(calls):
        # 第一个 LLM 调用: 声明 read_file
        return LLMResponse(
            content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "/nonexistent/x"})], provider="fake"
        )
    fake._responses = [seq, LLMResponse(content="子代理完成: 文件不存在", tool_calls=[], provider="fake")]

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
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "/x"})], provider="fake"),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="read_file", arguments={"path": "/y"})], provider="fake"),
    ]
    result = runner.run(task="死循环任务", depth=0)
    assert result.truncated is True
    assert "轮数上限" in result.final_answer
    assert result.rounds == 2


def test_runner_tool_restricted(build_test_engine):
    """受限工具集: edit_file 已纳入白名单（审查 P0-2 修复）→ 走 registry 执行而非 blocked. """
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_iterations=2
    )
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="edit_file", arguments={"path": "/x", "content": "y"})],
            provider="fake",
        ),
        LLMResponse(content="结束", tool_calls=[], provider="fake"),
    ]
    result = runner.run(task="尝试改文件", depth=0)
    assert result.tool_calls[0]["name"] == "edit_file"
    # 修复后: edit_file 在白名单内 → 不再 blocked（安全链由 edit_file 自身 symlink 防护/FileBaseline 承担）
    assert result.tool_calls[0]["status"] != "blocked"
    assert result.truncated is False


def test_runner_recursive_spawn(build_test_engine):
    """递归委派: 子代理内可再 spawn_subagent（depth 自增），孙代理执行后回传."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_depth=3
    )
    # 子代理第一轮: spawn_subagent（深度 1 → 孙代理）; 孙代理一轮后回答; 子代理最终回答
    def sub_spawn(calls):
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="spawn_subagent", arguments={"task": "孙子任务", "depth": 1})],
            provider="fake",
        )

    def grandson_tool(calls):
        return LLMResponse(
            content="", tool_calls=[ToolCall(id="c2", name="read_file", arguments={"path": "/nonexistent"})], provider="fake"
        )

    fake._responses = [
        sub_spawn,  # 子代理: 委派孙代理
        grandson_tool,  # 孙代理: 调 read_file
        LLMResponse(content="孙代理完成", tool_calls=[], provider="fake"),  # 孙代理回答
        LLMResponse(content="子代理整合完成: 孙子已完成", tool_calls=[], provider="fake"),  # 子代理回答
    ]
    result = runner.run(task="父任务", depth=0)
    assert result.refused is False
    assert "子代理整合完成" in result.final_answer
    # 子代理 + 孙代理会话都落盘
    import pathlib

    sub_files = list(pathlib.Path(engine.session._dir).glob("subagent_*.json"))
    assert len(sub_files) >= 2, sub_files


def test_spawn_subagent_tool_receipt(build_test_engine):
    """spawn_subagent 工具回执: 含状态/深度/轮数/轨迹/回答."""
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_depth=3
    )
    tool = SpawnSubAgentTool(runner)
    fake._responses = [LLMResponse(content="完成: 42", tool_calls=[], provider="fake")]
    result = tool.execute(task="计算答案")
    assert result.status.value == "success"
    assert "子代理完成" in result.content
    assert "depth=0" in result.content
    assert "rounds=1" in result.content
    assert "子代理回答" in result.content
    assert "完成: 42" in result.content


def test_spawn_subagent_tool_missing_task(build_test_engine):
    """缺 task 参数: 如实失败."""
    engine, fake = build_test_engine([])
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    tool = SpawnSubAgentTool(runner)
    result = tool.execute()
    assert result.status.value == "failure"
    assert "task" in result.content


def test_runner_restores_parent_session_id(build_test_engine):
    """P1-5(审计发现 #10): 子代理执行后会话 id 恢复为父会话（不再串台）.

    子代理执行期间注册表会话为子会话（change_log/超长归档正确归属子会话）；
    执行结束恢复父会话——父级后续工具结果的归档/变更日志不得归错到子会话。
    contextvar（P0-5 优先）与显式回退字段两者都要恢复。
    """
    from llm_loop.core.run_context import current_session_id

    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )

    # 探针工具（在子代理受限工具集内，且测试引擎未注册 web_search）:
    # 记录子代理执行瞬间的会话（contextvar 优先值 + 显式回退字段）
    captured: list[tuple[str, str]] = []

    class _ProbeTool:
        name = "web_search"
        description = "探针（子代理会话断言）"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            captured.append(
                (engine.registry._session_id, engine.registry._session_id_explicit)
            )
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
        # 执行期间: 会话为子会话（contextvar 优先 + 显式字段都指向子会话）
        assert captured, "探针工具应被执行"
        assert captured[0][0].startswith("subagent_"), captured
        assert captured[0][1].startswith("subagent_"), captured
        # 执行结束: 恢复父会话（显式字段 + contextvar + 属性读取三者一致）
        assert engine.registry._session_id_explicit == parent_sid
        assert current_session_id.get() == parent_sid
        assert engine.registry._session_id == parent_sid
    finally:
        current_session_id.set(prev_ctx)


def test_runner_restores_parent_session_on_exception(build_test_engine):
    """P1-5(审计发现 #10): 子代理内部异常时同样恢复父会话（finally 兜底）."""
    from llm_loop.core.run_context import current_session_id

    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
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
