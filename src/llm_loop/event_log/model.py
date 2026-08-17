"""D1 事件模型与类型登记表（design.md §2.2.2-A / §2.3.2）.

事件是 append-only 的不可变事实单元：`event_id` 全局唯一（uuid4 hex）、
`session_id` 必填落盘（修复割裂点 A：审计流反向关联会话）、`seq` 会话内从 1 单调递增、
`type` 在登记表中可见、`ts` ISO 时间戳（UTC）、`payload` 缺失字段如实置空不伪造。

全部为无状态纯函数（serialize/parse/validate），可先行单测。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# ── 事件类型登记（spec §5.2.1 / design.md §2.3.2）──

EVENT_SESSION_CREATED = "session.created"
EVENT_MESSAGE_APPENDED = "message.appended"
EVENT_CONTEXT_COMPRESSED = "context.compressed"
EVENT_SESSION_META_CHANGED = "session.meta_changed"
EVENT_SESSION_FORKED = "session.forked"  # D3 预留：本期登记不触发行为
EVENT_REQUEST_META = "request.meta"  # HARNESS-02(2026-08-14): 每轮请求快照（模型/思考/工具目录/预算）
EVENT_REQUEST_USAGE = "request.usage"  # DSH 借鉴(2026-08-17): 每轮响应 usage 明细（命中/miss token 精确落盘）

# ── CodeArts 子 Agent 调度集成事件类型（design.md §1.1.2，凭证明文绝不入 payload）──
EVENT_CODEARTS_DISPATCHED = "codearts.dispatched"
EVENT_CODEARTS_STATUS_SYNCED = "codearts.status_synced"
EVENT_CODEARTS_STATUS_UNKNOWN = "codearts.status_unknown"
EVENT_CODEARTS_COLLECTED = "codearts.collected"
EVENT_CODEARTS_CANCELLED = "codearts.cancelled"
EVENT_CODEARTS_RECOVERED = "codearts.recovered"


@dataclass(frozen=True)
class EventTypeSpec:
    """事件类型登记项（类型名/版本/字段语义）.

    fields: {字段名: 语义描述}；字段缺失由事件承载方如实置空（不伪造）。
    """

    name: str
    version: int
    fields: dict[str, str]


@dataclass(frozen=True)
class Event:
    """事件对象（spec §6.1 逐字段对齐）."""

    event_id: str  # 全局唯一（uuid4 hex）
    session_id: str  # 关联会话标识（修复割裂点 A：必填落盘）
    seq: int  # 会话内单调递增、不重号
    type: str  # 事件类型（登记表中可见）
    ts: str  # ISO 时间戳（UTC）
    payload: dict  # 事件承载字段（缺失如实置空，不伪造）


def _event_to_dict(event: Event) -> dict:
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "seq": event.seq,
        "type": event.type,
        "ts": event.ts,
        "payload": event.payload,
    }


def serialize_event(event: Event) -> str:
    """事件 → 单行 JSON（ensure_ascii=False，无内嵌换行，保证 JSONL 行语义）."""
    return json.dumps(_event_to_dict(event), ensure_ascii=False)


def parse_event_line(line: str) -> Event | None:
    """单行 JSON → Event；损坏/结构非法 → None（调用方如实标注，fail-open）.

    不做类型登记校验（`validate_event_type` 单独负责），保证读路径对未登记
    旧类型只读兼容：解析成功即返回，是否合法由校验函数判定。
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    event_id = data.get("event_id")
    session_id = data.get("session_id")
    seq = data.get("seq")
    type_ = data.get("type")
    ts = data.get("ts")
    if not isinstance(event_id, str) or not event_id:
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    if not isinstance(seq, int) or seq < 1:
        return None
    if not isinstance(type_, str) or not type_:
        return None
    if not isinstance(ts, str):
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    return Event(
        event_id=event_id,
        session_id=session_id,
        seq=seq,
        type=type_,
        ts=ts,
        payload=payload,
    )


def validate_event_type(event: Event) -> list[str]:
    """类型登记校验：返回违规描述列表（空 = 合法）."""
    return REGISTRY.validate(event)


class EventTypeRegistry:
    """事件类型登记表（显式登记，旧类型只读兼容，spec §4.4）."""

    def __init__(self) -> None:
        self._types: dict[str, EventTypeSpec] = {}

    def register(self, spec: EventTypeSpec) -> None:
        self._types[spec.name] = spec

    def spec(self, type_name: str) -> EventTypeSpec | None:
        return self._types.get(type_name)

    def registered(self) -> list[str]:
        return list(self._types.keys())

    def validate(self, event: Event) -> list[str]:
        """校验事件类型是否登记；返回违规描述列表（空 = 合法）."""
        spec = self._types.get(event.type)
        if spec is None:
            return [f"未登记事件类型: {event.type}"]
        return []


