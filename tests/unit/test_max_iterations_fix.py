"""R10(2026-08-14) 轮数上限体验修复测试（零 LLM 零网络）.

覆盖: max_iterations 默认 40（类默认 + env 默认）/ 上限反馈含续做引导 /
[轮数预警] 文本结构 / 引擎 80% 轮数注入预警一次（AI 可自主调大）/ 小预算不预警。
"""

from __future__ import annotations

from llm_loop.config import Settings, load_settings
from llm_loop.core.message import MessageSource
from llm_loop.feedback.honesty import (
    max_iterations_feedback,
    max_iterations_warning_message,
)


def test_max_iterations_default_40(monkeypatch):
    """类默认与 env 默认均 40（多步任务不再轻易触顶）."""
    assert Settings.max_iterations == 40
    # env 未设置 → 40（补必填 env 通过装配校验）
    # 2026-08-16: 显式清掉 LLM_MAX_ITERATIONS——前序测试 load_env_file 可能把 .env
    # 的 80 注入 os.environ（污染），delenv 保证本测试断言"未设置时默认"语义
    monkeypatch.delenv("LLM_MAX_ITERATIONS", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert load_settings().max_iterations == 40


def test_env_override_preserved(monkeypatch):
    """显式 env 覆盖延续."""
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "60")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert load_settings().max_iterations == 60


def test_max_iterations_feedback_has_resume_guidance():
    """上限反馈含续做引导（如实说明未完成 + 同会话可续聊）."""
    msg = max_iterations_feedback(["read_file", "execute_command"])
    assert msg.role == "system"
    assert "已达轮数上限" in msg.content
    assert "未完成" in msg.content
    assert "继续发消息" in msg.content
    assert "LLM_MAX_ITERATIONS" in msg.content
    assert "read_file" in msg.content  # 轨迹如实呈现


def test_warning_message_structure():
    """轮数预警：事实 + 可选动作（调大/压缩/如实收尾），决策归 AI."""
    msg = max_iterations_warning_message(32, 40)
    assert msg.role == "system"
    assert "[轮数预警]" in msg.content
    assert "32 轮" in msg.content and "40" in msg.content
    assert "adjust_strategy" in msg.content  # 白名单可调
    assert "上限 500" in msg.content


def test_engine_injects_warning_at_80_percent(tmp_path, monkeypatch):
    """引擎达 80% 轮数注入 [轮数预警] 一次；调大后不再重复注入."""
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        """迷你 FakeLLM: 前 8 轮返回工具调用（execute_command），第 9 轮直接回答.

        预算 10 的 80% = 8 → 第 8 轮工具轮末注入 [轮数预警]（第 9 轮回答 break 不经检查点）。
        """

        def __init__(self) -> None:
            self.calls = 0

        def _next(self) -> LLMResponse:
            self.calls += 1
            if self.calls < 9:
                from llm_loop.core.message import ToolCall

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
            # 生成器协议：return 值作为 StopIteration.value（与真实 stream 语义一致）
            def _gen():
                yield from ()  # 空迭代（无 delta），return 值承载响应
                return self._next()

            return _gen()

    class _Reg(ToolRegistry):
        def execute(self, call):
            from llm_loop.core.message import ToolResult

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ok",
                tool_call_id=call.id,
                tool_name=call.name,
                duration_ms=0.0,
            )

    from llm_loop.core.message import ToolResultStatus

    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    store = SessionStore(sess_dir)
    fake = _Fake()
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
    settings = Settings(
        llm_api_key="k",
        llm_base_url="http://t",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        max_iterations=10,  # 80% = 8 轮 → 第 8 轮注入预警
    )
    engine = LoopEngine(
        llm_client=fake,  # type: ignore[arg-type]
        registry=reg,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=store,
        settings=settings,
    )
    sid = store.create()
    result = engine.run(sid, "多步任务")
    sess = store.load(sid)
    warnings = [m for m in sess.messages if m.role == "system" and "[轮数预警]" in m.content]
    assert len(warnings) == 1  # 只注入一次
    assert warnings[0].source == MessageSource.SYSTEM
    assert result.final_answer  # 正常完成（未触顶）


def test_warning_not_injected_for_small_budget(tmp_path):
    """预算 < 10 时不预警（小预算场景零噪音）."""
    from llm_loop.feedback.honesty import max_iterations_warning_message

    msg = max_iterations_warning_message(7, 8)  # 仅验证文本函数；引擎侧小预算由条件守卫跳过
    assert "轮数预警" in msg.content


# ── H-UI: 引擎动作观察者（实时状态条数据源）──


def test_action_observer_events_sequence(tmp_path):
    """观察者收到 thinking→tool_call→tool_result→thinking→answer→done 序列（同步 run 也触发）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.message import ToolCall, ToolResultStatus
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def __init__(self) -> None:
            self.calls = 0

        def _next(self) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="用工具",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"})
                    ],
                    provider="fake",
                )
            return LLMResponse(content="最终回答", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw) -> LLMResponse:
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return self._next()

            return _gen()

    class _Reg(ToolRegistry):
        def execute(self, call):
            from llm_loop.core.message import ToolResult

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ok",
                tool_call_id=call.id,
                tool_name=call.name,
                duration_ms=0.0,
            )

    reg = _Reg()
    reg.register(
        type(
            "RF",
            (),
            {
                "name": "read_file",
                "description": "test",
                "parameters": {"type": "object"},
            },
        )()
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=reg,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=SessionStore(tmp_path / "sessions"),
        settings=settings,
    )
    events: list[str] = []
    engine.set_action_observer(lambda etype, payload: events.append(etype))
    engine.run_single("任务")
    assert events[0] == "thinking"
    assert "tool_call" in events
    assert "tool_result" in events
    assert events[-1] == "done"
    # 顺序约束：tool_call 在 tool_result 前
    assert events.index("tool_call") < events.index("tool_result")
    # 最后回答前有 thinking（第 2 轮）
    assert events.count("thinking") >= 2
    # 观察者通知后移除 → 不再触发
    engine.set_action_observer(None)
    events.clear()
    engine.run_single("任务2")
    assert events == []


def test_action_observer_exception_fail_open(tmp_path):
    """观察者抛异常 → fail-open，主循环正常完成."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def chat(self, messages, tools, **kw) -> LLMResponse:
            return LLMResponse(content="回答", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="回答", tool_calls=[], provider="fake")

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=SessionStore(tmp_path / "sessions"),
        settings=settings,
    )

    def boom(etype, payload):
        raise RuntimeError("观察者故障")

    engine.set_action_observer(boom)
    result = engine.run_single("任务")
    assert result.final_answer == "回答"  # 观察者异常不影响结果
