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
EVENT_MESSAGE_CACHE_COMPACTED = "message.cache_compacted"
EVENT_HISTORY_COMPACTION = "history.compaction"
EVENT_HISTORY_COMPACTION_STATE_RESET = "history.compaction_state_reset"
EVENT_SESSION_META_CHANGED = "session.meta_changed"
EVENT_SESSION_FORKED = "session.forked"  # D3 预留：本期登记不触发行为
EVENT_REQUEST_META = (
    "request.meta"  # HARNESS-02(2026-08-14): 每轮请求快照（模型/思考/工具目录/预算）
)
EVENT_REQUEST_ATTEMPT = "request.attempt"  # exceptional provider attempts (fallback/retry)
EVENT_REQUEST_USAGE = (
    "request.usage"  # DSH 借鉴(2026-08-17): 每轮响应 usage 明细（命中/miss token 精确落盘）
)
EVENT_INTEROP_SPLICED = (
    "interop.spliced"  # DSH 借鉴(2026-08-17): 协调通道 inbox 注入事件（对齐 agent/inbox/spliced）
)
EVENT_RUN_END = (
    "run.end"  # DSH 借鉴(2026-08-17): run 生命周期结束事件（对齐 turn/end，结束原因可审计）
)
EVENT_LLM_INTERRUPTED = (
    "llm.interrupted"  # 未完成 provider 输出的终止事实（storage/audit，不等于完成 assistant）
)
EVENT_LLM_PARTIAL_CHECKPOINT = (
    "llm.partial_checkpoint"  # 流式 in-flight model state；重启续思数据源，不进对话
)
EVENT_TOOL_EXECUTION_DECLARED = "tool.execution.declared"
EVENT_TOOL_EXECUTION_STARTED = "tool.execution.started"
EVENT_TOOL_EXECUTION_EFFECT_PREPARED = "tool.execution.effect_prepared"
EVENT_TOOL_EXECUTION_EFFECT_OBSERVED = "tool.execution.effect_observed"
EVENT_TOOL_EXECUTION_FINISHED = "tool.execution.finished"
EVENT_TOOL_EXECUTION_RECEIPT_COMMITTED = "tool.execution.receipt_committed"
EVENT_HUMAN_FILE_EDIT_PREPARED = "human.file_edit.prepared"
EVENT_HUMAN_FILE_EDIT_OBSERVED = "human.file_edit.observed"
EVENT_HUMAN_FILE_EDIT_REJECTED = "human.file_edit.rejected"
EVENT_EXTERNAL_EXECUTION_LAUNCHED = "external.execution.launched"
EVENT_EXTERNAL_EXECUTION_TERMINAL = "external.execution.terminal"
EVENT_EXTERNAL_EXECUTION_CANCEL_REQUESTED = "external.execution.cancel_requested"
EVENT_SUBAGENT_LINKED = "subagent.linked"
EVENT_SUBAGENT_GENERATION_STARTED = "subagent.generation.started"
EVENT_SUBAGENT_GENERATION_RELEASED = "subagent.generation.released"
EVENT_SUBAGENT_TERMINAL = "subagent.terminal"
EVENT_SUBAGENT_MAILBOX_QUEUED = "subagent.mailbox.queued"
EVENT_SUBAGENT_REPORT_QUEUED = "subagent.report.queued"
EVENT_SUBAGENT_RESULT_AVAILABLE = "subagent.result.available"
EVENT_SUBAGENT_CANCEL_REQUESTED = "subagent.cancel_requested"
EVENT_PROGRAM_RECOVERY = "program.recovery"  # R4: 一次性程序恢复动作审计（不作为 durable 对话消息）
EVENT_INJECTION_PROFILE_SHADOW = "injection.profile.shadow"  # Historical R8 schema; P1-C keeps read compatibility only, no new emitter

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


