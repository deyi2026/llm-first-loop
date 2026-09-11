"""Web 请求/响应 Pydantic 模型（M36 薄壳适配器）。

ChatResponse 六字段与 core.loop.LoopResult 六字段一一对应（如实透传）。
仅格式校验（Pydantic 类型约束），不新增业务校验。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ChatAttachmentRef(BaseModel):
    """客户端仅回传服务端签发的 opaque attachment ref。"""

    model_config = ConfigDict(extra="forbid")
    ref: str = Field(pattern=r"^attachment://[0-9a-f]{32}$", description="服务端上传接口签发的附件引用")


class ChatRequest(BaseModel):
    """对话请求（POST /api/v1/chat body）."""

    message: str = Field(default="", description="用户原始消息；纯附件消息可为空")
    attachments: list[ChatAttachmentRef] = Field(
        default_factory=list,
        max_length=20,
        description="服务端签发的附件引用；客户端不传 path/hash；单请求最多20个",
    )
    session_id: str | None = Field(default=None, description="会话 ID，可选；不传则新建会话")
    new_session: bool = Field(default=False, description="2026-08-18: true=强制新建会话（/new 语义——前端清 currentSessionId 但后端复用共享当前导致'新开不成功'）；与 session_id 互斥（同传时 new_session 优先）")
    model: str | None = Field(default=None, description="模型名，可选；不传用装配默认模型")
    reasoning_effort: str | None = Field(default=None, description="推理等级（low/medium/high），可选；不传用装配默认")
    reasoning_mode: Literal["auto", "off", "on"] = Field(
        default="auto",
        description="reasoning 模式：auto=尊重 provider/operator 默认，off/on=本请求显式关闭/开启",
    )
    resume: bool = Field(default=False, description="EVO 后台 run：true=不提交新 run，订阅已有 run（刷新/切回）")
    queue_id: str | None = Field(
        default=None,
        description="排队派发标记：本次 run 承接该排队项，run 终态时回写队列状态（completed/failed）",
    )

    @model_validator(mode="after")
    def _require_human_payload(self) -> "ChatRequest":
        if not self.message and not self.attachments:
            raise ValueError("message 或 attachments 至少提供一项")
        if self.resume and self.attachments:
            raise ValueError("resume 仅用于恢复订阅，不能携带新的 attachments")
        return self


class ChatResponse(BaseModel):
    """对话响应（LoopResult 七字段如实透传, M51 增 model_used）."""
    session_id: str
    final_answer: str
    verification_note: str | None = None
    rounds: int = 0
    tool_calls: list[dict] = []
    truncated: bool = False
    model_used: str = ""  # M51: 实际生成回复的模型标签（provider/model）
    fallback_receipt: dict[str, str] | None = None  # current-user runtime fact; never prompt history
    tokens_in: int = 0  # M52: 本轮 prompt tokens（0 = provider 未提供）
    tokens_out: int = 0  # M52: 本轮 completion tokens
    tokens_cache_hit: int = 0  # M58: 本轮前缀缓存命中 token（0=未提供/未命中）
    reasoning_content: str | None = None  # P1-1: 最终回答轮思考链透传（缺失/思考模式关闭为 None）
    reasoning_mode: str = "auto"
    reasoning_capable: bool = False
    reasoning_control: str = "unknown"
    reasoning_supported: bool = False
    reasoning_effective: bool = False
    reasoning_tokens: int | None = None


class ChatCancelRequest(BaseModel):
    """停止请求（POST /api/v1/chat/cancel body，2026-08-23 停止按钮修复）."""

    session_id: str = Field(description="要停止的会话 ID（必填）")


class QueueEnqueueRequest(BaseModel):
    """排队入队（POST /api/v1/chat/queue body）：生成中 Cmd/Ctrl+Enter 插话."""

    session_id: str = Field(description="目标会话 ID（必填）")
    message: str = Field(default="", description="排队消息原文；纯附件可为空")
    attachments: list[ChatAttachmentRef] = Field(
        default_factory=list,
        max_length=20,
        description="服务端签发的附件引用（入队时冻结）",
    )
    model: str | None = Field(default=None, description="排队时的模型选择（冻结）")
    reasoning_effort: str | None = Field(default=None, description="排队时的推理等级（冻结）")
    reasoning_mode: Literal["auto", "off", "on"] = Field(
        default="auto", description="排队时的 reasoning 模式（冻结）"
    )

    @model_validator(mode="after")
    def _require_payload(self) -> "QueueEnqueueRequest":
        if not self.message and not self.attachments:
            raise ValueError("message 或 attachments 至少提供一项")
        return self


class QueueCancelRequest(BaseModel):
    """取消排队项（DELETE /api/v1/chat/queue body）."""

    session_id: str = Field(description="目标会话 ID")
    queue_id: str = Field(description="要取消的排队项 ID")


class QueueDispatchRequest(BaseModel):
    """派发领取（POST /api/v1/chat/queue/dispatch body）：原子领取队首 queued 项."""

    session_id: str = Field(description="目标会话 ID")


class QueueReleaseRequest(BaseModel):
    """领取方回滚（POST /api/v1/chat/queue/release body）：claimed→queued."""

    session_id: str = Field(description="目标会话 ID")
    queue_id: str = Field(description="要回滚的排队项 ID")


class SessionMetaItem(BaseModel):
    """会话元数据条目（对齐 CLI list 输出语义）."""

    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    status: str
    last_message_preview: str = ""
    pinned: bool = False   # M56: 置顶（Web 端列表置顶优先）
    channel: str = "web"   # M56: 来源通道（web / feishu:p2p:* / feishu:group:*）


class SessionListResponse(BaseModel):
    """会话列表响应."""

    sessions: list[SessionMetaItem]
    count: int


class AttachmentFactItem(BaseModel):
    """历史/UI 可见的附件事实；明确不含宿主机路径与提取正文。"""

    ref: str
    filename: str
    content_type: str = ""
    media_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    created_at: float = 0.0


class MessageItem(BaseModel):
    """会话消息条目（刷新后恢复对话用）."""

    role: str
    content: str
    tool_call_id: str | None = None  # M52: tool 消息透出（web 端"展开原文"精确定位档案）
    status: str | None = None  # tool receipt 结构化终态；非 tool/旧消息缺省 None
    tool_name: str | None = None  # tool receipt 机械工具名；不从正文反推
    duration_ms: float = 0.0  # tool receipt 机械耗时；旧消息缺省 0
    reasoning_content: str | None = None  # P1-1: assistant 消息思考链透传（历史会话恢复渲染）
    model_used: str = ""  # M51: assistant 消息模型标签透传（页脚显示）
    tokens_in: int = 0  # M52: assistant 消息 prompt tokens 透传
    tokens_out: int = 0  # M52: assistant 消息 completion tokens 透传
    tokens_cache_hit: int = 0  # M58: 前缀缓存命中 token
    ts: float = 0.0  # 消息时间戳（epoch 秒；web 端时间显示，旧消息缺省 0）
    tool_calls: list[dict] | None = None  # assistant 工具声明透传（历史恢复出产物/正文链接）
    attachments: list[AttachmentFactItem] = Field(default_factory=list)


class SessionMessagesResponse(BaseModel):
    """会话历史消息响应."""

    session_id: str
    messages: list[MessageItem]
    has_more: bool = False  # D2: 是否还有更早消息（分页用，旧客户端忽略）
    total: int = 0  # D2: 会话消息总数（分页用，旧客户端忽略）


class WorkspaceRequest(BaseModel):
    """工作区注册请求（Open 语义：注册即切换）."""

    path: str = Field(min_length=1, description="要打开的目录绝对路径")


class WorkspaceSwitchRequest(BaseModel):
    """工作区切换请求."""

    id: str = Field(min_length=1, description="已注册工作区 id")


class ErrorResponse(BaseModel):
    """错误响应（错误类型 + 原因/引导建议，如实可检索）."""

    error: str
    detail: str


class UploadRequest(BaseModel):
    """上传请求（POST /api/v1/upload body，JSON/base64 传输）."""

    filename: str = Field(min_length=1, max_length=512, description="文件名（含扩展名）")
    data: str = Field(min_length=1, description="文件内容（base64 编码）")


class WorkspaceAttachmentImportRequest(BaseModel):
    """Import one existing current-workspace file as a durable attachment ref."""

    path: str = Field(min_length=1, max_length=2048, description="当前工作区内文件路径")


class FeedbackRequest(BaseModel):
    """消息反馈（POST /api/v1/sessions/{id}/feedback，2026-08-15 对齐 DSH ui-message-feedback）."""

    message_index: int = Field(ge=0, description="会话内消息下标（含 user/assistant 全部角色）")
    feedback: str = Field(description="up / down")
    note: str = Field(default="", max_length=500, description="可选补充说明")


class UploadResponse(BaseModel):
    """上传处理响应（来源可追溯 + durable opaque ref + 兼容提取文本）."""

    source_filename: str
    content_type: str
    status: str  # ok / degraded / pending / error
    result_text: str = ""
    detail: str = ""
    truncated: bool = False
    attachment_ref: str = ""
    size_bytes: int = 0
    sha256: str = ""
    excerpt: str = ""


class ProviderModelAdminInput(BaseModel):
    """Strict operator-supplied model registry entry; no semantic capability inference."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    context: int = Field(default=131072, ge=1024, le=8_000_000)
    max_input_tokens: int | None = Field(default=None, ge=1, le=8_000_000)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    cost_tier: str = Field(default="mid", min_length=1, max_length=32)
    thinking: bool = False
    reasoning_capable: bool = False
    reasoning_control: Literal[
        "legacy", "unknown", "none", "thinking_type", "chat_template", "always_on_effort"
    ] = "unknown"
    reasoning: bool = False
    long_context: bool = False
    multimodal: bool = False
    wire_protocol: Literal["openai", "anthropic", "google", "lms-chat"] = "openai"
    capability_tier: Literal["strong", "weak", "unknown"] = "unknown"
    send_tool_choice: bool = True
    reasoning_split: bool = False
    reasoning_replay: Literal["configured", "none", "tool_calls", "full"] = "configured"
    reasoning_effort_map: dict[str, str] = Field(default_factory=dict)
    runtime_identity: str = Field(default="", max_length=256)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    top_k: int | None = Field(default=None, ge=0)
    min_p: float | None = Field(default=None, ge=0, le=1)

    @field_validator("id")
    @classmethod
    def _model_id_is_wire_safe(cls, value: str) -> str:
        if value != value.strip() or any(ord(ch) < 32 or ch.isspace() for ch in value):
            raise ValueError("model id 不得包含空白/控制字符")
        return value

    @field_validator("reasoning_effort_map")
    @classmethod
    def _effort_map_is_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"low", "medium", "high", "max", "xhigh"}
        if len(value) > len(allowed):
            raise ValueError("reasoning_effort_map 条目过多")
        out: dict[str, str] = {}
        for key, mapped in value.items():
            k = str(key).strip().lower()
            v = str(mapped).strip().lower()
            if k not in allowed or not v or len(v) > 32 or any(ch.isspace() for ch in v):
                raise ValueError("reasoning_effort_map 含非法条目")
            out[k] = v
        return out