# 模块级默认登记表（显式登记 5 类事件）
REGISTRY = EventTypeRegistry()
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SESSION_CREATED,
        version=1,
        fields={
            "version": "派生视图格式版本",
            "title": "会话标题",
            "created_at": "创建时间 ISO",
            "updated_at": "更新时间 ISO",
            "status": "active/archived",
            "parent_id": "父会话 id（根会话 None）",
            "branch_id": "分支标识",
            "branch_summary": "分支摘要",
            "model_override": "会话级模型覆盖（None=用装配默认）",
            "pinned": "置顶",
            "channel": "来源通道",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_MESSAGE_APPENDED,
        version=1,
        fields={
            "index": "消息在会话中的序号",
            "role": "user/assistant/tool/system",
            "content": "消息内容",
            "source": "消息来源标识",
            "tool_call_id": "tool 消息绑定 id",
            "status": "tool 执行状态",
            "tool_name": "来源工具名",
            "error_detail": "完整错误描述",
            "tool_calls": "assistant 工具声明",
            "reasoning_content": "assistant 思考链",
            "metadata": "截断/降级标注等",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CONTEXT_COMPRESSED,
        version=1,
        fields={
            "archive_ref": "压缩档案引用（archive id 或 tool_call_id）",
            "tool_call_id": "原消息定位（tool 消息绑定 id）",
            "msg_seq": "原消息在会话中的序号",
            "chars": "原文长度",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SESSION_META_CHANGED,
        version=1,
        fields={
            "field": "变更字段名",
            "changes": "变更明细（字段: 旧值→新值）",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SESSION_FORKED,
        version=1,
        fields={
            "parent_id": "父会话 id",
            "branch_id": "分支标识",
            "fork_point": "分叉点消息索引",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_REQUEST_META,
        version=1,
        fields={
            "round": "循环轮次",
            "model": "本轮实际使用的模型标签（routing/fallback 后最终值）",
            "thinking": "思考模式是否开启",
            "reasoning_effort": "推理强度",
            "tools_count": "本轮注入的工具 schema 数量",
            "history_chars": "提交历史字符数",
            "budget": "本轮历史预算",
        },
    )
)
# DSH 借鉴(2026-08-17): 每轮响应 usage 明细——对齐 DSH 事件流 usage 事件，
# 命中/miss token 逐轮落盘，命中率实时可算（不再依赖 CSV 账单/流式 M58 盲区）。
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_REQUEST_USAGE,
        version=1,
        fields={
            "round": "循环轮次",
            "model": "本轮实际使用的模型标签",
            "tokens_in": "本轮输入 token（provider 未返回 usage 时为 0，如实不伪造）",
            "tokens_out": "本轮输出 token",
            "cache_hit": "前缀缓存命中 token（provider 未返回为 0）",
            "cache_miss": "缓存未命中 token（=tokens_in−cache_hit，负值截 0；provider 无 usage 时不可据此判命中率）",
            "usage_available": "provider 是否返回 usage（false 时 tokens_in/cache_hit=0 不可当全 miss）",
        },
    )
)
# ── CodeArts 委派事件类型登记（payload 不含凭证明文，spec §6.1/§6.2/§6.3）──
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CODEARTS_DISPATCHED,
        version=1,
        fields={
            "handle_id": "执行句柄标识",
            "session_id": "关联会话标识",
            "trace_id": "链路追踪标识",
            "created_at": "句柄创建时间 ISO",
            "task_description": "委派任务描述摘要（已脱敏）",
            "priority": "优先级",
            "risk_level": "风险等级",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CODEARTS_STATUS_SYNCED,
        version=1,
        fields={
            "handle_id": "执行句柄标识",
            "session_id": "关联会话标识",
            "trace_id": "链路追踪标识",
            "status": "本地状态",
            "remote_status": "远端状态",
            "synced_at": "同步时间 ISO",
            "drift": "是否状态漂移",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CODEARTS_STATUS_UNKNOWN,
        version=1,
        fields={
            "handle_id": "执行句柄标识",
            "session_id": "关联会话标识",
            "trace_id": "链路追踪标识",
            "reason": "状态查询持续失败原因",
            "failed_attempts": "连续失败次数",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CODEARTS_COLLECTED,
        version=1,
        fields={
            "handle_id": "执行句柄标识",
            "session_id": "关联会话标识",
            "trace_id": "链路追踪标识",
            "status": "结果状态",
            "final_answer_chars": "最终回答字符数（可能已截断）",
            "truncated": "是否截断",
            "original_bytes": "原始体积（截断时标注）",
            "retained_bytes": "保留体积（截断时标注）",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CODEARTS_CANCELLED,
        version=1,
        fields={
            "handle_id": "执行句柄标识",
            "session_id": "关联会话标识",
            "trace_id": "链路追踪标识",
            "cancelled_at": "取消时间 ISO",
            "remote_cancelled": "远端是否确认取消",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_CODEARTS_RECOVERED,
        version=1,
        fields={
            "handle_id": "执行句柄标识",
            "session_id": "关联会话标识",
            "trace_id": "链路追踪标识",
            "recovered_at": "接管时间 ISO",
        },
    )
)


def build_message_payload(
    *,
    index: int,
    role: str,
    content: str,
    source: str,
    tool_call_id: Any = None,
    status: Any = None,
    tool_name: Any = None,
    error_detail: Any = None,
    tool_calls: Any = None,
    reasoning_content: Any = None,
    metadata: dict | None = None,
) -> dict:
    """构造 message.appended 事件 payload（与 Session.to_dict() 消息字段逐一对齐）."""
    return {
        "index": index,
        "role": role,
        "content": content,
        "source": source,
        "tool_call_id": tool_call_id,
        "status": status,
        "tool_name": tool_name,
        "error_detail": error_detail,
        "tool_calls": tool_calls,
        "reasoning_content": reasoning_content,
        "metadata": metadata or {},
    }
