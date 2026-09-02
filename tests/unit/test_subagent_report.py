"""DSH 借鉴 022-B（2026-08-17）: 子代理中途报告（subagent_report）测试.

验证:
- 子代理调用 subagent_report → 报告收集进 SubAgentResult.reports
- 回执含 [中途报告] 摘要
- interop inbox 仍保留 from=subagent-report 通知用于 UI/audit，但父模型不靠该通知回注；reports 已随工具回执直接返回
- 非子代理上下文调用 → 拒绝
- 白名单放行（不被 blocked）
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
from llm_loop.tools.builtin.subagent_report import _SUBAGENT_REPORT_CTX, SubagentReportTool


def _inbox_files(tmp_path: Path) -> list[Path]:
    base = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    if not base.is_dir():
        return []
    return sorted(base.glob("*.json"))


def test_runner_collects_reports(build_test_engine, tmp_path, monkeypatch):
    """子代理中途报告: 收集进 reports + inbox 通知."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    # ① 调 subagent_report 报进展 → ② 给出最终回答
    fake._responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="subagent_report", arguments={"content": "已定位根因: 缓存键未失效"})],
            provider="fake",
        ),
        LLMResponse(content="子代理完成", tool_calls=[], provider="fake"),
    ]

    result = runner.run(task="排查缓存问题", depth=0)

    assert result.truncated is False
    assert result.reports == ["已定位根因: 缓存键未失效"]
    # inbox 通知（from=subagent-report）
    files = _inbox_files(tmp_path)
    assert len(files) == 1, files
    msg = json.loads(files[0].read_text(encoding="utf-8"))
    assert msg["from"] == "subagent-report"
    assert msg["topic"] == "notify"
    assert "已定位根因" in msg["body"]
    assert msg["ref"].startswith("subagent_")


def test_report_delivery_does_not_duplicate_into_parent_prompt(build_test_engine, tmp_path, monkeypatch):
    """R8.12/E25: subagent report 已随 SubAgentResult/tool receipt 回父级，notify 只留 UI/audit.

    报告不改变子代理生命周期；interop 扫描把 notify 归档到 done/，不再把同一工作产物
    第二次作为程序消息塞给父模型。
    """
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    # 子代理: 报告一次 → 再报告一次 → 结束（报告不打断生命周期，全部收集）
    fake._responses = [
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="subagent_report", arguments={"content": "关键发现A"})], provider="fake"),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="subagent_report", arguments={"content": "关键发现B"})], provider="fake"),
        LLMResponse(content="子代理完成", tool_calls=[], provider="fake"),
    ]
    result = runner.run(task="长任务拆解", depth=0)
    assert result.reports == ["关键发现A", "关键发现B"]  # 生命周期未被打断
    # 父级唯一语义通道已经是 result.reports / spawn_subagent tool receipt；
    # interop notify 只做观测归档，不能重复进入父模型 prompt。
    from llm_loop.core.loop.engine_services.interop import InteropService

    parent_eng = InteropService(None)  # 02e 服务化：mixin 裸实例 → host=None 裸服务，fail-open 契约不变
    assert parent_eng._interop_inbox_messages() == []
    done_dir = tmp_path / "interop" / "lfl_to_dsh" / "done"
    payloads = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(done_dir.glob("*.json"))]
    assert len(payloads) == 2
    bodies = " ".join(str(x.get("body", "")) for x in payloads)
    assert "关键发现A" in bodies and "关键发现B" in bodies
    assert all(x.get("status") == "done" for x in payloads)
    assert all(x.get("from") == "subagent-report" for x in payloads)


