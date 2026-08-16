"""统一消息结构：用户/工具/助手三类同构承载（design.md §2.2.2.1）.

设计要点:
- FR-MSG-01: user/tool/assistant 同构，循环内同等处理
- FR-MSG-04: source 来源标识（user/tool/memory/system）
- 约束 C2: tool 消息 content 恒为非空字符串
- tool_call_id 由程序统一管理（约束 C1），与 LLM 声明严格绑定
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class MessageSource(StrEnum):
    """消息来源标识（FR-MSG-04）."""

    USER = "user"
    TOOL = "tool"
    MEMORY = "memory"
    SYSTEM = "system"


class ToolResultStatus(StrEnum):
    """工具执行结果如实状态（数据约束 6.2，禁止伪装成功）."""

    SUCCESS = "success"  # 执行成功
    FAILURE = "failure"  # 业务失败（如文件不存在）
    ERROR = "error"  # 异常
    TIMEOUT = "timeout"  # 超时（含部分结果）
    BLOCKED = "blocked"  # 灾难性安全硬阻断


@dataclass(frozen=True)
class ToolCall:
    """LLM 声明的工具调用（tool_call_id 由程序统一管理生命周期）.

    design.md §2.2.2.1: 流式聚合后 id 必为非空，校验通过才执行。
    """

    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    """统一消息结构（FR-MSG-01）.

    同构承载 user/assistant/tool/system 四类消息；tool 消息通过
    tool_call_id/status/tool_name/error_detail 如实承载执行反馈。
    """

    role: Literal["user", "assistant", "tool", "system"]
    content: str
    source: MessageSource
    tool_call_id: str | None = None  # 仅 tool 消息：与声明严格绑定（约束 C1）
    status: ToolResultStatus | None = None  # 仅 tool 消息：如实执行状态
    tool_name: str | None = None  # 仅 tool 消息：来源工具名
    error_detail: str | None = None  # 仅失败/异常/阻断：完整错误描述（FR-FBK-02）
    tool_calls: list[dict] | None = None  # 仅 assistant 消息：LLM 工具声明（约束 C1 配对）
    reasoning_content: str | None = (
        None  # M20 THK-04: 仅 assistant 消息思考链（协议回传用，不注入 prompt）
    )
    model_used: str = ""  # M51: 仅 assistant 消息：实际生成模型标签（provider/model）
    tokens_in: int = 0  # M52: 仅 assistant 消息：本轮 run 累计 prompt tokens
    tokens_out: int = 0
    tokens_cache_hit: int = 0  # M58: 本轮 run 前缀缓存命中 token（0=未提供/未命中）
    metadata: dict = field(default_factory=dict)  # 截断标注/降级标注等

    def to_llm_dict(self) -> dict:
        """转为提交 LLM 的协议消息.

        tool 消息: {role, tool_call_id, content}; 其余: {role, content}。
        assistant 消息带 tool_calls 时原样输出（约束 C1: 声明与后续 tool 回执配对）。
        tool 消息 content 恒为非空（约束 C2），由构造方保证。
        """
        if self.role == "tool":
            d: dict = {
                "role": "tool",
                "tool_call_id": self.tool_call_id or "",
                "content": self.content,
            }
            if self.tool_name:
                d["name"] = self.tool_name
            return d
        d: dict = {"role": self.role, "content": self.content}
        if self.role == "assistant" and self.tool_calls:
            d["tool_calls"] = self.tool_calls
        # M20 THK-04: 思考链非空才回传（缺失态 None 不回传 → 零回归；官方"携带 tools 必须完整回传"）
        if self.role == "assistant" and self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content
        return d


@dataclass
class ToolResult:
    """工具执行结果（五态 + tool_call_id 绑定，数据约束 6.2）.

    design.md §2.2.2.2 / §2.1.3.3 机制二。
    """

    status: ToolResultStatus
    content: str  # 成功=真实结果；失败=完整错误（FR-FBK-02）
    tool_call_id: str
    tool_name: str
    error_type: str | None = None  # 异常类型（ERROR 时）
    error_detail: str | None = None  # 完整错误描述（类型+原因+上下文）
    partial_output: str | None = None  # 超时时的部分结果（TIMEOUT 时）
    duration_ms: float = 0.0
    # EVO-d78b270c: 经验驱动注入（M41 升级）——registry 失败时按错误关键词检索
    # MemoryStore，命中 procedure 经验条目的【已验解法】段写入此字段，tool 消息带出。
    # 默认空串 = 零回归（无经验库/未命中时行为与旧版完全一致）。
    guidance_extra: str = ""

    def to_message(self) -> Message:
        """构造为 tool 消息（如实承载状态，AI 视角：状态结构化呈现）.

        约束 C2: content 恒为非空；失败/异常保留完整错误。
        AI-first（T21）: content 前置显式状态标注（`[状态: failure]`），
        AI 无需从文本推断执行状态，可直接决策。
        """
        status_label = self.status.value if self.status else "unknown"
        content = f"[状态: {status_label}] {self.content}"
        if self.status == ToolResultStatus.ERROR and self.error_detail:
            content = f"{content}\n[错误详情] {self.error_detail}"
        elif self.status == ToolResultStatus.TIMEOUT and self.partial_output:
            content = f"{content}\n[部分结果] {self.partial_output}"
        elif self.status == ToolResultStatus.BLOCKED and self.error_detail:
            content = f"{content}\n[阻断依据] {self.error_detail}"
        return Message(
            role="tool",
            content=content
            if content.strip()
            else f"[{self.tool_name} 执行{self.status.value}]（无输出）",
            source=MessageSource.TOOL,
            tool_call_id=self.tool_call_id,
            status=self.status,
            tool_name=self.tool_name,
            error_detail=self.error_detail,
        )
