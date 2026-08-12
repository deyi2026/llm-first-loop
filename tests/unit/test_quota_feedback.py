"""EVO-20260812-fb50ab78: 配额耗尽（billing quota）专门识别与反馈测试.

验证:
- is_quota_error 识别 403 access_terminated_error 等配额模式
- 403 非配额（权限/鉴权）不误判
- 429 access_terminated 语义识别
- llm_error_text 对配额错误给出专门文案（非泛化"检查网络/Key"）
- 非配额 LLM 异常仍走原泛化反馈（零回归）
"""
from __future__ import annotations

from llm_loop.feedback.honesty import llm_error_text
from llm_loop.llm.errors import LLMError, LLMHTTPError, LLMTimeoutError, is_quota_error


def test_is_quota_error_403_access_terminated():
    """kimi 实测模式: 403 + access_terminated_error → True."""
    exc = LLMHTTPError(
        "HTTP 403: Forbidden",
        status_code=403,
        body='{"error":{"type":"access_terminated_error","message":"usage limit"}}',
    )
    assert is_quota_error(exc)


def test_is_quota_error_403_usage_limit_body():
    """403 + usage limit/quota 语义 → True."""
    exc = LLMHTTPError("forbidden", status_code=403, body="usage limit reached")
    assert is_quota_error(exc)


def test_is_quota_error_403_non_quota():
    """403 非配额（纯权限拒绝）→ False，不误判."""
    exc = LLMHTTPError("forbidden", status_code=403, body="permission denied")
    assert not is_quota_error(exc)


def test_is_quota_error_429_access_terminated():
    """429 限流中明确 access_terminated 语义 → True."""
    exc = LLMHTTPError("rate limited", status_code=429, body='{"type":"access_terminated_error"}')
    assert is_quota_error(exc)


def test_is_quota_error_non_quota_exceptions():
    """超时/网络/普通 4xx → False."""
    assert not is_quota_error(LLMTimeoutError("timeout"))
    assert not is_quota_error(LLMError("boom"))
    assert not is_quota_error(LLMHTTPError("not found", status_code=404))
    assert not is_quota_error(LLMHTTPError("unauthorized", status_code=401))


def test_llm_error_text_quota_specialized():
    """配额错误 → 专门文案（非泛化检查网络/Key）."""
    exc = LLMHTTPError(
        "HTTP 403: Forbidden | quota",
        status_code=403,
        body='{"error":{"type":"access_terminated_error"}}',
    )
    text = llm_error_text(exc)
    assert "配额周期已用尽" in text
    assert "非网络/Key/模型配置问题" in text
    assert "等待配额刷新" in text
    assert "检查网络/Key" not in text  # 不再走泛化建议


def test_llm_error_text_non_quota_regression():
    """非配额 LLM 异常 → 原泛化反馈（零回归）."""
    exc = LLMHTTPError("bad gateway", status_code=502)
    text = llm_error_text(exc)
    assert "检查网络/Key/模型名配置后重试" in text
