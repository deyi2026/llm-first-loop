"""Web 请求/响应 Pydantic 模型（M36 薄壳适配器）。

ChatResponse 六字段与 core.loop.LoopResult 六字段一一对应（如实透传）。
仅格式校验（Pydantic 类型约束），不新增业务校验。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatAttachmentRef(BaseModel):
    """客户端仅回传服务端签发的 opaque attachment ref。"""

    model_config = ConfigDict(extra="forbid")
    ref: str = Field(
        pattern=r"^attachment://[0-9a-f]{32}$", description="服务端上传接口签发的附件引用"
    )


class ChatRequest(BaseModel):
    """对话请求（POST /api/v1/chat body）."""

    message: str = Field(default="", description="用户原始消息；纯附件消息可为空")
    attachments: list[ChatAttachmentRef] = Field(
        default_factory=list,
        max_length=20,
        description="服务端签发的附件引用；客户端不传 path/hash；单请求最多20个",
    )
    session_id: str | None = Field(default=None, description="会话 ID，可选；不传则新建会话")
    new_session: bool = Field(
        default=False,
        description="2026-08-18: true=强制新建会话（/new 语义——前端清 currentSessionId 但后端复用共享当前导致'新开不成功'）；与 session_id 互斥（同传时 new_session 优先）",
    )
    model: str | None = Field(default=None, description="模型名，可选；不传用装配默认模型")
    reasoning_effort: str | None = Field(
        default=None, description="推理等级（low/medium/high），可选；不传用装配默认"
    )
    reasoning_mode: Literal["auto", "off", "on"] = Field(
        default="auto",
        description="reasoning 模式：auto=尊重 provider/operator 默认，off/on=本请求显式关闭/开启",
    )
    resume: bool = Field(
        default=False, description="EVO 后台 run：true=不提交新 run，订阅已有 run（刷新/切回）"
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
    fallback_receipt: dict[str, str] | None = (
        None  # current-user runtime fact; never prompt history
    )
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


class SessionMetaItem(BaseModel):
    """会话元数据条目（对齐 CLI list 输出语义）."""

    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    status: str
    last_message_preview: str = ""
    pinned: bool = False  # M56: 置顶（Web 端列表置顶优先）
    channel: str = "web"  # M56: 来源通道（web / feishu:p2p:* / feishu:group:*）


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
