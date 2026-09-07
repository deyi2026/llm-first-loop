"""LLM 异常类型（design.md §2.2.2.4 / DFX-REL-02）.

异常如实向上传播，由核心循环如实反馈（不伪造回答）。
"""

from __future__ import annotations

import json
import re


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
    """Terminal response contained no visible text/tool call; preserve transport facts."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        finish_reason: str = "",
        completion_tokens: int = 0,
        reasoning_tokens: int | None = None,
        provider_truncated: bool = False,
    ) -> None:
        super().__init__(message, provider=provider)
        self.finish_reason = str(finish_reason or "")
        self.completion_tokens = int(completion_tokens or 0)
        self.reasoning_tokens = reasoning_tokens
        self.provider_truncated = bool(provider_truncated)


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


# err1210 T2.1（design 2.2.2-①）: provider 业务错误码提取——正则兜底模式
_PROVIDER_CODE_RE = re.compile(r'"code"\s*:\s*"?(\d+)"?')


def parse_provider_error_code(body: str) -> str | None:
    """[err1210] 从 LLMHTTPError.body 提取 provider 业务错误码（如 "1210"）.

    两级策略:
    1. json.loads(body)["error"]["code"] —— 循环解包至多 3 层（覆盖转义 JSON /
       双层转义——body 为字符串化 JSON 时 loads 得到 str 再解）;
    2. 正则 ``"code"\\s*:\\s*"?(\\d+)?"`` 兜底（覆盖前后缀噪音/半截 body）。

    任何失败返回 None（保守判非 1210，spec 5.1.3-4——调用方据此走既有路径）。
    纯函数无副作用；内部全捕获，永不抛出。
    """
    if not body:
        return None
    try:
        data: object = body
        for _ in range(3):
            if not isinstance(data, str):
                break
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                break
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                code = err.get("code")
                if code is not None:
                    return str(code)
            elif err is not None:
                return str(err)
        m = _PROVIDER_CODE_RE.search(body)
        if m:
            return m.group(1)
        return None
    except Exception:  # noqa: BLE001 — 保守判定，永不抛出
        return None
