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
