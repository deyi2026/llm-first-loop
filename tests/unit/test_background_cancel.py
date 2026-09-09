"""后台 Stop 的真实取消语义与跨会话隔离回归."""

from __future__ import annotations

import queue
import shlex
import threading
import time
from pathlib import Path

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.llm.client import LLMResponse, StreamDelta
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolRegistry

_STOP_TEXT = "（已停止——用户点击停止按钮，本轮回答终止）"


def _wait_done(q: queue.Queue, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    events = []
    while time.monotonic() < deadline:
        event = q.get(timeout=max(0.01, deadline - time.monotonic()))
        events.append(event)
        if event["type"] == "done":
            return events, event["result"]
        if event["type"] == "error":
            raise AssertionError(event["error"])
    raise AssertionError("后台 run 未在期限内结束")


def test_cancel_stops_llm_stream_before_more_deltas(build_test_engine):
    """收到首 token 后 Stop：后续 delta 不再外泄，完整答案不得伪装落盘."""
    engine, fake = build_test_engine([])
    full = "ABCDEFGHIJKLMNO"
    stream_closed = threading.Event()

    def slow_stream(**_kwargs):
        try:
            for ch in full:
                time.sleep(0.04)
                yield StreamDelta(text=ch)
            return LLMResponse(content=full, tool_calls=[], provider="fake")
        finally:
            stream_closed.set()

    fake.chat_stream = slow_stream
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()

    _handle, q = runner.start(sid, "hello")
    first = q.get(timeout=2.0)
    assert first["type"] == "delta"
    assert first["delta"].text == "A"
    assert runner.cancel(sid) is True

    events, result = _wait_done(q, timeout=2.0)
    leaked = "".join(
        event["delta"].text for event in events if event["type"] == "delta" and event["delta"].text
    )
    assert leaked == "", "Stop 后不应继续外泄后续 token"
    assert result.final_answer == _STOP_TEXT
    assert stream_closed.wait(0.5), "取消后应 close LLM stream 释放 HTTP/生成资源"

    sess = engine.session.load(sid)
    # Agency-first: cancelled 收口仍保留 assistant role 边界，但边界内容必须为零，
    # 不能把历史 [program-final] 控制字串重新暴露给后续 provider prompt。
    assert sess.messages[-1].role == "assistant"
    assert sess.messages[-1].content == ""
    # B1(EVO-20260902-41898b20): 倒数第二行 = 中断半截产物（截断标注如实落盘，
    # 本次取消仅消费首 token "A"）
    assert "[截断标注]" in sess.messages[-2].content
    assert "reason=cancelled" in sess.messages[-2].content
    assert full not in [m.content for m in sess.messages]


def test_cancel_stops_running_execute_command(build_test_engine):
    """工具已启动后 Stop：命令应被定向终止，而不是等自然完成/超时."""
    engine, fake = build_test_engine(
        [
            {
                "content": "",
                "tool_calls": [
                    ToolCall(
                        id="call-slow",
                        name="execute_command",
                        arguments={"command": "sleep 5; echo TOOL_FINISHED"},
                    )
                ],
            },
            {"content": "SHOULD_NOT_REACH"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()

    _handle, q = runner.start(sid, "run slow command")
    progress = q.get(timeout=2.0)
    assert progress["type"] == "delta"
    assert progress["delta"].tool_round is not None

    tool = engine.registry.get("execute_command")
    deadline = time.monotonic() + 1.0
    while not getattr(tool, "_active_procs", {}) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert getattr(tool, "_active_procs", {}), "测试前提：命令子进程应已启动"

    started = time.monotonic()
    assert runner.cancel(sid) is True
    _events, result = _wait_done(q, timeout=2.0)
    elapsed = time.monotonic() - started

    assert elapsed < 1.5, f"Stop 后工具仍阻塞过久: {elapsed:.3f}s"
    assert result.final_answer == _STOP_TEXT
    assert len(fake._responses) == 1, "取消后不应进入下一轮 LLM"
    sess = engine.session.load(sid)
    assert not any(
        "TOOL_FINISHED\n" in (m.content or "") for m in sess.messages if m.role == "tool"
    )


def test_registry_cancel_session_does_not_kill_other_session(tmp_path: Path):
    """共享 ExecuteCommandTool 并发时，取消 s1 绝不能误杀 s2."""
    registry = ToolRegistry(tool_timeout_s=10.0)
    tool = ExecuteCommandTool(timeout_s=10.0)
    registry.register(tool)
    started1 = tmp_path / "s1.started"
    started2 = tmp_path / "s2.started"
    results = {}

    def run(sid: str, marker: Path, sleep_s: float, done_text: str) -> None:
        token = current_session_id.set(sid)
        try:
            cmd = f"echo started > {shlex.quote(str(marker))}; sleep {sleep_s}; echo {done_text}"
            results[sid] = registry.execute(
                ToolCall(id=f"call-{sid}", name="execute_command", arguments={"command": cmd})
            )
        finally:
            current_session_id.reset(token)

    t1 = threading.Thread(target=run, args=("s1", started1, 5.0, "S1_DONE"), daemon=True)
    t2 = threading.Thread(target=run, args=("s2", started2, 0.8, "S2_DONE"), daemon=True)
    t1.start()
    t2.start()

    deadline = time.monotonic() + 2.0
    while not (started1.exists() and started2.exists()) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started1.exists() and started2.exists(), "两个会话命令都应已启动"

    cancelled = registry.cancel_session("s1")
    assert cancelled >= 1
    t1.join(timeout=1.5)
    assert not t1.is_alive(), "s1 应被快速终止"
    assert t2.is_alive(), "取消 s1 不得误杀仍在运行的 s2"

    t2.join(timeout=2.0)
    assert not t2.is_alive()
    assert results["s2"].status == ToolResultStatus.SUCCESS
    assert "S2_DONE" in results["s2"].content
    assert results["s1"].status != ToolResultStatus.SUCCESS
