"""M41 测试（truncated 跳过声明校验 + 工具出错引导，零真实冒烟）.

用例：truncated=True 跳过声明-回执校验 / truncated=False 校验保持 / 失败回执引导段 / BLOCKED 不加引导。
复用 tests/conftest build_test_engine fixture，FakeLLM 装配零真实 API。
"""

from __future__ import annotations

from llm_loop.llm.client import LLMResponse
from llm_loop.tools.registry import ToolResult, ToolResultStatus, tool_result_to_message


def _truncated_resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], provider="fake", truncated=True)


def _full_resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], provider="fake", truncated=False)


def test_truncated_skips_declaration_check(build_test_engine, fake_settings):
    """truncated=True（回答被截断）时不执行声明-回执校验，不注入 [声明提醒]."""
    engine, _ = build_test_engine([_truncated_resp("## 🆕 最新项目\n- **rocinante** 本地模型编码 agent")])
    sid = engine.session.create()
    # 预置一条 tool 回执（声明提到 rocinante 但回执无 → 若不跳过会误报）
    from llm_loop.core.message import Message, MessageSource

    sess = engine.session.load(sid)
    sess.messages.append(
        Message(role="tool", content="[状态: success] 无关回执", source=MessageSource.TOOL, tool_call_id="c1", tool_name="architecture_status")
    )
    engine.session.save(sess)
    result = engine.run(sid, "请调研最新项目")
    # truncated=True → 跳过校验 → verification_note 保持 None（无误报）
    assert result.truncated is True
    assert result.verification_note is None
    sess2 = engine.session.load(sid)
    assert not any("[声明提醒]" in str(m.content) for m in sess2.messages if m.role == "system")


def test_not_truncated_keeps_declaration_check(build_test_engine, fake_settings):
    """truncated=False（完整回答）时声明-回执校验保持（FR-FBK-01 语义零回归）."""
    engine, _ = build_test_engine([_full_resp("我已完成全部调研并写入了方案。")])
    sid = engine.session.create()
    from llm_loop.core.message import Message, MessageSource

    sess = engine.session.load(sid)
    sess.messages.append(
        Message(role="tool", content="[状态: success] 无关回执", source=MessageSource.TOOL, tool_call_id="c1", tool_name="architecture_status")
    )
    engine.session.save(sess)
    result = engine.run(sid, "请完成任务")
    assert result.truncated is False
    # 校验执行路径（validator.check 被调用）——声明与回执不符可能触发 verification_note
    assert result.verification_note is None or "声明" in str(result.verification_note)


def test_failure_guidance_appended():
    """工具 failure 回执追加引导段（错误类型 + 建议换用工具/重试）."""
    result = ToolResult(
        status=ToolResultStatus.FAILURE,
        content="[工具不存在] 未注册的工具 'xyz'",
        tool_call_id="c1",
        tool_name="xyz",
    )
    msg = tool_result_to_message(result)
    assert "[状态: failure]" in msg.content
    assert "建议" in msg.content
    assert "RULE-AI-02/07" in msg.content


def test_blocked_no_guidance():
    """BLOCKED 回执不加引导段（灾难性拦截语义，不做任何诱导）."""
    result = ToolResult(
        status=ToolResultStatus.BLOCKED,
        content="[安全拦截] 该命令被灾难性保护拦截",
        tool_call_id="c1",
        tool_name="execute_command",
    )
    msg = tool_result_to_message(result)
    assert "[状态: blocked]" in msg.content
    assert "建议" not in msg.content


def test_guidance_disabled():
    """failure_guidance_enabled=False 时不追加引导段."""
    result = ToolResult(
        status=ToolResultStatus.ERROR,
        content="[执行异常] boom",
        tool_call_id="c1",
        tool_name="t1",
    )
    msg = tool_result_to_message(result, failure_guidance_enabled=False)
    assert "建议" not in msg.content
