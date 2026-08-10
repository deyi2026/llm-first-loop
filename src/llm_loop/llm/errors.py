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
