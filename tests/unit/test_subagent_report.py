"""Agent Communication Contract：直接相邻投递、step-boundary steer 与结果查询。"""

from __future__ import annotations

import re
import threading

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.agent_message import AgentMessageTool
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool


def _fixture_runner(engine) -> SubAgentRunner:
    return engine.registry.get("spawn_subagent")._runner


def test_agent_message_replaces_report_on_public_schema(build_test_engine):
    """公共通信只留 agent_message；异步结算由独立 subagent_result handle 工具承担。"""
    engine, _fake = build_test_engine([])
    assert "agent_message" in engine.registry.names()
    assert "subagent_result" in engine.registry.names()
    assert "subagent_report" not in engine.registry.names()
    schema_names = {x["name"] for x in engine.registry.schemas(lazy=False)}
    assert "agent_message" in schema_names
    assert "subagent_result" in schema_names
    assert "subagent_report" not in schema_names
    tool = engine.registry.get("agent_message")
    assert "sender" not in tool.parameters["properties"]


def test_nonblocking_spawn_parent_can_steer_then_await(build_test_engine):
    """公共链机械闭环：spawn 返回→parent继续→steer→child boundary吸收→await result。"""
    engine, fake = build_test_engine([])
    entered = threading.Event()
    release = threading.Event()
    child_calls: list[list[dict]] = []

    def _chat(messages, tools, **kwargs):
        del tools, kwargs
        child_calls.append(messages)
        if len(child_calls) == 1:
            entered.set()
            assert release.wait(2.0)
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="r1", name="read_file", arguments={"path": "/missing"})],
                provider="fake",
            )
        assert "优先查 A，不要查 B" in str(messages[-1].get("content", ""))
        return LLMResponse(content="steered-done", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-public-async-steer"
    tok = current_session_id.set(parent_sid)
    try:
        started = engine.registry.execute(
            ToolCall(
                id="spawn-async",
                name="spawn_subagent",
                arguments={"task": "先读取一次，再根据父级新消息收口"},
            )
        )
    finally:
        current_session_id.reset(tok)
    assert started.status.name == "SUCCESS"
    match = re.search(r"child_id=(subagent_[0-9a-f]+)", started.content)
    assert match, started.content
    child_id = match.group(1)
    assert entered.wait(2.0), "spawn 必须已返回但 child 仍可在后台运行"

    tok = current_session_id.set(parent_sid)
    try:
        sent = engine.registry.execute(
            ToolCall(
                id="steer-public",
                name="agent_message",
                arguments={"target_id": child_id, "content": "优先查 A，不要查 B"},
            )
        )
        assert sent.status.name == "SUCCESS"
        release.set()
        terminal = engine.registry.execute(
            ToolCall(
                id="await-public",
                name="subagent_result",
                arguments={"child_id": child_id, "wait_seconds": 2},
            )
        )
    finally:
        current_session_id.reset(tok)

    assert terminal.status.name == "SUCCESS"
    assert "child_outcome=completed" in terminal.content
    assert "steered-done" in terminal.content
    assert len(child_calls) == 2
    roles = [m["role"] for m in child_calls[1][-4:]]
    assert roles[-3:] == ["assistant", "tool", "user"], roles


def test_subagent_result_wait_wakes_on_child_report_before_terminal(build_test_engine):
    """await 等的是 activity：child report 一到就唤醒 parent，不必睡到最终结算。"""
    engine, fake = build_test_engine([])
    second_entered = threading.Event()
    release_final = threading.Event()
    call_no = 0

    def _chat(messages, tools, **kwargs):
        nonlocal call_no
        del messages, tools, kwargs
        call_no += 1
        if call_no == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="report-1",
                        name="agent_message",
                        arguments={"target_id": "parent", "content": "checkpoint-A"},
                    )
                ],
                provider="fake",
            )
        second_entered.set()
        assert release_final.wait(2.0)
        return LLMResponse(content="report-then-done", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-report-wakeup"
    tok = current_session_id.set(parent_sid)
    try:
        started = engine.registry.execute(
            ToolCall(id="spawn-report", name="spawn_subagent", arguments={"task": "先报告再等待"})
        )
    finally:
        current_session_id.reset(tok)
    match = re.search(r"child_id=(subagent_[0-9a-f]+)", started.content)
    assert match is not None, started.content
    child_id = match.group(1)
    assert second_entered.wait(2.0), "child 应已发出 report 并进入下一轮"

    tok = current_session_id.set(parent_sid)
    try:
        running = engine.registry.execute(
            ToolCall(
                id="wait-report",
                name="subagent_result",
                arguments={"child_id": child_id, "wait_seconds": 2},
            )
        )
    finally:
        current_session_id.reset(tok)
    assert running.status.name == "SUCCESS"
    assert "child_state=running" in running.content
    assert "checkpoint-A" in running.content
    assert not release_final.is_set(), "result 必须在 terminal 前因 report activity 提前返回"

    release_final.set()
    tok = current_session_id.set(parent_sid)
    try:
        terminal = engine.registry.execute(
            ToolCall(
                id="wait-terminal",
                name="subagent_result",
                arguments={"child_id": child_id, "wait_seconds": 2},
            )
        )
    finally:
        current_session_id.reset(tok)
    assert terminal.status.name == "SUCCESS"
    assert "child_outcome=completed" in terminal.content
    assert "report-then-done" in terminal.content


def test_subagent_result_rejects_non_parent_reader(build_test_engine):
    """handle 不是全局可读 id；只有直接 parent 能查询 child 运行/终态。"""
    engine, fake = build_test_engine([])
    entered = threading.Event()
    release = threading.Event()

    def _chat(messages, tools, **kwargs):
        del messages, tools, kwargs
        entered.set()
        assert release.wait(2.0)
        return LLMResponse(content="done", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-handle-owner"
    tok = current_session_id.set(parent_sid)
    try:
        started = engine.registry.execute(
            ToolCall(id="spawn-owned", name="spawn_subagent", arguments={"task": "等待"})
        )
    finally:
        current_session_id.reset(tok)
    match = re.search(r"child_id=(subagent_[0-9a-f]+)", started.content)
    assert match is not None, started.content
    child_id = match.group(1)
    assert entered.wait(2.0)

    tok = current_session_id.set("sibling-not-owner")
    try:
        denied = engine.registry.execute(
            ToolCall(
                id="read-foreign",
                name="subagent_result",
                arguments={"child_id": child_id, "wait_seconds": 0},
            )
        )
    finally:
        current_session_id.reset(tok)
    assert denied.status.name == "FAILURE"
    assert "直接 parent" in denied.content

    release.set()
    tok = current_session_id.set(parent_sid)
    try:
        terminal = engine.registry.execute(
            ToolCall(
                id="read-owned",
                name="subagent_result",
                arguments={"child_id": child_id, "wait_seconds": 2},
            )
        )
    finally:
        current_session_id.reset(tok)
    assert terminal.status.name == "SUCCESS"


def test_child_agent_message_to_parent_is_collected(build_test_engine):
    """child→parent 只写 runner-owned report；sender 服务端推导，不复制到 K4 interop。"""
    engine, fake = build_test_engine([])
    runner = _fixture_runner(engine)
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="m1",
                    name="agent_message",
                    arguments={"target_id": "parent", "content": "已定位根因: 缓存键未失效"},
                )
            ],
            provider="fake",
        ),
        LLMResponse(content="子代理完成", tool_calls=[], provider="fake"),
    ]
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set("parent-agent-message")
    try:
        result = runner.run(task="排查缓存问题", depth=0)
    finally:
        current_session_id.reset(tok)

    assert result.reports == ["已定位根因: 缓存键未失效"]
    assert result.tool_calls[0] == {"name": "agent_message", "status": "success"}


