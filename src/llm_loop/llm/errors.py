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
        self,
        message: str,
        *,
        status_code: int,
        body: str = "",
        provider: str = "",
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.status_code = status_code
        self.body = body
        # ASSESS-20261008 BUG-02/03: provider 业务码与 HTTP 状态是两个独立事实。
        # status_code 只承载真实 HTTP 状态；业务码（如 GLM 1311）由本字段承载，
        # 不再互相污染（原 SSE 路径把业务码灌入 status_code，使分类误判 5xx）。
        self.provider_code = (
            str(provider_code) if provider_code is not None else None
        )


class LLMStreamProviderError(LLMHTTPError):
    """HTTP 2xx + 流内 error 事件（provider 在 SSE 流中显式报告失败）.

    ASSESS-20261008 BUG-03/04 修复契约:
    - status_code 保留真实 HTTP 状态（通常 2xx），不被业务码污染;
    - provider_code 承载 provider 业务码或错误类型（如 GLM "1311" /
      Anthropic "overloaded_error" / Google "UNAVAILABLE"）;
    - partial_chars 记录错误事件前已投递的字符数（content+reasoning）——
      失败 attempt 不得发布成功 completion，也不得重放导致重复展示或
      重复工具执行，该事实供上层如实反馈"部分内容已展示但不完整"。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        provider_code: str | None = None,
        body: str = "",
        provider: str = "",
        partial_chars: int = 0,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            body=body,
            provider=provider,
            provider_code=provider_code,
        )
        self.partial_chars = max(0, int(partial_chars))


class LLMProtocolError(LLMError):
    """响应协议解析失败（流式/字段缺失等）."""


class LLMRequestTooLargeError(LLMProtocolError):
    """Local request-envelope overflow with exact mechanical size evidence.

    observed_chars and limit_chars describe the same serialized request envelope.
    They are transport facts only; callers may use them to choose a deterministic
    compaction ratio without inferring task semantics.
    """

    def __init__(
        self,
        message: str,
        *,
        observed_chars: int,
        limit_chars: int,
        provider: str = "",
    ) -> None:
        super().__init__(message, provider=provider)
        self.observed_chars = max(0, int(observed_chars))
        self.limit_chars = max(0, int(limit_chars))


class LLMProjectionError(LLMProtocolError):
    """Local provider-request projection violated a mechanical wire invariant.

    This error is raised before the HTTP transport is entered.  It represents a
    harness projection defect/pressure state, not a provider response and not a
    model semantic failure.
    """

    def __init__(
        self,
        message: str,
        *,
        violations: list[str] | tuple[str, ...],
        provider: str = "",
    ) -> None:
        super().__init__(message, provider=provider)
        self.violations = tuple(str(item) for item in violations)


class LLMEmptyResponseError(LLMError):
    """Terminal response contained no visible text/tool call; preserve transport facts."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        finish_reason: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reasoning_tokens: int | None = None,
        provider_truncated: bool = False,
    ) -> None:
        super().__init__(message, provider=provider)
        self.finish_reason = str(finish_reason or "")
        self.prompt_tokens = int(prompt_tokens or 0)
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
    # EVO-20260921-51d12fa6: GLM 400 code 1261 实测文案（hev0 P3 t3 裸注入
    # 2.7M+ chars 确定性拒绝: {"error":{"code":"1261","message":"Prompt exceeds max length"}}）
    "prompt exceeds max length",
)

# EVO-20260921-51d12fa6: GLM 族 provider（注册表 glm/glm-api；bigmodel/zhipu 同族推断）。
# 码 1261 仅在 GLM 族按码判定，避免劫持其他 provider 同码异义错误。
_GLM_OVERFLOW_PROVIDERS = ("glm", "glm-api", "zhipu")


def is_overflow_error(exc: LLMError) -> bool:
    """识别 provider 返回的上下文溢出错误（R4: 如实反馈让 AI 决策）."""
    if isinstance(exc, LLMRequestTooLargeError):
        return True
    msg = str(exc).lower()
    if any(p in msg for p in _OVERFLOW_PATTERNS):
        return True
    # EVO-20260921-51d12fa6: GLM 上下文超限错误码 1261 —— 文案可能本地化/变更，
    # 按 provider+status+码精确识别（码提取复用 err1210 的 parse_provider_error_code）。
    if (
        isinstance(exc, LLMHTTPError)
        and exc.status_code == 400
        and getattr(exc, "provider", "") in _GLM_OVERFLOW_PROVIDERS
    ):
        return parse_provider_error_code(exc.body or "") == "1261"
    return False


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


