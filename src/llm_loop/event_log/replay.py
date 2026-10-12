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

from llm_loop.event_log.model import (
    EVENT_HISTORY_COMPACTION_STATE_RESET,
    EVENT_MESSAGE_CACHE_COMPACTED,
    EVENT_MESSAGE_RETRACTED,
    REGISTRY,
    Event,
)

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
    # Session version 5: 追加式压缩摘要链。旧事件日志无字段时语义默认为空。
    "fixed_summary": "",
    "summary_chain": [],
    # S1 internal fold state; absent in legacy event logs.
    "working_state_checkpoint": None,
}


def _apply_cache_compacted(
    message: dict,
    provider_id: str,
    *,
    marker_version: int | None = None,
    model: str = "",
    effective_budget: int | None = None,
) -> None:
    """Replay provider-scoped prompt-view compaction into message metadata."""
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    raw = metadata.get("cache_compacted_for")
    if isinstance(raw, str):
        providers = [raw]
    elif isinstance(raw, (list, tuple, set)):
        providers = [str(item) for item in raw if item]
    else:
        providers = []
    if provider_id not in providers:
        providers.append(provider_id)
    metadata["cache_compacted_for"] = providers
    if marker_version and model and effective_budget:
        scopes_raw = metadata.get("cache_compaction_scope")
        scopes = dict(scopes_raw) if isinstance(scopes_raw, dict) else {}
        scopes[provider_id] = {
            "version": int(marker_version),
            "model": model,
            "effective_budget": int(effective_budget),
        }
        metadata["cache_compaction_scope"] = scopes
    message["metadata"] = metadata


def _clear_cache_compacted(message: dict, provider_id: str) -> None:
    """Replay a compaction-contract reset by removing this provider's old marker."""
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return
    raw = metadata.get("cache_compacted_for")
    if isinstance(raw, str):
        providers = [raw]
    elif isinstance(raw, (list, tuple, set)):
        providers = [str(item) for item in raw if item]
    else:
        providers = []
    providers = [item for item in providers if item != provider_id]
    if providers:
        metadata["cache_compacted_for"] = providers
    else:
        metadata.pop("cache_compacted_for", None)
    scopes_raw = metadata.get("cache_compaction_scope")
    if isinstance(scopes_raw, dict):
        scopes = dict(scopes_raw)
        scopes.pop(provider_id, None)
        if scopes:
            metadata["cache_compaction_scope"] = scopes
        else:
            metadata.pop("cache_compaction_scope", None)
    message["metadata"] = metadata


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
            # 2026-08-21 修复（中断索引错乱）: 事件按 seq 排序处理, 先到的是真实顺序。
            # 若 idx 已被占用（run 中断导致内存 len(sess.messages) 回滚 → 索引重复,
            # 实测 180c662a: idx=4 被"评估"和"继续"两条 user 消息占用, 后者覆盖前者
            # 丢任务）——不再覆盖, 用递增 idx 追加（全部消息保留, 顺序按 seq 保真）。
            while idx in messages_by_index:
                idx += 1
            messages_by_index[idx] = msg
        elif event.type == "session.meta_changed":
            _apply_meta_change(view, event.payload)
        elif event.type == EVENT_MESSAGE_RETRACTED:
            from llm_loop.core.message_retraction import (
                HUMAN_TURN_SOURCE_ID_KEY,
                RETRACTED_MARKER,
                project_retracted_metadata,
            )

            source_id = str(event.payload.get("source_id") or "")
            matches = [
                message
                for message in messages_by_index.values()
                if str((message.get("metadata") or {}).get(HUMAN_TURN_SOURCE_ID_KEY) or "")
                == source_id
                and str(message.get("role") or "") == "user"
            ]
            if source_id and matches:
                for target in matches:
                    target["content"] = RETRACTED_MARKER
                    target["metadata"] = project_retracted_metadata(
                        target.get("metadata"), event.payload, event_id=event.event_id
                    )
                # A model-authored working-state snapshot may carry facts from the withdrawn
                # turn.  It is exact-transcript state, so mechanically invalidate it.
                view["working_state_checkpoint"] = None
        elif event.type == "context.compressed":
            compressed_refs.append(
                {
                    "archive_ref": event.payload.get("archive_ref"),
                    "tool_call_id": event.payload.get("tool_call_id"),
                    "msg_seq": event.payload.get("msg_seq"),
                    "chars": event.payload.get("chars"),
                }
            )
        elif event.type == EVENT_HISTORY_COMPACTION_STATE_RESET:
            provider_id = str(event.payload.get("provider_id") or "")
            if provider_id:
                for message in messages_by_index.values():
                    _clear_cache_compacted(message, provider_id)
        elif event.type == EVENT_MESSAGE_CACHE_COMPACTED:
            idx = _as_int(event.payload.get("msg_seq"))
            provider_id = str(event.payload.get("provider_id") or "")
            if idx is not None and provider_id and idx in messages_by_index:
                _apply_cache_compacted(
                    messages_by_index[idx],
                    provider_id,
                    marker_version=_as_int(event.payload.get("marker_version")),
                    model=str(event.payload.get("model") or ""),
                    effective_budget=_as_int(event.payload.get("effective_budget")),
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

    view["messages"] = _ordered_messages(messages_by_index, ordered)
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


def _ordered_messages(messages_by_index: dict, ordered_events: list) -> list[dict]:
    """按事件 seq 顺序输出消息（2026-08-21 修复中断索引错乱）.

    原实现按 idx 排序——run 中断时内存 len(sess.messages) 回滚导致多条消息 idx 重复
    （实测 180c662a: "评估"和"继续"都 idx=4）, dict 后到覆盖先到 → 丢消息/顺序错乱。
    修复: 按 seq 遍历 message.appended 事件, 依出现顺序收集（idx 冲突时后到的追加
    到尾部, 不覆盖先到的）——全部消息保留且顺序按 seq 保真。
    """
    # messages_by_index 本身按 event seq 处理顺序插入；idx 冲突时上游会递增到空位，
    # 因此 dict insertion order 就是保真的消息顺序。必须返回这里的对象，而不能再次
    # 从 message.appended payload 重建，否则后续 message.cache_compacted 等增量事件
    # 对 metadata 的修改会被丢掉。
    return list(messages_by_index.values())