# 模块级默认登记表（所有可写事件类型必须显式登记）
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
            "fixed_summary": "version 5 固定摘要（生成后不可变）",
            "summary_chain": "version 5 增量摘要链（尾部追加）",
            "working_state_checkpoint": "S1 内部 working-state checkpoint（缺省 None）",
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
        name=EVENT_MESSAGE_CACHE_COMPACTED,
        version=1,
        fields={
            "msg_seq": "原消息在会话中的序号",
            "provider_id": "该折叠状态所属 provider",
            "marker_version": "provider-view compaction marker contract version；legacy 事件缺失",
            "model": "生成该 marker 的完整 provider/model 标签；模型变化时旧 marker 可重算",
            "effective_budget": "生成该 marker 时的有效历史字符预算；预算扩容时旧 marker 可重算",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_HISTORY_COMPACTION,
        version=1,
        fields={
            "model": "本次实际路由模型标签",
            "provider_id": "本次 provider",
            "compaction_epoch": "session 级历史压缩事件序号",
            "trigger": "压缩触发原因码",
            "pre_history_chars": "触发判断时 provider-visible 历史字符数",
            "pre_chars": "压缩前视图字符数（含 system）",
            "post_chars": "压缩后实际提交视图字符数",
            "effective_budget_chars": "本次实际历史预算",
            "compact_ratio": "触发阈值比例",
            "trigger_limit_chars": "本次触发阈值字符数",
            "trigger_excess_chars": "超出触发阈值的字符数",
            "archive_target_ratio": "归档目标比例",
            "archive_target_chars": "归档目标字符数",
            "archived_count": "本次归档消息数",
            "archived_group_count": "本次归档原子消息组数",
            "atomic_group_count": "压缩前原子消息组总数",
            "compaction_mode": "本次机械 compaction 投影模式",
            "head_keep_chars": "本次 fixed-head 配置字符预算",
            "head_keep_target_ratio": "fixed-head 占归档目标上限比例",
            "cache_boundary_mode": "inactive/protected/epoch_reset",
            "cache_protected_messages": "实际原子组取整后保护消息数",
            "cache_protected_chars": "实际原子组取整后保护字符数",
            "cache_epoch_reset": "本次是否显式重建 cache prefix epoch",
            "anchor_before": "压缩前 provider history anchor",
            "anchor_after": "压缩后 provider history anchor",
            "anchor_moved": "history anchor 是否移动",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_HISTORY_COMPACTION_STATE_RESET,
        version=1,
        fields={
            "model": "当前完整 provider/model 标签",
            "provider_id": "当前 provider",
            "effective_budget": "当前有效历史字符预算",
            "legacy_anchor_reset": "旧/失配 history anchor 是否被清零重算",
            "anchor_before": "重算前 provider history anchor",
            "reopened_marker_count": "因旧/失配 contract 重新进入当前 provider view 的消息数",
            "reason": "稳定原因码；当前为 compaction_contract_changed",
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
        name=EVENT_LLM_PARTIAL_CHECKPOINT,
        version=1,
        fields={
            "round": "生成该 checkpoint 的模型轮次",
            "provider": "生成中断状态的 provider",
            "model": "生成中断状态的模型标签",
            "text_tail": "最近已收到的模型正文尾段；非完成答案",
            "reasoning_tail": "最近已收到的 reasoning 尾段；仅用于同一未完成交互续接",
            "text_chars": "截至 checkpoint 已收到的正文总字符数",
            "reasoning_chars": "截至 checkpoint 已收到的 reasoning 总字符数",
            "partial_sha256": "截至 checkpoint 模型输出的内容指纹",
            "native_state_sha256": "原子 in-flight provider-native sidecar 内容指纹；空表示本轮尚无 opaque/tool draft 状态",
            "native_state_chars": "provider-native sidecar JSON 字符数",
            "tool_call_draft_count": "尚未到 provider 完成边界的 tool-call draft 数；仅恢复诊断，绝不可直接执行",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_LLM_INTERRUPTED,
        version=1,
        fields={
            "round": "中断发生的模型轮次",
            "reason": "client_disconnect/cancelled/llm_error 等终止原因",
            "error_digest": "可选错误摘要",
            "text_tail": "保存的模型正文尾段",
            "reasoning_tail": "保存的模型 reasoning 尾段",
            "text_tail_chars": "保存的模型正文尾段字符数",
            "reasoning_tail_chars": "保存的模型 reasoning 尾段字符数",
            "partial_chars": "中断时正文+reasoning 总字符数",
            "partial_sha256": "中断模型输出的内容指纹",
            "native_state_sha256": "中断时 provider-native sidecar 内容指纹",
            "native_state_chars": "中断时 provider-native sidecar JSON 字符数",
            "tool_call_draft_count": "中断时未完成 tool-call draft 数；非可执行工具调用",
            "finish_reason": "provider terminal finish reason；未知为空",
            "completion_tokens": "provider terminal completion token 事实；未知为 null/0",
            "reasoning_tokens": "provider terminal reasoning token 事实；未知为 null",
            "provider_truncated": "provider 是否显式报告 truncation；未知为 null",
            "timing": "primary attempt 机械阶段耗时；prefill 不可观测时为 null",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_TOOL_EXECUTION_DECLARED,
        version=1,
        fields={
            "execution_id": "session+round+tool_call+arguments 的稳定执行尝试 id",
            "round": "模型工具轮次",
            "tool_call_id": "provider tool call id",
            "tool_name": "工具名",
            "args_sha256": "规范化 arguments 的 SHA256；不存原参数副本",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_TOOL_EXECUTION_STARTED,
        version=1,
        fields={
            "execution_id": "对应 declared 执行尝试 id",
            "round": "模型工具轮次",
            "tool_call_id": "provider tool call id",
            "tool_name": "工具名",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
        version=1,
        fields={
            "execution_id": "对应 started 执行尝试 id",
            "round": "模型工具轮次",
            "tool_call_id": "provider tool call id",
            "tool_name": "工具名",
            "effect_kind": "机械副作用类型；EW2-B 首期为 file_replace",
            "workspace_root": "执行时规范化工作区根",
            "canonical_path": "工作区内规范化目标路径",
            "before_sha256": "mutation 前精确文件字节 SHA256",
            "before_size": "mutation 前精确文件字节数",
            "expected_after_sha256": "预期写入精确字节 SHA256",
            "expected_after_size": "预期写入精确字节数",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
        version=1,
        fields={
            "execution_id": "对应 effect_prepared 执行尝试 id",
            "round": "模型工具轮次",
            "tool_call_id": "provider tool call id",
            "tool_name": "工具名",
            "effect_kind": "机械副作用类型",
            "workspace_root": "执行时规范化工作区根",
            "canonical_path": "工作区内规范化目标路径",
            "actual_after_sha256": "写后复读精确文件字节 SHA256",
            "actual_size": "写后复读精确文件字节数",
            "actual_mtime_ns": "写后 stat mtime_ns；不可用可为空",
            "matches_expected": "actual_after_sha256 是否等于 prepared 的预期字节",
            "artifact_ref": "可选：该精确写后版本对应的 workspace-scoped immutable artifact ref",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_HUMAN_FILE_EDIT_PREPARED,
        version=1,
        fields={
            "operation_id": "真实人工文件操作 id",
            "request_id": "客户端幂等请求 id",
            "request_sha256": "绑定 session/workspace/path/版本/内容的规范化请求摘要",
            "origin": "authenticated_user；仅表示已认证 Web/CLI 操作者",
            "workspace_root": "操作时机械绑定的规范化工作区根",
            "relative_path": "工作区内相对路径",
            "before_sha256": "mutation 前完整字节 SHA256",
            "before_size": "mutation 前完整字节数",
            "expected_after_sha256": "准备写入完整字节 SHA256",
            "expected_after_size": "准备写入完整字节数",
            "expected_snapshot_ref": "调用方提交的版本前置 artifact ref",
            "precondition_checked": "是否已执行精确版本前置核对",
            "file_contract_version": "文件协作契约版本",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_HUMAN_FILE_EDIT_OBSERVED,
        version=1,
        fields={
            "operation_id": "对应 prepared 的人工文件操作 id",
            "request_id": "客户端幂等请求 id",
            "origin": "authenticated_user",
            "workspace_root": "操作时机械绑定的规范化工作区根",
            "relative_path": "工作区内相对路径",
            "actual_after_sha256": "写后复读完整字节 SHA256",
            "actual_size": "写后复读完整字节数",
            "actual_mtime_ns": "写后 mtime_ns；不可得时为空",
            "matches_expected": "实际写后字节是否等于 prepared 预期",
            "artifact_ref": "写后 immutable artifact ref；失败可为空",
            "receipt_state": "recorded/recording_failed",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_HUMAN_FILE_EDIT_REJECTED,
        version=1,
        fields={
            "operation_id": "被拒绝请求的操作 id",
            "request_id": "客户端幂等请求 id",
            "request_sha256": "规范化请求摘要",
            "origin": "authenticated_user",
            "workspace_root": "拒绝时绑定的规范化工作区根",
            "relative_path": "经安全解析后的工作区相对路径；不可解析时可为空",
            "reason": "稳定机械拒绝原因",
            "precondition_checked": "拒绝前是否已执行版本前置核对",
            "file_contract_version": "文件协作契约版本",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_TOOL_EXECUTION_FINISHED,
        version=1,
        fields={
            "execution_id": "对应 declared 执行尝试 id",
            "round": "模型工具轮次",
            "tool_call_id": "provider tool call id",
            "tool_name": "工具名",
            "result_state_sha256": "原子 result sidecar 内容 SHA256",
            "result_state_chars": "result sidecar JSON 字符数",
            "status": "已返回 ToolResult 的状态",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_TOOL_EXECUTION_RECEIPT_COMMITTED,
        version=1,
        fields={
            "execution_id": "对应 declared 执行尝试 id",
            "round": "模型工具轮次",
            "tool_call_id": "provider tool call id",
            "tool_name": "工具名",
            "result_state_sha256": "已提交 receipt 对应 result sidecar 指纹；可为空",
            "recovered": "是否由重启恢复路径完成 commit",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_EXTERNAL_EXECUTION_LAUNCHED,
        version=1,
        fields={
            "job_id": "稳定后台执行 id",
            "workspace_root": "启动时规范化工作区根；机械归属事实",
            "executor": "启动该外部执行的工具/执行器",
            "command_sha256": "命令/任务文本 SHA256；不持久化原始命令",
            "pid": "启动进程观察到的 PID；不单独授权重连/终止",
            "pgid": "启动进程观察到的进程组 ID；不单独授权重连/终止",
            "auto_reclaim": "恒 false；本阶段不自动重连/重启",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_EXTERNAL_EXECUTION_TERMINAL,
        version=1,
        fields={
            "job_id": "对应后台执行 id",
            "state": "completed/failed/killed 机械终态",
            "exit_code": "进程退出码；不可得时 None",
            "killed": "是否由本进程机械终止路径标记",
            "auto_reclaim": "恒 false",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_EXTERNAL_EXECUTION_CANCEL_REQUESTED,
        version=1,
        fields={
            "job_id": "对应后台执行 id",
            "reason": "机械取消来源，例如 session_cancel/user_job_kill",
            "auto_reclaim": "恒 false",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_LINKED,
        version=1,
        fields={
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "depth": "mechanical recursion depth",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_GENERATION_STARTED,
        version=1,
        fields={
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "owner_id": "runner instance owner id; diagnostic/fencing fact, not PID authority",
            "depth": "mechanical recursion depth",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_GENERATION_RELEASED,
        version=1,
        fields={
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "owner_id": "runner instance owner id",
            "depth": "mechanical recursion depth",
            "reason": "mechanical release reason",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_TERMINAL,
        version=1,
        fields={
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "depth": "mechanical recursion depth",
            "outcome": "terminal child outcome fact",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_MAILBOX_QUEUED,
        version=1,
        fields={
            "message_id": "stable mailbox message id",
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "sender_id": "direct parent sender session id",
            "content": "exact delegated message content",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_REPORT_QUEUED,
        version=1,
        fields={
            "report_id": "stable child report id",
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "content": "exact child report content",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_RESULT_AVAILABLE,
        version=1,
        fields={
            "result_id": "stable terminal result id for this generation",
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "result": "exact structured SubAgentResult facts",
            "report_ids": "durable report ids included by this terminal result",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_SUBAGENT_CANCEL_REQUESTED,
        version=1,
        fields={
            "cancel_id": "stable cancellation fact id",
            "child_id": "child session id",
            "parent_id": "direct parent session id",
            "generation": "execution-generation fencing id",
            "reason": "mechanical lifecycle cancel reason",
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
            "thinking": "legacy：本请求是否显式请求 reasoning；auto+本地默认未知时可为 null",
            "reasoning_mode": "配置模式 auto/off/on",
            "reasoning_capable": "是否有模型/provider/实测事实支持该模型可产生 reasoning；与可否显式控制分离",
            "reasoning_control": "显式控制协议：thinking_type/chat_template/unknown/none/legacy",
            "reasoning_supported": "兼容字段：该模型/provider 是否支持 LFL 当前已知的显式 reasoning 控制",
            "reasoning_requested": "发送前可确定的请求状态；auto+provider 默认未知时为 null",
            "reasoning_effort": "推理强度",
            "tools_count": "本轮注入的工具 schema 数量",
            "messages_count": "提交 provider 的 message 条数；机械结构事实",
            "tail_user_run": "提交 provider 的尾部连续 user frame 条数；1210/协议诊断事实",
            "history_chars": "提交 message content 字符数（不含 reasoning_content）",
            "reasoning_chars": "提交 messages 中 reasoning_content 字符数",
            "provider_visible_chars": "主要 provider-visible 结构字符数（messages + tool schemas；不含传输头/凭据）",
            "budget": "本轮历史预算",
            "attempt_id": "provider attempt 机械身份；不参与 prompt/provider payload",
            "attempt_kind": "primary/fallback/err1210_retry 等机械 attempt 类型",
            "attempt_index": "同类 attempt 序号",
            "provider_structure_fp": "messages+tools 主要 provider-visible 结构的一次性 SHA256 短指纹",
            "runtime_snapshot": "启动时进程/source/config/tool surface 机械身份快照；不进入 prompt",
            "generation_contract": "该 attempt 的有效 generation/wire 客户端事实",
            "influence": "请求构建阶段机械 effect 摘要；不含完整 prompt/语义根因判断",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_REQUEST_ATTEMPT,
        version=1,
        fields={
            "round": "循环轮次",
            "attempt_id": "provider attempt 机械身份",
            "attempt_kind": "fallback/err1210_retry 等异常路径类型",
            "attempt_index": "同类 attempt 序号",
            "provider": "实际 provider",
            "model": "实际模型",
            "tools_count": "本 attempt tools 数量",
            "messages_count": "本 attempt provider message 条数",
            "tail_user_run": "本 attempt 尾部连续 user frame 条数",
            "history_chars": "本 attempt message content 字符数",
            "reasoning_chars": "本 attempt historical reasoning 字符数",
            "provider_visible_chars": "本 attempt messages+tools 主要结构字符数",
            "provider_structure_fp": "本 attempt 主要结构 SHA256 短指纹",
            "generation_contract": "实际 client generation/wire 机械事实",
            "transform": "若存在，记录 retry 前后结构机械变换；不判断语义",
        },
    )
)
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_INJECTION_PROFILE_SHADOW,
        version=1,
        fields={
            "round": "循环轮次",
            "attempt_kind": "provider attempt 类型（primary/fallback/err1210_retry）",
            "attempt_index": "同轮同类型 attempt 序号；primary=0，fallback/retry 从1开始",
            "model": "该次真实 provider attempt 的模型标签",
            "mode": "历史 R8 注入分档模式（P1-C 后仅旧日志读取兼容）",
            "recommended_injection_profile": "历史 R8 推荐 profile（minimal/standard/full）",
            "applied": "历史 R8 字段；旧事件固定 false，P1-C 后不再新写",
            "model_capability_tier": "推荐所依据的 ModelSpec capability_tier",
            "source": "能力归因来源（provider registry 或保守 fallback）",
            "reason": "稳定的推荐原因码",
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
            "cache_read_tokens": "缓存复用 token；统一别名，当前等于 cache_hit",
            "uncached_prompt_tokens": "真实未缓存输入 token；usage 不可用时为 null，不把未知伪装成 0",
            "cache_hit_rate": "cache_read_tokens/tokens_in；usage 不可用时为 null",
            "context_window": "本次实际路由模型注册的物理 context window；未知为 null",
            "output_reserve_tokens": "本次 client 实际配置/请求的 max output 预留，不等同模型理论最大输出",
            "context_headroom_tokens": "context_window−tokens_in−output_reserve；缓存命中 token 仍占窗口，不从容量中扣除",
            "context_used_ratio": "(tokens_in+output_reserve)/context_window；未知窗口/usage 时为 null",
            "stable_prefix_fp": "system/稳定 base + 实际投影 tools 的结构指纹；仅用于缓存漂移观测",
            "prefix_changed": "相对上一成功 provider 请求，模型或稳定结构指纹是否变化",
            "prefix_change_reason": "model_changed/stable_prefix_changed/空字符串",
            "cache_prefix_epoch": "session 级 provider-prefix 代数；结构替换或显式 cache epoch reset 时递增",
            "compaction_epoch": "历史压缩事件序号；与 cache_prefix_epoch 分离",
            "runtime_pid": "产生本次请求的 LFL 进程 PID；用于归因进程重启后的 cache/run-state 冷启动，不参与 prompt/路由",
            "usage_available": "provider 是否返回 usage（false 时 tokens_in/cache_hit=0 不可当全 miss）",
            "timing": "primary provider attempt 阶段耗时；异常/非 primary 不伪造",
        },
    )
)
# DSH 借鉴(2026-08-17): 协调通道 inbox 注入事件（对齐 DSH agent/inbox/spliced 血缘语义）——
# 每轮 run 构建消息时若有外部协调消息注入，记录来源/条数/位置，缓存审计可追溯
# "哪轮请求含外部注入"（注入改变请求内容→可解释该轮 miss 来源）。
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_INTEROP_SPLICED,
        version=1,
        fields={
            "session_id": "注入目标会话 ID",
            "round": "注入发生的循环轮次（0=构建期不可知时如实置 0）",
            "count": "注入消息条数",
            "start": "注入位置（base 列表索引，对齐 DSH start 语义）",
            "sources": "来源文件列表（data/interop/lfl_to_dsh/pending/*.json）",
            "content_preview": "首条消息内容前 200 字符（审计摘要，不全量落盘）",
        },
    )
)
# INJECTION-GOVERNANCE R4: executable recovery is runtime-only, so its durable
# audit truth is an event rather than a message.appended row.  `action` maps to the
# canonical template in core/program_recovery.py and is sufficient to reconstruct intent.
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_PROGRAM_RECOVERY,
        version=1,
        fields={
            "action": "closed ProgramRecoveryAction value",
            "trigger": "recovery trigger (currently provider_1210)",
            "turn_ref": "human turn reference this recovery is bounded to",
            "scope": "execution lifetime; currently next_build_only",
        },
    )
)
# DSH 借鉴(2026-08-17): run 生命周期结束事件（对齐 DSH turn/end reason 语义）——
# run 有 8+ 个结束出口（completed/llm_error/overflow/stagnation/max_iterations/routing_override
# /session_save_failed 等），结束原因散落各分支无统一审计；run.end 在统一出口
# LoopResult 前落盘，排障/轮次耗尽归因（RULE-AI-11）直接可查。
REGISTRY.register(
    EventTypeSpec(
        name=EVENT_RUN_END,
        version=1,
        fields={
            "session_id": "run 所属会话 ID",
            "reason": "结束原因（completed/llm_error/overflow/stagnation/max_iterations/routing_override/session_save_failed）",
            "rounds": "实际循环轮数",
            "tokens_in": "run 累计输入 token",
            "tokens_out": "run 累计输出 token",
            "cache_hit": "run 累计缓存命中 token",
            "duration_ms": "run 总耗时毫秒（run 开始到结束）",
            "model_used": "最终模型标签",
            "truncated": "最终回答是否被截断",
            "answer_preview": "最终回答前 200 字符（审计摘要）",
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
