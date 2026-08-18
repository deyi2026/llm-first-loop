"""LLM 异常类型（design.md §2.2.2.4 / DFX-REL-02）.

异常如实向上传播，由核心循环如实反馈（不伪造回答）。
"""

from __future__ import annotations


class LLMError(Exception):
    """LLM 调用基类异常."""

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


class LLMTimeoutError(LLMError):
    """LLM 请求超时."""


class LLMNetworkError(LLMError):
    """网络不可达."""


class LLMHTTPError(LLMError):
    """非 2xx 响应（含 400 协议错误）."""

    def __init__(
        self, message: str, *, status_code: int, body: str = "", provider: str = ""
    ) -> None:
        super().__init__(message, provider=provider)
        self.status_code = status_code
        self.body = body


class LLMProtocolError(LLMError):
    """响应协议解析失败（流式/字段缺失等）."""


class LLMEmptyResponseError(LLMError):
    """LLM 返回空内容（无文本且无工具调用）——流被截断/模型异常，不应静默记为成功.

    EVO-20260818-92bd97d6: 此前空响应被静默记为 llm_response content=(空)，
    用户看到"无回答输出"且无异常记录；现在抛此异常走如实反馈路径。
    """


# R4: provider 返回的上下文溢出错误模式（如实反馈让 AI 决策，不自动重试）
_OVERFLOW_PATTERNS = (
    "context length exceeded",
    "request_too_large",
    "input token count exceeds",
    "maximum context length",
    "token limit exceeded",
    "context window exceeded",
    "prompt is too long",
    "input too long",
)


def is_overflow_error(exc: LLMError) -> bool:
    """识别 provider 返回的上下文溢出错误（R4: 如实反馈让 AI 决策）."""
    msg = str(exc).lower()
    return any(p in msg for p in _OVERFLOW_PATTERNS)


# EVO-20260812-fb50ab78: provider 配额耗尽错误模式（billing 周期用尽，本周期内不可恢复）
# 实测: kimi 返回 HTTP 403 {"type":"access_terminated_error", ...}（配额周期用尽）
_QUOTA_PATTERNS = (
    "access_terminated_error",
    "usage limit",
    "quota",
    "insufficient_quota",
    "billing cycle",
    "purchase extra usage",
)


def is_quota_error(exc: LLMError) -> bool:
    """识别 provider 返回的配额耗尽错误（403/429 之外的 billing 用尽，本周期不可恢复）.

    与 is_overflow_error 同构: 识别后由 feedback 层如实反馈（专门文案），
    不触发降级重试（换模型无用，配额是账户级）——RULE-AI-01 诚实反馈。
    """
    # 403 权限类中仅配额终止模式命中；其余 403（鉴权/权限）不误判
    if isinstance(exc, LLMHTTPError) and exc.status_code == 403:
        body = (exc.body or "").lower()
        msg = str(exc).lower()
        return any(p in body or p in msg for p in _QUOTA_PATTERNS)
    # 429 限流通常可等待恢复，但 access_terminated 语义明确为配额用尽时也识别
    if isinstance(exc, LLMHTTPError) and exc.status_code == 429:
        body = (exc.body or "").lower()
        return "access_terminated" in body
    return False