def test_parent_message_arrives_only_after_tool_protocol_boundary(build_test_engine):
    """parent steer 不插断 assistant(tool_calls)->tool；下一 child turn 才看到消息。"""
    engine, fake = build_test_engine([])
    runner = _fixture_runner(engine)
    entered = threading.Event()
    release = threading.Event()
    calls: list[list[dict]] = []

    def _chat(messages, tools, **kwargs):
        del tools, kwargs
        calls.append(messages)
        if len(calls) == 1:
            entered.set()
            assert release.wait(2.0)
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="read-1", name="read_file", arguments={"path": "/missing"})
                ],
                provider="fake",
            )
        return LLMResponse(content="已按父消息调整并完成", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-steer"
    box: list = []

    def _run_child():
        tok = current_session_id.set(parent_sid)
        try:
            box.append(runner.run(task="先检查文件", depth=0))
        finally:
            current_session_id.reset(tok)

    worker = threading.Thread(target=_run_child)
    worker.start()
    assert entered.wait(2.0)
    child_sid = runner.active_children(parent_sid)[0]
    tok = current_session_id.set(parent_sid)
    try:
        sent = engine.registry.execute(
            ToolCall(
                id="steer-1",
                name="agent_message",
                arguments={
                    "target_id": child_sid,
                    "content": "先集中确认 A，不要扩散到 B",
                    "sender_id": "forged-by-model",
                },
            )
        )
    finally:
        current_session_id.reset(tok)
    assert sent.status.name == "SUCCESS"
    release.set()
    worker.join(timeout=3.0)
    assert not worker.is_alive()
    assert box and box[0].final_answer == "已按父消息调整并完成"
    second = calls[1]
    roles = [m["role"] for m in second[-4:]]
    assert roles[-3:] == ["assistant", "tool", "user"], roles
    assert second[-1]["content"].startswith("【父代理委派消息·非真人新授权】")
    assert f"direct-parent {parent_sid}" in second[-1]["content"]
    assert "forged-by-model" not in second[-1]["content"]
    assert "先集中确认 A" in second[-1]["content"]


def test_multiple_parent_messages_are_one_nonhuman_delegated_frame(build_test_engine):
    """同一 step 前多条 steer 保序聚合为一个 user wire，且永远不冒充真人新授权。"""
    engine, _fake = build_test_engine([])
    runner = _fixture_runner(engine)
    from llm_loop.core.reference_injection import is_human_user_message
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-aggregate"
    child_sid, _cancel, sess = runner._reserve_child(parent_sid)
    tok = current_session_id.set(parent_sid)
    try:
        assert runner.send_current_message(child_sid, "第一条：先查 A")[0]
        assert runner.send_current_message(child_sid, "第二条：再核 B")[0]
        assert runner._inject_pending_agent_messages(sess, child_sid) == 2
    finally:
        current_session_id.reset(tok)
        runner._finalize_child(child_sid, parent_sid, None)

    frames = [m for m in sess.messages if m.role == "user"]
    assert len(frames) == 1
    frame = frames[0]
    assert frame.content.startswith("【父代理委派消息·非真人新授权】")
    assert frame.content.index("第一条：先查 A") < frame.content.index("第二条：再核 B")
    assert frame.metadata.get("program_origin") is True
    assert is_human_user_message(frame) is False


def test_agent_message_rejects_oversized_content(build_test_engine):
    engine, _fake = build_test_engine([])
    runner = _fixture_runner(engine)
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-message-bound"
    child_sid, _cancel, _sess = runner._reserve_child(parent_sid)
    tok = current_session_id.set(parent_sid)
    try:
        result = AgentMessageTool(runner).execute(target_id=child_sid, content="x" * 4001)
    finally:
        current_session_id.reset(tok)
        runner._finalize_child(child_sid, parent_sid, None)
    assert result.status.name == "FAILURE"
    assert "4000" in result.content


def test_parent_message_reopens_stale_no_tool_final(build_test_engine):
    """steer 在 LLM 生成 final 期间到达时，旧 final 不得被直接 settlement。"""
    engine, fake = build_test_engine([])
    runner = _fixture_runner(engine)
    entered = threading.Event()
    release = threading.Event()
    calls: list[list[dict]] = []

    def _chat(messages, tools, **kwargs):
        del tools, kwargs
        calls.append(messages)
        if len(calls) == 1:
            entered.set()
            assert release.wait(2.0)
            return LLMResponse(content="旧信息下准备结束", tool_calls=[], provider="fake")
        return LLMResponse(content="已吸收父级纠偏后完成", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-reopen-final"
    box: list = []

    def _run_child():
        tok = current_session_id.set(parent_sid)
        try:
            box.append(runner.run(task="先给初判", depth=0))
        finally:
            current_session_id.reset(tok)

    worker = threading.Thread(target=_run_child)
    worker.start()
    assert entered.wait(2.0)
    child_sid = runner.active_children(parent_sid)[0]
    tok = current_session_id.set(parent_sid)
    try:
        sent = AgentMessageTool(runner).execute(
            target_id=child_sid,
            content="先不要收口，补查 A 证据",
        )
    finally:
        current_session_id.reset(tok)
    assert sent.status.name == "SUCCESS"
    release.set()
    worker.join(timeout=3.0)
    assert not worker.is_alive()
    assert box and box[0].final_answer == "已吸收父级纠偏后完成"
    assert len(calls) == 2
    second = calls[1]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["content"] == "旧信息下准备结束"
    assert second[-1]["role"] == "user"
    assert "先不要收口" in second[-1]["content"]


def test_agent_message_rejects_non_adjacent_sender(build_test_engine):
    """兄弟/陌生 sender 不能给 active child 发消息；授权来自拓扑而非目标 id 猜测。"""
    engine, fake = build_test_engine([])
    runner = _fixture_runner(engine)
    entered = threading.Event()
    release = threading.Event()

    def _chat(messages, tools, **kwargs):
        del messages, tools, kwargs
        entered.set()
        assert release.wait(2.0)
        return LLMResponse(content="完成", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    from llm_loop.core.run_context import current_session_id

    parent_sid = "parent-auth"
    worker = threading.Thread(
        target=lambda: (
            current_session_id.set(parent_sid),
            runner.run(task="等待", depth=0),
        )
    )
    worker.start()
    assert entered.wait(2.0)
    child_sid = runner.active_children(parent_sid)[0]
    tok = current_session_id.set("not-the-parent")
    try:
        denied = AgentMessageTool(runner).execute(target_id=child_sid, content="越权消息")
    finally:
        current_session_id.reset(tok)
    assert denied.status.name == "FAILURE"
    assert "相邻边" in denied.content
    release.set()
    worker.join(timeout=3.0)


# ── DSH 借鉴 022-A: fork 继承（父会话切片注入）──
def test_inherit_injects_parent_context(build_test_engine, tmp_path, monkeypatch):
    """inherit=True: 父会话最近消息切片注入子代理 context."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    # 造父会话: 2 条消息（用户 + 助手）
    parent_sid = "parent-fork-test"
    psess = engine.session.load(parent_sid)
    from llm_loop.core.message import Message, MessageSource

    psess.messages.append(
        Message(role="user", content="用户原始问题: 如何优化缓存", source=MessageSource.USER)
    )
    psess.messages.append(
        Message(role="assistant", content="初步分析: 命中率低", source=MessageSource.SYSTEM)
    )
    engine.session.save(psess)
    # current_session_id 指向父会话（模拟主循环中）
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set(parent_sid)
    try:
        fake._responses = [LLMResponse(content="子代理完成", tool_calls=[], provider="fake")]
        result = runner.run(task="分析缓存问题", depth=0, inherit=True)
    finally:
        current_session_id.reset(tok)

    assert result.truncated is False
    # 子代理 LLM 收到的首条 user 消息应含继承切片
    assert fake.calls  # 至少一次调用
    # 从 fake 捕获的消息断言（FakeLLM.calls 结构见 test_subagent.py）
    first_msgs = fake.calls[0]["messages"]
    joined = " ".join(str(m) for m in first_msgs)
    assert "fork 继承" in joined or "父会话最近上下文" in joined
    assert "用户原始问题" in joined and "初步分析" in joined


def test_inherit_false_no_parent_context(build_test_engine, tmp_path, monkeypatch):
    """inherit 默认 False: 不注入父会话（零回归）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    parent_sid = "parent-noinherit"
    psess = engine.session.load(parent_sid)
    from llm_loop.core.message import Message, MessageSource

    psess.messages.append(
        Message(role="user", content="不应继承的父消息", source=MessageSource.USER)
    )
    engine.session.save(psess)
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set(parent_sid)
    try:
        fake._responses = [LLMResponse(content="子代理完成", tool_calls=[], provider="fake")]
        runner.run(task="独立任务", depth=0)  # 不传 inherit
    finally:
        current_session_id.reset(tok)

    joined = " ".join(str(m) for m in fake.calls[0]["messages"])
    assert "不应继承的父消息" not in joined


def test_inherit_fail_open_no_parent_session(build_test_engine, tmp_path, monkeypatch):
    """inherit=True 但无父会话: fail-open 不阻断，子代理正常执行."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set("ghost-session-404")
    try:
        fake._responses = [LLMResponse(content="子代理完成", tool_calls=[], provider="fake")]
        result = runner.run(task="无父会话任务", depth=0, inherit=True)
    finally:
        current_session_id.reset(tok)
    assert result.truncated is False
    assert "子代理完成" in result.final_answer


def test_spawn_tool_inherit_param(build_test_engine, tmp_path, monkeypatch):
    """spawn_subagent(inherit=True) 参数透传 + 回执成功."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(llm=fake, registry=engine.registry, session_store=engine.session)
    parent_sid = "parent-spawn"
    psess = engine.session.load(parent_sid)
    from llm_loop.core.message import Message, MessageSource

    psess.messages.append(
        Message(role="user", content="父上下文要点XYZ", source=MessageSource.USER)
    )
    engine.session.save(psess)
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set(parent_sid)
    try:
        fake._responses = [LLMResponse(content="子代理完成", tool_calls=[], provider="fake")]
        tool = SpawnSubAgentTool(runner)
        r = tool.execute(task="fork 任务", inherit=True)
        assert r.status.name == "SUCCESS", r.content
        # spawn is nonblocking; direct parent waits through the actual handle.
        import re

        from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

        match = re.search(r"child_id=(subagent_[0-9a-f]+)", r.content)
        assert match, r.content
        terminal = SubAgentResultTool(runner).execute(child_id=match.group(1), wait_seconds=2)
        assert terminal.status.name == "SUCCESS"
    finally:
        current_session_id.reset(tok)
    joined = " ".join(str(m) for m in fake.calls[0]["messages"])
    assert "父上下文要点XYZ" in joined


def test_inherit_exposes_exact_parent_context_artifact_without_private_reasoning(
    build_test_engine, tmp_path
) -> None:
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.run_context import current_session_id, current_workspace_root
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.builtin.read_file import ReadFileTool
    from llm_loop.workspace.artifacts import WorkspaceArtifactStore

    engine, fake = build_test_engine([])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifact_store = WorkspaceArtifactStore(tmp_path / "artifacts-data")
    runner = SubAgentRunner(
        llm=fake,
        registry=engine.registry,
        session_store=engine.session,
        artifact_store=artifact_store,
    )
    parent_sid = "parent-exact-context"
    psess = engine.session.load(parent_sid)
    long_text = "PARENT-HEAD-" + ("Q" * 25_000) + "-PARENT-TAIL"
    psess.messages.append(Message(role="user", content=long_text, source=MessageSource.USER))
    psess.messages.append(
        Message(
            role="assistant",
            content="VISIBLE-ANSWER",
            reasoning_content="PRIVATE-REASONING-MUST-NOT-CROSS-AGENT",
            source=MessageSource.USER,
        )
    )
    engine.session.save(psess)

    sid_token = current_session_id.set(parent_sid)
    ws_token = current_workspace_root.set(str(workspace.resolve()))
    try:
        fake._responses = [LLMResponse(content="child done", tool_calls=[], provider="fake")]
        result = runner.run(task="inspect parent", depth=0, inherit=True)
        assert result.truncated is False
        joined = "\n".join(str(m) for m in fake.calls[0]["messages"])
        import re

        match = re.search(r"exact_parent_context_ref=(artifact://v1/[0-9a-f]{32})", joined)
        assert match, joined
        ref = match.group(1)
        hydrated = ReadFileTool(artifact_store=artifact_store).execute(path=ref, offset=0, limit=20)
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)
    assert hydrated.status.name == "SUCCESS"
    assert "PARENT-HEAD-" in hydrated.content
    assert "-PARENT-TAIL" in hydrated.content
    assert "VISIBLE-ANSWER" in hydrated.content
    assert "PRIVATE-REASONING-MUST-NOT-CROSS-AGENT" not in hydrated.content
