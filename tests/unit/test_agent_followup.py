"""EVO-20260914-e6b8aa22: 终止 child 有界续话（同会话/硬预算/时间窗/显式拒绝）。"""

from __future__ import annotations

from llm_loop.core.run_context import current_session_id
from llm_loop.subagent.runner import SubAgentRunner

MARKER = "[subagent_followup:"


def _make_runner(engine) -> SubAgentRunner:
    return SubAgentRunner(
        llm=engine.registry.llm if getattr(engine.registry, "llm", None) else engine.llm,
        registry=engine.registry,
        session_store=engine.session,
    )


def _run_child(engine, runner: SubAgentRunner, fake, parent_sid: str, answer: str, task: str):
    fake._responses = [{"content": answer}]
    tok = current_session_id.set(parent_sid)
    try:
        result = runner.run(task=task, depth=0)
        assert result.outcome == "completed", result.final_answer
        # 从会话目录找到该 child 的 sid
        sid = result.session_id if getattr(result, "session_id", None) else None
        if sid is None:
            import pathlib

            cands = sorted(
                pathlib.Path(engine.session._dir).glob("subagent_*.json"),
                key=lambda p: p.stat().st_mtime,
            )
            sid = cands[-1].stem
        return sid
    finally:
        current_session_id.reset(tok)


def test_followup_success_same_session_and_budget_accounting(build_test_engine):
    engine, fake = build_test_engine([])
    parent = engine.session.create()
    runner = _make_runner(engine)
    child_id = _run_child(engine, runner, fake, parent, "A完成", "做A")
    # Normal completed children retain the existing active/session-visible lifecycle.
    assert engine.session.load(child_id).status == "active"

    tok = current_session_id.set(parent)
    try:
        fake._responses = [{"content": "B完成"}]
        ok, detail, result = runner.followup_current(child_id, "补充：再做B")
        assert ok, detail
        assert result.outcome == "completed"
        assert "B完成" in result.final_answer
        assert "1/2" in detail and "1/4" in detail

        sess = engine.session.load(child_id)
        markers = [
            m for m in sess.messages
            if m.role == "user" and str(m.content).startswith(MARKER)
        ]
        assert len(markers) == 1 and "再做B" in markers[0].content
        # 同会话证据：child 原任务消息仍在（未新开会话）
        assert any(m.role == "user" and "做A" in str(m.content) for m in sess.messages)

        fake._responses = [{"content": "确认完成"}]
        ok2, detail2, _ = runner.followup_current(child_id, "最后确认")
        assert ok2 and "2/2" in detail2

        # per-child 上限：第 3 次显式拒绝并指向 spawn_subagent
        ok3, detail3, res3 = runner.followup_current(child_id, "第三次")
        assert not ok3 and "用尽" in detail3 and "spawn_subagent" in detail3
        assert res3 is None
    finally:
        current_session_id.reset(tok)


def test_followup_rejects_non_child(build_test_engine):
    engine, fake = build_test_engine([])
    parent = engine.session.create()
    runner = _make_runner(engine)
    child_id = _run_child(engine, runner, fake, parent, "A完成", "做A")

    tok = current_session_id.set("session-not-mine")
    try:
        ok, detail, _ = runner.followup_current(child_id, "越权续话")
        assert not ok and "直接 child" in detail
    finally:
        current_session_id.reset(tok)


def test_followup_window_expiry(build_test_engine):
    engine, fake = build_test_engine([])
    parent = engine.session.create()
    runner = _make_runner(engine)
    child_id = _run_child(engine, runner, fake, parent, "A完成", "做A")
    # run_owned_session 退出会刷新 updated_at，改用负窗口等价模拟“终止很久之后”
    runner.FOLLOWUP_WINDOW_S = -1  # type: ignore[assignment]

    tok = current_session_id.set(parent)
    try:
        ok, detail, _ = runner.followup_current(child_id, "迟到的续话")
        assert not ok and "过期" in detail and "spawn_subagent" in detail
    finally:
        current_session_id.reset(tok)


def test_followup_empty_args_rejected(build_test_engine):
    engine, _ = build_test_engine([])
    runner = _make_runner(engine)
    parent = engine.session.create()
    tok = current_session_id.set(parent)
    try:
        ok, detail, _ = runner.followup_current("  ", "指令")
        assert not ok and "child_id" in detail
        ok2, detail2, _ = runner.followup_current("x", "  ")
        assert not ok2 and "instruction" in detail2
    finally:
        current_session_id.reset(tok)


def test_followup_parent_total_budget(build_test_engine):
    engine, fake = build_test_engine([])
    parent = engine.session.create()
    runner = _make_runner(engine)
    # 造满父会话总量预算：4 条含 agent_followup 工具调用的 assistant 帧
    from llm_loop.core.message import Message, MessageSource

    with engine.session.run_owned_session(parent) as owned:
        for i in range(4):
            owned.messages.append(
                Message(
                    role="assistant",
                    content="",
                    source=MessageSource.TOOL,
                    tool_calls=[
                        {"id": f"call_seed_{i}", "name": "agent_followup", "arguments": {}}
                    ],
                )
            )
        engine.session.save(owned)  # run_owned_session 仅快照，需显式落盘
    child_id = _run_child(engine, runner, fake, parent, "A完成", "做A")

    tok = current_session_id.set(parent)
    try:
        ok, detail, _ = runner.followup_current(child_id, "第5次")
        assert not ok and "总预算" in detail and "spawn_subagent" in detail
    finally:
        current_session_id.reset(tok)


def test_followup_tool_wraps_runner(build_test_engine):
    engine, fake = build_test_engine([])
    parent = engine.session.create()
    runner = _make_runner(engine)
    child_id = _run_child(engine, runner, fake, parent, "A完成", "做A")

    from llm_loop.tools.builtin.agent_followup import AgentFollowupTool

    tok = current_session_id.set(parent)
    try:
        tool = AgentFollowupTool(runner)
        fake._responses = [{"content": "续答完成"}]
        r = tool.execute(child_id=child_id, instruction="补充问一句")
        assert r.status.value == "success", r.content
        assert "续话完成" in r.content and "子代理回答" in r.content
        r2 = tool.execute(child_id=child_id, instruction="")
        assert r2.status.value == "failure" and "参数错误" in r2.content
        r3 = tool.execute(child_id="no-such-child", instruction="x")
        assert r3.status.value == "failure" and "no-such-child" in r3.content
    finally:
        current_session_id.reset(tok)