# ── ASSESS-20261008 BUG-02: 错误语义分类（分类与 availability fallback 消费同一份事实）──
# GLM 族 429 业务码语义（docs.bigmodel.cn/cn/faq/api-code）。仅在 GLM 族按码判定
# （先例: _GLM_OVERFLOW_PROVIDERS），避免劫持其他 provider 同码异义错误。
_GLM_FAMILY_PROVIDERS = ("glm", "glm-api", "zhipu")
_GLM_RATE_LIMIT_CODES = ("1302",)          # 速率限制: 瞬时，等待可恢复
_GLM_MODEL_PERMISSION_CODES = ("1311",)    # 当前订阅未开放所选模型权限（针对所选模型）
_GLM_ACCOUNT_BILLING_CODES = ("1113",)     # 账户欠费: 账户级，本周期不可恢复

# 流内错误类型语义（Anthropic error.type / Google error.status 字符串）
_STREAM_RATE_LIMIT_TYPES = ("rate_limit_error", "resource_exhausted")
_STREAM_SERVER_TYPES = ("overloaded_error", "api_error", "unavailable")
_STREAM_CLIENT_TYPES = (
    "permission_error",
    "authentication_error",
    "not_found_error",
    "invalid_request_error",
    "request_too_large",
)


class LLMErrorSemantics:
    """错误语义分类结果: 保留修复动作的三个维度，不合并成单一布尔.

    ASSESS-20261008 BUG-02 修复契约——同身份重试 / 同账户其他模型 / 独立 provider
    是三个不同问题; is_quota_error 与 availability fallback 回答不同问题，
    二者消费同一份事实（HTTP 状态 + provider + 业务码 + 脱敏摘要）。
    """

    __slots__ = (
        "kind",
        "label",
        "provider_code",
        "same_identity_retry",
        "same_account_other_models",
        "independent_provider",
    )

    def __init__(
        self,
        kind: str,
        label: str,
        *,
        provider_code: str | None = None,
        same_identity_retry: bool = False,
        same_account_other_models: bool = False,
        independent_provider: bool = False,
    ) -> None:
        self.kind = kind
        self.label = label
        self.provider_code = provider_code
        self.same_identity_retry = same_identity_retry
        self.same_account_other_models = same_account_other_models
        self.independent_provider = independent_provider

    @property
    def fallback_eligible(self) -> bool:
        """availability fallback 判定: 候选池（同账户其他模型/其他 provider）可能可用.

        同身份重试与同账户其他模型任一为真即触发降级（与既有 429/5xx/断连语义一致）;
        账户级欠费/配额两维皆假——如实反馈，不换同账户模型空转。
        """
        return self.same_identity_retry or self.same_account_other_models


def _error_code_facts(exc: LLMHTTPError) -> str | None:
    """提取业务码事实: 优先异常显式携带，其次从 body 解析（同一解析器）."""
    code = getattr(exc, "provider_code", None)
    if code:
        return code
    body = getattr(exc, "body", "") or ""
    if body:
        return parse_provider_error_code(body)
    return None