def test_runner_multiple_reports_all_collected(build_test_engine, tmp_path, monkeypatch):
    """多次报告: 全部按序收集."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    fake._responses = [
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="subagent_report", arguments={"content": "进展1"})], provider="fake"),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="subagent_report", arguments={"content": "进展2"})], provider="fake"),
        LLMResponse(content="完成", tool_calls=[], provider="fake"),
    ]
    result = runner.run(task="多轮报告", depth=0)
    assert result.reports == ["进展1", "进展2"]
    # 同秒连续报告 → inbox 应有 2 条独立通知（序号防同名覆盖）
    files = _inbox_files(tmp_path)
    assert len(files) == 2, files
    assert all(json.loads(f.read_text(encoding="utf-8"))["from"] == "subagent-report" for f in files)


def test_spawn_tool_receipt_includes_reports(build_test_engine, tmp_path, monkeypatch):
    """spawn_subagent 回执含 [中途报告] 摘要（父级可见）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    fake._responses = [
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="subagent_report", arguments={"content": "找到关键线索 X"})], provider="fake"),
        LLMResponse(content="子代理完成", tool_calls=[], provider="fake"),
    ]
    tool = SpawnSubAgentTool(runner)
    r = tool.execute(task="调研线索")
    assert r.status.name == "SUCCESS", r.content
    assert "[中途报告 1 条]" in r.content
    assert "找到关键线索 X" in r.content


def test_report_outside_subagent_rejected():
    """非子代理上下文调用 → 如实拒绝."""
    r = SubagentReportTool().execute(content="不应成功")
    assert r.status.name == "FAILURE"
    assert "仅子代理会话内可用" in r.content


def test_report_not_blocked_by_whitelist(build_test_engine, tmp_path, monkeypatch):
    """白名单: subagent_report 在受限集内（不被 blocked）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    fake._responses = [
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="subagent_report", arguments={"content": "汇报"})], provider="fake"),
        LLMResponse(content="完成", tool_calls=[], provider="fake"),
    ]
    result = runner.run(task="白名单验证", depth=0)
    assert result.tool_calls[0]["name"] == "subagent_report"
    assert result.tool_calls[0]["status"] == "success"  # 未被 blocked


def test_report_ctx_reset_after_run(build_test_engine, tmp_path, monkeypatch):
    """contextvar 恢复: run 结束后非子代理上下文（防串台）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    fake._responses = [LLMResponse(content="完成", tool_calls=[], provider="fake")]
    runner.run(task="无报告任务", depth=0)
    assert _SUBAGENT_REPORT_CTX.get() is None  # 已恢复


# ── DSH 借鉴 022-A: fork 继承（父会话切片注入）──
def test_inherit_injects_parent_context(build_test_engine, tmp_path, monkeypatch):
    """inherit=True: 父会话最近消息切片注入子代理 context."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    # 造父会话: 2 条消息（用户 + 助手）
    parent_sid = "parent-fork-test"
    psess = engine.session.load(parent_sid)
    from llm_loop.core.message import Message, MessageSource

    psess.messages.append(Message(role="user", content="用户原始问题: 如何优化缓存", source=MessageSource.USER))
    psess.messages.append(Message(role="assistant", content="初步分析: 命中率低", source=MessageSource.SYSTEM))
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
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    parent_sid = "parent-noinherit"
    psess = engine.session.load(parent_sid)
    from llm_loop.core.message import Message, MessageSource

    psess.messages.append(Message(role="user", content="不应继承的父消息", source=MessageSource.USER))
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
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
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
    runner = SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session
    )
    parent_sid = "parent-spawn"
    psess = engine.session.load(parent_sid)
    from llm_loop.core.message import Message, MessageSource

    psess.messages.append(Message(role="user", content="父上下文要点XYZ", source=MessageSource.USER))
    engine.session.save(psess)
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set(parent_sid)
    try:
        fake._responses = [LLMResponse(content="子代理完成", tool_calls=[], provider="fake")]
        tool = SpawnSubAgentTool(runner)
        r = tool.execute(task="fork 任务", inherit=True)
    finally:
        current_session_id.reset(tok)
    assert r.status.name == "SUCCESS", r.content
    joined = " ".join(str(m) for m in fake.calls[0]["messages"])
    assert "父上下文要点XYZ" in joined
