"""统一消息结构：用户/工具/助手三类同构承载（design.md §2.2.2.1）.

设计要点:
- FR-MSG-01: user/tool/assistant 同构，循环内同等处理
- FR-MSG-04: source 来源标识（user/tool/memory/system）
- 约束 C2: tool 消息 content 恒为非空字符串
- tool_call_id 由程序统一管理（约束 C1），与 LLM 声明严格绑定
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

_ATTACHMENT_TOTAL_EXCERPT_CHARS = 4_000


def _project_user_attachments(content: str, metadata: dict) -> str:
    """Mechanically project durable attachment facts for provider visibility only.

    Raw ``Message.content`` remains the exact human text. Attachment metadata is
    rendered in stable request order; no semantic selection, summary, or advice is
    introduced here. Excerpts use one shared representation budget.
    """
    raw = metadata.get("attachments") if isinstance(metadata, dict) else None
    if not isinstance(raw, list) or not raw:
        return content
    rows: list[str] = []
    excerpt_budget = _ATTACHMENT_TOTAL_EXCERPT_CHARS
    for item in raw:
        if not isinstance(item, dict):
            continue
        fact = {
            "ref": str(item.get("ref") or ""),
            "filename": str(item.get("filename") or ""),
            "content_type": str(item.get("content_type") or ""),
            "media_type": str(item.get("media_type") or ""),
            "size_bytes": int(item.get("size_bytes") or 0),
            "sha256": str(item.get("sha256") or ""),
        }
        excerpt = str(item.get("excerpt") or "")
        shown = excerpt[:excerpt_budget] if excerpt_budget > 0 else ""
        excerpt_budget -= len(shown)
        if excerpt:
            fact["excerpt_kind"] = str(item.get("excerpt_kind") or "")
            fact["excerpt_chars_shown"] = len(shown)
            fact["excerpt_total_chars"] = len(excerpt)
            fact["excerpt"] = shown
        rows.append(json.dumps(fact, ensure_ascii=False, sort_keys=True))
    if not rows:
        return content
    block = "[attachment_facts]\n" + "\n".join(rows) + "\n[/attachment_facts]"
    return f"{content}\n\n{block}" if content else block

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
    UNAUTHORIZED = "unauthorized"  # 缺真实用户/系统授权（任务恢复授权缺失/拒绝）


class RecoverabilityStatus(StrEnum):
    """Evidence durability is orthogonal to the source action result."""

    NOT_CONFIGURED = "not_configured"
    RECORDED = "recorded"
    FAILED = "failed"


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
    llm_ms: float = 0.0  # M59: 本轮 run LLM 调用总耗时（毫秒；0=未记录）
    ttft_ms: float = 0.0  # M59: 首 token 延迟（毫秒；0=未记录/无文本）
    duration_ms: float = 0.0  # M59: 工具执行耗时（毫秒，tool 消息）
    ts: float = field(
        default_factory=time.time
    )  # 消息时间戳（epoch 秒；web 端时间显示，缺省=创建时）
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
        wire_content = self.content
        if self.role == "user":
            wire_content = _project_user_attachments(self.content, self.metadata or {})
        d: dict = {"role": self.role, "content": wire_content}
        if self.role == "assistant" and self.tool_calls:
            d["tool_calls"] = self.tool_calls
        # M20 THK-04: 思考链非空才回传（缺失态 None 不回传 → 零回归；官方"携带 tools 必须完整回传"）
        if self.role == "assistant" and self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content
        # Internal marker only: LLMClient projects this opaque state to a
        # whitelisted provider-native field before guard/fingerprint/send. It is
        # never sent as `_provider_replay` on the wire.
        if self.role == "assistant":
            replay = (self.metadata or {}).get("provider_replay")
            if isinstance(replay, dict):
                d["_provider_replay"] = replay
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
    # ERC Phase2 shadow-only: pre-projection observation retained only when the explicit
    # shadow context is enabled. to_message()/to_llm_dict() never expose this field.
    raw_observation: str | None = None
    # ERC Phase3: recoverability is independent from action status.  These structured
    # fields are copied to Message.metadata; the deterministic capsule in content is the
    # model-visible recovery handle because Message.metadata does not go on the LLM wire.
    recoverability_status: RecoverabilityStatus = RecoverabilityStatus.NOT_CONFIGURED
    evidence_ref: str | None = None
    evidence_representation: str | None = None
    evidence_projection_complete: bool | None = None
    # Internal capture metadata; never sent to the model directly.  A probeable source can
    # later be compared against this token without re-executing the source action.
    evidence_source_version_token: str | None = None
    # ERC R9: distinguish logical source resolution from physical acquisition.
    source_resolution_mode: str | None = None
    source_execution_performed: bool | None = None
    # R8.24-C C-D4: capsule metadata-only 投影（LFL_EVIDENCE_CAPSULE=off）时补齐
    # capsule 六字段中的 source/coverage 两项（ref/representation/complete 已有结构化
    # 字段）；默认 None 零回归（on/shadow 模式不写——capsule 本体已承载）。
    evidence_source_label: str | None = None
    evidence_coverage_label: str | None = None
    # Canonical EvidenceRecord origin facts. Metadata-only until an explicit provider
    # representation (for example a folded receipt) chooses to expose them. Runtime
    # reports source identity/version/provenance only; it never decides task applicability.
    evidence_origin_facts: dict[str, object] | None = None
    # R8.24-C C-D7: read_file 对 evidence:// 引用的参数误用短路标记（事件/审计面）。
    short_circuit_kind: str | None = None
    # EVO-d78b270c: 经验驱动注入（M41 升级）——registry 失败时按错误关键词检索
    # MemoryStore，命中 procedure 经验条目的【已验解法】段写入此字段，tool 消息带出。
    # 默认空串 = 零回归（无经验库/未命中时行为与旧版完全一致）。
    guidance_extra: str = ""
    # R8.7: structured recovery advice is internal metadata plus compact model-facing text.
    # Concrete type lives in llm_loop.tools.recovery to avoid a core->tools import cycle.
    recovery_advice: Any | None = None
    # LFL Agency First P0-2: 执行层结构化结果指纹（同一调用+同指纹才判无进展）。
    # 由工具执行层给出，不进 prose 推断；默认 None = 未提供（零回归）。
    result_fingerprint: str | None = None
    # P1-B: tool-produced capability facts remain durable metadata only. They may
    # describe a capability named by the receipt, but never select/hide/promote tools.
    capability_requirements: tuple[str, ...] = ()
    # 组合/子代理工具的嵌套成功证据，仅供声明-回执校验与审计消费；不进 LLM wire。
    # 例: ("execute_command:success", "read_file:success")。只允许真实 SUCCESS
    # 子动作进入，失败/阻断不得借外层 SUCCESS 冒充已完成。
    verification_receipts: tuple[str, ...] = ()
    # ST2-C2: provider-invisible mechanical binding for SubAgent settlement.
    # It carries identity/fencing facts only; Message.to_llm_dict() never projects metadata.
    subagent_settlement: dict[str, str] | None = None

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
        metadata: dict = {}
        if self.recoverability_status is not RecoverabilityStatus.NOT_CONFIGURED:
            metadata["recoverability_status"] = self.recoverability_status.value
            if self.evidence_ref:
                metadata["evidence_ref"] = self.evidence_ref
            if self.evidence_representation is not None:
                metadata["evidence_representation"] = self.evidence_representation
            if self.evidence_projection_complete is not None:
                metadata["evidence_projection_complete"] = self.evidence_projection_complete
        if self.source_resolution_mode is not None:
            metadata["source_resolution_mode"] = self.source_resolution_mode
        if self.verification_receipts:
            metadata["verification_receipts"] = list(self.verification_receipts)
        if self.subagent_settlement is not None:
            metadata["subagent_settlement"] = dict(self.subagent_settlement)
        if self.source_execution_performed is not None:
            metadata["source_execution_performed"] = self.source_execution_performed
        # R8.24-C: capsule metadata-only 审计补充字段 + 短路标记（默认缺省不写，零回归）
        if self.evidence_source_label is not None:
            metadata["evidence_source_label"] = self.evidence_source_label
        if self.evidence_coverage_label is not None:
            metadata["evidence_coverage_label"] = self.evidence_coverage_label
        if self.evidence_origin_facts is not None:
            metadata["evidence_origin_facts"] = dict(self.evidence_origin_facts)
        if self.short_circuit_kind is not None:
            metadata["short_circuit_kind"] = self.short_circuit_kind
        if self.recovery_advice is not None:
            to_dict = getattr(self.recovery_advice, "to_dict", None)
            if callable(to_dict):
                metadata["tool_recovery"] = to_dict()
        if self.result_fingerprint is not None:
            metadata["result_fingerprint"] = self.result_fingerprint
        # R2 No Unreachable Advice: 回执指名能力留痕（对账证据，不进 LLM wire）
        if self.capability_requirements:
            metadata["capability_requirements"] = list(self.capability_requirements)
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
            duration_ms=self.duration_ms,
            metadata=metadata,
        )