def classify_llm_error(exc: LLMError) -> LLMErrorSemantics:
    """基于事实（异常类型/HTTP 状态/provider/业务码）产生语义分类与如实标签.

    分类优先级: 异常族 → GLM 族业务码 → 配额模式（is_quota_error 同源）→
    流内错误类型/HTTP 形码 → HTTP 状态。未知业务码如实保留在标签中，
    不发明语义、不凭关键词推断全局权限。
    """
    if isinstance(exc, LLMTimeoutError):
        return LLMErrorSemantics(
            "timeout", "请求超时", same_identity_retry=True,
            same_account_other_models=True, independent_provider=True,
        )
    if isinstance(exc, LLMNetworkError):
        return LLMErrorSemantics(
            "network", "网络不可达", same_identity_retry=True,
            same_account_other_models=True, independent_provider=True,
        )
    if isinstance(exc, LLMEmptyResponseError):
        detail = f"（finish_reason={exc.finish_reason}）" if exc.finish_reason else ""
        return LLMErrorSemantics(
            "empty_response", f"空响应{detail}", same_identity_retry=True,
            same_account_other_models=True, independent_provider=True,
        )
    if isinstance(exc, LLMProtocolError):
        # 含 RequestTooLarge/Projection: 本地协议/投影事实，非 provider 可用性
        return LLMErrorSemantics("protocol", "协议错误（本地投影/解析）")
    if not isinstance(exc, LLMHTTPError):
        return LLMErrorSemantics("unknown", "未知错误")

    code = _error_code_facts(exc)
    provider = (getattr(exc, "provider", "") or "").lower()
    glm_family = provider in _GLM_FAMILY_PROVIDERS
    code_part = f"（业务码 {code}）" if code else ""

    # GLM 族业务码语义（先例: 码判定仅限 GLM 族，见 _GLM_OVERFLOW_PROVIDERS）
    if glm_family and code in _GLM_RATE_LIMIT_CODES:
        return LLMErrorSemantics(
            "rate_limit", f"限流（GLM {code}）", provider_code=code,
            same_identity_retry=True, same_account_other_models=True,
            independent_provider=True,
        )
    if glm_family and code in _GLM_MODEL_PERMISSION_CODES:
        # 1311 针对所选模型: 同身份重试无意义，但订阅内其他模型/其他 provider 可能可用
        return LLMErrorSemantics(
            "model_permission", f"模型权限受限（GLM {code}，订阅未含所选模型）",
            provider_code=code, same_identity_retry=False,
            same_account_other_models=True, independent_provider=True,
        )
    if glm_family and code in _GLM_ACCOUNT_BILLING_CODES:
        return LLMErrorSemantics(
            "account_billing", f"账户欠费（GLM {code}）", provider_code=code,
        )
    # 配额耗尽模式（与 is_quota_error 消费同一份 body/status 事实）
    if is_quota_error(exc):
        return LLMErrorSemantics(
            "account_billing", "配额/欠费（账户级，本周期不可恢复）",
            provider_code=code,
        )

    if isinstance(exc, LLMStreamProviderError):
        # 流内错误: HTTP 已成功（2xx），语义来自业务码/错误类型
        lc = (code or "").lower()
        if lc in _STREAM_RATE_LIMIT_TYPES:
            return LLMErrorSemantics(
                "rate_limit", f"流内限流（{code}）", provider_code=code,
                same_identity_retry=True, same_account_other_models=True,
                independent_provider=True,
            )
        if lc in _STREAM_SERVER_TYPES:
            return LLMErrorSemantics(
                "server_error", f"流内服务错误（{code}）", provider_code=code,
                same_identity_retry=True, same_account_other_models=True,
                independent_provider=True,
            )
        if lc in _STREAM_CLIENT_TYPES:
            return LLMErrorSemantics(
                "client_error", f"流内请求错误（{code}）", provider_code=code,
            )
        if code and code.isdigit():
            n = int(code)
            if 400 <= n <= 599:  # HTTP 形码（如 Google error.code 503）
                if n == 429:
                    return LLMErrorSemantics(
                        "rate_limit", f"流内限流（{code}）", provider_code=code,
                        same_identity_retry=True, same_account_other_models=True,
                        independent_provider=True,
                    )
                if n >= 500:
                    return LLMErrorSemantics(
                        "server_error", f"流内服务错误（{code}）", provider_code=code,
                        same_identity_retry=True, same_account_other_models=True,
                        independent_provider=True,
                    )
                return LLMErrorSemantics(
                    "client_error", f"流内请求错误（{code}）", provider_code=code,
                )
        # 未知流内错误: 如实反馈，不发明语义
        return LLMErrorSemantics(
            "unknown", f"流内错误{code_part}（HTTP {exc.status_code}）",
            provider_code=code,
        )

    # HTTP 层事实
    if exc.status_code == 429:
        # 未知业务码: 保留码事实于标签，HTTP 429 的机械事实仍是限流
        label_429 = "限流（HTTP 429）" + (f"业务码 {code}" if code else "")
        return LLMErrorSemantics(
            "rate_limit", label_429,
            provider_code=code, same_identity_retry=True,
            same_account_other_models=True, independent_provider=True,
        )
    if exc.status_code >= 500:
        return LLMErrorSemantics(
            "server_error", f"HTTP {exc.status_code} 上游错误", provider_code=code,
            same_identity_retry=True, same_account_other_models=True,
            independent_provider=True,
        )
    if exc.status_code >= 400:
        return LLMErrorSemantics(
            "client_error", f"HTTP {exc.status_code}", provider_code=code,
        )
    return LLMErrorSemantics("unknown", f"HTTP {exc.status_code}", provider_code=code)
