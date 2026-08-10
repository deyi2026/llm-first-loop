"""Web 请求/响应 Pydantic 模型（M36 薄壳适配器）。

ChatResponse 六字段与 core.loop.LoopResult 六字段一一对应（如实透传）。
仅格式校验（Pydantic 类型约束），不新增业务校验。
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求（POST /api/v1/chat body）."""

    message: str = Field(min_length=1, description="用户消息，必填非空字符串")
    session_id: str | None = Field(default=None, description="会话 ID，可选；不传则新建会话")


class ChatResponse(BaseModel):
    """对话响应（LoopResult 六字段如实透传）."""

    session_id: str
    final_answer: str
    verification_note: str | None = None
    rounds: int = 0
    tool_calls: list[dict] = []
    truncated: bool = False


class SessionMetaItem(BaseModel):
    """会话元数据条目（对齐 CLI list 输出语义）."""

    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    status: str
    last_message_preview: str = ""


class SessionListResponse(BaseModel):
    """会话列表响应."""

    sessions: list[SessionMetaItem]
    count: int


class ErrorResponse(BaseModel):
    """错误响应（错误类型 + 原因/引导建议，如实可检索）."""

    error: str
    detail: str
