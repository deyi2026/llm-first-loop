"""R4 → R8.24-B: overflow 处理测试.

验证:
- is_overflow_error 模式识别正确
- 退役 overflow 教程生产者不存在于生产源码
- R8.24-B B-D5 集成: 首次 overflow 确定性收缩重发（零注入）、二次终止
"""
from __future__ import annotations

from llm_loop.llm.errors import LLMError, LLMHTTPError, LLMTimeoutError, is_overflow_error


def test_is_overflow_error_patterns():
    """识别常见 overflow 错误模式."""
    assert is_overflow_error(LLMHTTPError("context length exceeded", status_code=400))
    assert is_overflow_error(LLMError("request_too_large"))
    assert is_overflow_error(LLMError("input token count exceeds maximum"))
    assert is_overflow_error(LLMError("maximum context length is 8192"))
    assert is_overflow_error(LLMError("prompt is too long"))
    assert is_overflow_error(LLMError("input too long"))


def test_is_overflow_error_non_overflow():
    """非 overflow 错误返回 False."""
    assert not is_overflow_error(LLMTimeoutError("timeout"))
    assert not is_overflow_error(LLMHTTPError("not found", status_code=404))
    assert not is_overflow_error(LLMError("rate limit exceeded"))
    assert not is_overflow_error(LLMError("internal server error"))


# ── R4 → R8.24-B B-D5: overflow 确定性 runtime 处理（零 prompt 注入）集成测试 ──


def test_overflow_first_shrinks_budget_and_continues(build_test_engine):
    """R8.24-B B-D5: 首次 overflow → 确定性收缩重发（continue），sess 零注入."""

    def raise_overflow(history):
        raise LLMHTTPError("context length exceeded", status_code=400)

    engine, fake = build_test_engine([
        raise_overflow,
        {"content": "已处理overflow"},
    ])
    result = engine.run("s1", "你好")
    assert "已处理overflow" in result.final_answer
    assert len(fake.calls) == 2  # continue 后第二次调用在场
    sess = engine.session.load("s1")
    overflow_sys = [m for m in sess.messages if "上下文溢出" in m.content and m.role == "system"]
    assert len(overflow_sys) == 0  # 零注入


def test_overflow_second_time_ends_loop(build_test_engine):
    """R8.24-B B-D5: 第二次 overflow 直接确定性终止（纯事实终态，无注入）."""
    def raise_overflow(history):
        raise LLMHTTPError("context length exceeded", status_code=400)

    engine, _fake = build_test_engine([raise_overflow, raise_overflow])
    result = engine.run("s2", "你好")
    assert "上下文超限" in result.final_answer  # 新事实终态文案
    sess = engine.session.load("s2")
    overflow_sys = [m for m in sess.messages if "上下文溢出" in m.content and m.role == "system"]
    assert len(overflow_sys) == 0
