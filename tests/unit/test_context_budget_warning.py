"""HARNESS-04(2026-08-14) 上下文预算预警测试（零 LLM 零网络）.

覆盖: 上下文占用率 ≥80% 预算时引擎注入 [预算预警] 一次（事实告知,
决策归 AI——RULE-AI-00 程序不自动压缩）; 低于阈值不注入; 文本结构。
"""

from __future__ import annotations

import pytest

from llm_loop.config import Settings
from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.message import (
    Message,
    MessageSource,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from llm_loop.core.session import SessionStore
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """隔离协调通道/data 目录（EVO-20260817: 测试进程 cwd=项目根时，_inject_interop_messages
    会读取真实 data/interop/ 残留 pending 消息并注入构建载荷——多轮测试恰好越过 90%
    压缩线导致 user 历史被整组归档、[预算预警] 永不触发。此处把 LFL_DATA_DIR 指到 tmp，
    让 inbox 为空，测试载荷完全可控。"""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path / "data"))
    yield


def _make_fake():
    """迷你 FakeLLM: 第 1 轮工具调用（让检查点执行），第 2 轮直接回答."""

    class _Fake:
        def __init__(self) -> None:
            self.calls = 0

        def _next(self) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="执行命令",
                    tool_calls=[
                        ToolCall(
                            id="tc1", name="execute_command", arguments={"command": "echo 1"}
                        )
                    ],
                    provider="fake",
                )
            return LLMResponse(content="完成", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw) -> LLMResponse:
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()  # 空迭代（无 delta），return 值承载响应
                return self._next()

            return _gen()

    return _Fake()


class _Reg(ToolRegistry):
    def execute(self, call):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="ok",
            tool_call_id=call.id,
            tool_name=call.name,
            duration_ms=0.0,
        )


def _build_engine(tmp_path, fake, settings):
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    store = SessionStore(sess_dir)
    reg = _Reg()
    reg.register(
        type(
            "EC",
            (),
            {
                "name": "execute_command",
                "description": "test",
                "parameters": {"type": "object"},
            },
        )()
    )
    engine = LoopEngine(
        llm_client=fake,  # type: ignore[arg-type]
        registry=reg,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=store,
        settings=settings,
    )
    return store, engine


def test_engine_injects_context_warning_at_80_percent(tmp_path):
    """上下文占用 ≥80% 预算 → 工具轮末注入 [预算预警] 一次（事实告知，不自动压缩）."""
    settings = Settings(
        llm_api_key="k",
        llm_base_url="http://t",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        max_iterations=10,
    )
    fake = _make_fake()
    store, engine = _build_engine(tmp_path, fake, settings)
    sid = store.create()
    # 预填超长历史: 预算默认 100K，历史 85K（85% 预算）+system prompt → 超 80% 预警线。
    # ⚠️ 不能预填 90K: EVO-20260817 compact_ratio=0.9 预算分级主动压缩在 ≥90% 提前归档
    # （裁到 60% 留缓冲），90K 单条会被整组另存 → 提交载荷骤降 → 预警条件（≥80%）永不达。
    # 预警有效窗口 = (80%预算, 90%压缩线)。
    sess = store.load(sid)
    sess.messages.append(
        Message(role="user", content="内容" * 42500, source=MessageSource.USER)  # 85000 字符
    )
    store.save(sess)

    result = engine.run(sid, "继续")
    sess = store.load(sid)
    warnings = [m for m in sess.messages if m.role == "system" and "[预算预警]" in m.content]
    assert len(warnings) == 1  # 只注入一次
    assert warnings[0].source == MessageSource.SYSTEM
    # 文本结构: 占用率 + 字符数 + 决策归 AI（不自动压缩）
    assert "预算的" in warnings[0].content and "%" in warnings[0].content
    assert "字符" in warnings[0].content
    assert "RULE-AI-00" in warnings[0].content and "不会自动压缩" in warnings[0].content
    assert result.final_answer  # 正常完成（预警不阻断）


def test_engine_no_context_warning_below_threshold(tmp_path):
    """上下文占用 <80% → 不注入（零噪音）."""
    settings = Settings(
        llm_api_key="k",
        llm_base_url="http://t",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        max_iterations=10,
    )
    fake = _make_fake()
    store, engine = _build_engine(tmp_path, fake, settings)
    sid = store.create()
    # 短历史: 远低于 80% 预算
    result = engine.run(sid, "你好")
    sess = store.load(sid)
    warnings = [m for m in sess.messages if m.role == "system" and "[预算预警]" in m.content]
    assert warnings == []
    assert result.final_answer


def test_context_warning_once_per_run(tmp_path):
    """同一次 run 内多工具轮也只注入一次（幂等）. """
    settings = Settings(
        llm_api_key="k",
        llm_base_url="http://t",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        max_iterations=10,
    )

    class _Fake:
        def __init__(self) -> None:
            self.calls = 0

        def _next(self) -> LLMResponse:
            self.calls += 1
            if self.calls <= 3:
                return LLMResponse(
                    content="执行命令",
                    tool_calls=[
                        ToolCall(
                            id=f"tc{self.calls}",
                            name="execute_command",
                            arguments={"command": f"echo {self.calls}"},
                        )
                    ],
                    provider="fake",
                )
            return LLMResponse(content="完成", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw) -> LLMResponse:
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return self._next()

            return _gen()

    store, engine = _build_engine(tmp_path, _Fake(), settings)
    sid = store.create()
    sess = store.load(sid)
    # 同 test_engine_injects_context_warning_at_80_percent: 85K 落预警窗口（避开 90% 压缩线）
    sess.messages.append(
        Message(role="user", content="内容" * 42500, source=MessageSource.USER)  # 85000 字符
    )
    store.save(sess)

    engine.run(sid, "继续")
    sess = store.load(sid)
    warnings = [m for m in sess.messages if m.role == "system" and "[预算预警]" in m.content]
    assert len(warnings) == 1  # 3 轮工具仍只注入一次