class ProviderAdminProviderInput(BaseModel):
    """Strict provider config persisted to the local snapshot; credential plaintext is separate."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    enabled: bool = True
    base_url: str = Field(min_length=8, max_length=2048)
    api_key_env: str = Field(default="", max_length=128)
    default_model: str = Field(default="", max_length=160)
    timeout_s: float | None = Field(default=None, gt=0, le=7200)
    history_budget_chars: int | None = Field(default=None, ge=1000, le=100_000_000)
    max_input_tokens: int | None = Field(default=None, ge=1, le=8_000_000)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    chars_per_token: float | None = Field(default=None, gt=0, le=16)
    models: list[ProviderModelAdminInput] = Field(default_factory=list, max_length=200)

    @field_validator("base_url")
    @classmethod
    def _base_url_http_only(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url 仅接受带主机名的 http/https URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url 不得内嵌用户名/密码")
        return value.strip().rstrip("/")

    @field_validator("api_key_env")
    @classmethod
    def _api_key_env_name(cls, value: str) -> str:
        import re

        value = value.strip()
        if value and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value) is None:
            raise ValueError("api_key_env 必须是合法环境变量名")
        return value

    @model_validator(mode="after")
    def _provider_model_contract(self) -> "ProviderAdminProviderInput":
        ids = [item.id for item in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("同一 provider 下 model id 不得重复")
        if self.enabled and not any(item.enabled for item in self.models):
            raise ValueError("启用的 provider 至少需要一个启用模型")
        if self.default_model:
            matching = next((item for item in self.models if item.id == self.default_model), None)
            if matching is None:
                raise ValueError("default_model 必须存在于 models")
            if self.enabled and not matching.enabled:
                raise ValueError("启用 provider 的 default_model 不能指向停用模型")
        return self


class ProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(min_length=1, max_length=128)
    provider: ProviderAdminProviderInput
    api_key: SecretStr | None = None


class ProviderReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(min_length=1, max_length=128)
    provider: ProviderAdminProviderInput


class ProviderCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(description="仅写入本机 .env；永不回显/日志化")


class ProviderModelMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(min_length=1, max_length=128)
    model: ProviderModelAdminInput


class ProviderDefaultModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=256)

    @field_validator("model")
    @classmethod
    def _canonical_model_ref(cls, value: str) -> str:
        value = value.strip()
        if "/" not in value or any(ch.isspace() for ch in value):
            raise ValueError("默认模型必须使用 provider/model 全限定引用")
        return value


class ProviderTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="", max_length=160)


class EvolutionReviewRequest(BaseModel):
    """web 演进建议审批（POST /api/v1/evolution/review，EVO-20260818）."""

    id: str = Field(min_length=4, description="演进建议 ID（EVO-xxx）")
    decision: str = Field(pattern="^(accepted|rejected)$", description="accepted / rejected")
    reason: str = Field(default="", max_length=500, description="拒绝理由（拒绝必填）")
    expected_status: str = Field(
        default="", description="乐观锁: 客户端当前看到的 status，CAS 校验（Approval UX v2 批 1）"
    )
    extra_confirm: bool = Field(
        default=False,
        description="涉边界项（requires_human）单条批准额外确认标志（Approval UX v2 批 1，验证清单 #9）",
    )


class HumanFileObserveRequest(BaseModel):
    """Explicit authenticated-human physical file observation."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024, description="当前工作区内相对路径")
    offset: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1, le=5000)


class HumanFileEditRequest(BaseModel):
    """Version-protected authenticated-human full-text save."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    path: str = Field(min_length=1, max_length=1024, description="当前工作区内相对路径")
    expected_snapshot_ref: str = Field(pattern=r"^artifact://v1/[0-9a-f]{32}$")
    content: str = Field(max_length=1_048_576)
    file_contract_version: Literal[1] = 1
