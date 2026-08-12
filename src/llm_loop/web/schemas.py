"""Web 请求/响应 Pydantic 模型（M36 薄壳适配器）。

ChatResponse 六字段与 core.loop.LoopResult 六字段一一对应（如实透传）。
仅格式校验（Pydantic 类型约束），不新增业务校验。
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求（POST /api/v1/chat body）."""

    message: str = Field(min_length=1, description="用户消息，必填非空字符串")
    session_id: str | None = Field(default=None, description="会话 ID，可选；不传则新建会话")
    model: str | None = Field(default=None, description="模型名，可选；不传用装配默认模型")


class ChatResponse(BaseModel):
    """对话响应（LoopResult 七字段如实透传, M51 增 model_used）."""

    session_id: str
    final_answer: str
    verification_note: str | None = None
    rounds: int = 0
    tool_calls: list[dict] = []
    truncated: bool = False
    model_used: str = ""  # M51: 实际生成回复的模型标签（provider/model）
    tokens_in: int = 0  # M52: 本轮 prompt tokens（0 = provider 未提供）
    tokens_out: int = 0  # M52: 本轮 completion tokens


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


class MessageItem(BaseModel):
    """会话消息条目（刷新后恢复对话用）."""

    role: str
    content: str
    tool_call_id: str | None = None  # M52: tool 消息透出（web 端"展开原文"精确定位档案）


class SessionMessagesResponse(BaseModel):
    """会话历史消息响应."""

    session_id: str
    messages: list[MessageItem]


class ErrorResponse(BaseModel):
    """错误响应（错误类型 + 原因/引导建议，如实可检索）."""

    error: str
    detail: str


class UploadRequest(BaseModel):
    """上传请求（POST /api/v1/upload body，JSON/base64 传输）."""

    filename: str = Field(min_length=1, description="文件名（含扩展名）")
    data: str = Field(min_length=1, description="文件内容（base64 编码）")


class UploadResponse(BaseModel):
    """上传处理响应（来源可追溯 + 状态如实）."""

    source_filename: str
    content_type: str
    status: str  # ok / degraded / pending / error
    result_text: str = ""
    detail: str = ""
    truncated: bool = False
