"""R4: overflow 如实反馈测试（不自动重试，决策权归 AI）.

验证:
- is_overflow_error 模式识别正确
- overflow_feedback 含错误事实 + 占用 + 模型窗口 + 4 个可选动作
- overflow 不静默吞错（反馈注入 AI 可见）
"""
from __future__ import annotations

from llm_loop.feedback.honesty import overflow_feedback
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


def test_overflow_feedback_contains_error_fact():
    """反馈含错误事实."""
    exc = LLMHTTPError("context length exceeded", status_code=400)
    feedback = overflow_feedback(exc)
    assert "上下文溢出" in feedback
    assert "context length exceeded" in feedback


def test_overflow_feedback_contains_actions():
    """反馈含 4 个可选动作（AI 自主选择）."""
    exc = LLMError("request_too_large")
    feedback = overflow_feedback(exc)
    assert "search_archive" in feedback
    assert "adjust_strategy" in feedback
    assert "switch_model" in feedback
    assert "开新会话" in feedback
    assert "程序未自动压缩重试" in feedback  # 不自动重试声明


def test_overflow_feedback_with_breakdown():

    """反馈含当前占用信息."""
    exc = LLMError("context length exceeded")
    breakdown = {
        "total": {"chars": 210000, "est_tokens": 105000},
        "budget": 1000000,
        "ratio": 0.21,
    }
    feedback = overflow_feedback(exc, breakdown=breakdown)
    assert "210000" in feedback
    assert "1000000" in feedback


def test_overflow_feedback_with_model_window():
    """反馈含模型窗口信息."""
    exc = LLMError("context length exceeded")
    model_window = {"label": "kimi/k3-256k", "context": 262144}
    feedback = overflow_feedback(exc, model_window=model_window)
    assert "kimi/k3-256k" in feedback
    assert "262144" in feedback


def test_overflow_feedback_no_breakdown_no_error():
    """breakdown/model_window 为 None 时不报错."""
    exc = LLMError("context length exceeded")
    feedback = overflow_feedback(exc, breakdown=None, model_window=None)
    assert "上下文溢出" in feedback
    assert "search_archive" in feedback  # 动作建议仍在
