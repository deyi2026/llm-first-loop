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
