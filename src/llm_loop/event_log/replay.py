"""D1 事件回放与派生视图重建（design.md §2.2.2-C / spec §5.3）.

`replay_session` 为无状态纯函数：按 seq 递增重放事件 → 重建派生视图 dict
（对齐 `Session.to_dict()` 语义）。确定性：仅依赖事件日志内容（seq 顺序），
不依赖时间戳/外部状态——同一批事件重放两次结果逐字节一致。

- session.created 初始化顶层字段 → message.appended 按 index 组装消息 →
  session.meta_changed 增量更新顶层 → context.compressed 记录压缩引用 →
  session.forked 预留不触发 → 未知类型如实跳过计数。
- seq 缺口 → 视图携带 `event_log_gaps`；未知类型 → `unknown_event_types` 计数。
- 空事件列表 → 返回 {"exists": False}（不伪造空会话，由调用方如实标注"不存在"）。
- 只读派生：不修改事件日志。
"""

from __future__ import annotations

from llm_loop.event_log.model import REGISTRY, Event

# 对齐 Session.to_dict() 的顶层字段默认值（session.created 缺失字段如实置空）
_TOP_LEVEL_DEFAULTS: dict = {
    "version": None,
    "session_id": "",
    "created_at": "",
    "title": "",
    "updated_at": "",
    "status": "active",
    "parent_id": None,
    "branch_id": "",
    "branch_summary": "",
    "model_override": None,
    "pinned": False,
    "channel": "web",
}


def replay_session(events: list[Event]) -> dict:
    """按 seq 递增重放事件，重建派生视图 dict（对齐 Session.to_dict() 语义）.

    Returns:
        派生视图（含 version + 全部顶层字段 + messages + 标注）；空事件 → {"exists": False}。
    """
    if not events:
        return {"exists": False}

    ordered = sorted(events, key=lambda e: e.seq)
    view: dict = dict(_TOP_LEVEL_DEFAULTS)
    # session_id 是事件必填落盘字段（修复割裂点 A）：从事件本身取，不依赖 payload
    view["session_id"] = ordered[0].session_id
    messages_by_index: dict[int, dict] = {}
    compressed_refs: list[dict] = []
    gaps: list[dict] = []
    unknown_types: list[str] = []
    expected_seq = 1

    for event in ordered:
        if event.seq != expected_seq:
            gaps.append(
                {"gap_at": expected_seq, "missing": event.seq - expected_seq}
            )
        expected_seq = event.seq + 1

        if event.type == "session.created":
            for key in _TOP_LEVEL_DEFAULTS:
                if key in event.payload:
                    view[key] = event.payload[key]
        elif event.type == "message.appended":
            msg = _build_message(event.payload)
            idx = _as_int(event.payload.get("index"))
            if idx is None:
                idx = len(messages_by_index)
            messages_by_index[idx] = msg
        elif event.type == "session.meta_changed":
            _apply_meta_change(view, event.payload)
        elif event.type == "context.compressed":
            compressed_refs.append(
                {
                    "archive_ref": event.payload.get("archive_ref"),
                    "tool_call_id": event.payload.get("tool_call_id"),
                    "msg_seq": event.payload.get("msg_seq"),
                    "chars": event.payload.get("chars"),
                }
            )
        elif event.type == "session.forked":
            # D3: 提取 fork 元信息写入视图标注字段（不改变既有顶层字段重建语义）
            view.setdefault(
                "fork_meta",
                {
                    "source_session_id": event.payload.get("source_session_id"),
                    "fork_point": event.payload.get("fork_point"),
                    "inherited_event_count": event.payload.get("inherited_event_count"),
                    "new_session_id": event.payload.get("new_session_id"),
                    "fork_ts": event.payload.get("fork_ts"),
                },
            )
        elif REGISTRY.spec(event.type) is None and event.type not in unknown_types:
            unknown_types.append(event.type)
        # 已登记但未分派的类型：静默跳过（如实不伪造）

    view["messages"] = [messages_by_index[i] for i in sorted(messages_by_index)]
    if gaps:
        view["event_log_gaps"] = gaps
    if unknown_types:
        view["unknown_event_types"] = unknown_types
    if compressed_refs:
        view["compressed_refs"] = compressed_refs
    return view


def _build_message(payload: dict) -> dict:
    """按 Session.to_dict() 消息字段语义重建消息 dict（缺失字段如实置空）."""
    return {
        "role": payload.get("role"),
        "content": payload.get("content", ""),
        "source": payload.get("source"),
        "tool_call_id": payload.get("tool_call_id"),
        "status": payload.get("status"),
        "tool_name": payload.get("tool_name"),
        "error_detail": payload.get("error_detail"),
        "tool_calls": payload.get("tool_calls"),
        "reasoning_content": payload.get("reasoning_content"),
        "metadata": payload.get("metadata") or {},
    }


def _apply_meta_change(view: dict, payload: dict) -> None:
    """session.meta_changed 增量更新顶层字段.

    changes 结构: {field: {"from": 旧值, "to": 新值}}；单 field 也支持 payload["field"]。
    缺失/非法变更如实跳过（不伪造）。
    """
    changes = payload.get("changes")
    if isinstance(changes, dict):
        for field, change in changes.items():
            if field in view and isinstance(change, dict) and "to" in change:
                view[field] = change["to"]
        return
    field = payload.get("field")
    if isinstance(field, str) and field in view and field not in ("messages", "version"):
        # 无 changes 明细时仅携带字段名：无法确定新值，如实跳过（不伪造）
        return


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
