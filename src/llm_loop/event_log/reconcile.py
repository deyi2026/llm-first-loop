"""D1 一致性校验 reconcile（design.md §2.2.2-D / spec §5.6）.

`reconcile` 为无状态纯函数：重放视图（derived）vs 源 session JSON（source）
逐字段比对（顶层字段 + messages 全量字段），输出结构化差异明细。
纯只读比对：不修改任何数据（spec §5.6.1-4）。

- 顶层字段差异: {字段/期望/实际}
- 消息差异: {index/字段/期望/实际}（压缩标注消息比对标注语义）
- passed = 无顶层差异 且 无消息差异 且 无事件缺口 且 无未知类型
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_loop.event_log.replay import _TOP_LEVEL_DEFAULTS

# 比对时排除的派生视图附加标注字段（非会话顶层字段）
_DERIVED_ONLY_KEYS = {"event_log_gaps", "unknown_event_types", "compressed_refs"}

# 消息逐字段比对全集（与 Session.to_dict() 消息字段对齐）
_MESSAGE_FIELDS = [
    "role",
    "content",
    "source",
    "tool_call_id",
    "status",
    "tool_name",
    "error_detail",
    "tool_calls",
    "reasoning_content",
    "metadata",
]


@dataclass
class ReconcileReport:
    """一致性校验报告（结构化差异明细）."""

    session_id: str
    passed: bool
    top_level_diffs: list[dict] = field(default_factory=list)
    message_diffs: list[dict] = field(default_factory=list)
    unknown_events: int = 0
    gap_count: int = 0
    replay_ms: float = 0.0


def reconcile(derived: dict, source: dict, *, replay_ms: float = 0.0) -> ReconcileReport:
    """重放视图 vs 源 session JSON 逐字段比对（顶层 + messages 全量字段）.

    Args:
        derived: replay_session 重建的派生视图.
        source: Session.load().to_dict() 或直接 json.loads 的源 dict.
        replay_ms: 重放耗时（调用方测得，默认 0）.

    Returns:
        结构化报告；比对异常 → passed=False + 差异/异常标注（不伪造通过）。
    """
    session_id = source.get("session_id") or derived.get("session_id") or ""
    top_diffs: list[dict] = []
    msg_diffs: list[dict] = []
    gap_count = 0

    for gap in derived.get("event_log_gaps", []) or []:
        gap_count += gap.get("missing", 0)

    # ── 顶层字段比对（含 version 与全部会话顶层字段）──
    for key in list(_TOP_LEVEL_DEFAULTS) + ["session_id"]:
        if key in _DERIVED_ONLY_KEYS:
            continue
        expected = source.get(key, _TOP_LEVEL_DEFAULTS.get(key))
        actual = derived.get(key, _TOP_LEVEL_DEFAULTS.get(key))
        if not _same_value(expected, actual):
            top_diffs.append({"字段": key, "期望": expected, "实际": actual})

    # 源含但视图未建模的顶层键（如实标注，不静默放行）
    for key in source:
        if key == "messages" or key in _TOP_LEVEL_DEFAULTS or key == "session_id":
            continue
        if key not in derived or derived.get(key) != source.get(key):
            top_diffs.append({"字段": key, "期望": source.get(key), "实际": derived.get(key)})

    # ── 消息逐字段比对（按 index）──
    src_messages = source.get("messages") or []
    der_messages = derived.get("messages") or []
    for i in range(max(len(src_messages), len(der_messages))):
        if i >= len(src_messages):
            msg_diffs.append(
                {"index": i, "字段": "(消息不存在)", "期望": None, "实际": der_messages[i]}
            )
            continue
        if i >= len(der_messages):
            msg_diffs.append(
                {"index": i, "字段": "(消息不存在)", "期望": src_messages[i], "实际": None}
            )
            continue
        sm = src_messages[i]
        dm = der_messages[i]
        if not isinstance(sm, dict) or not isinstance(dm, dict):
            msg_diffs.append({"index": i, "字段": "(结构异常)", "期望": sm, "实际": dm})
            continue
        for f in _MESSAGE_FIELDS:
            expected = sm.get(f, _default_msg_value(f))
            actual = dm.get(f, _default_msg_value(f))
            if not _same_value(expected, actual):
                msg_diffs.append({"index": i, "字段": f, "期望": expected, "实际": actual})

    unknown_events = len(derived.get("unknown_event_types", []) or [])
    passed = not top_diffs and not msg_diffs and gap_count == 0 and unknown_events == 0

    return ReconcileReport(
        session_id=session_id,
        passed=passed,
        top_level_diffs=top_diffs,
        message_diffs=msg_diffs,
        unknown_events=unknown_events,
        gap_count=gap_count,
        replay_ms=replay_ms,
    )


def _default_msg_value(field_name: str):
    """消息字段缺失时的语义默认值（与 Session.to_dict()/_build_message 对齐）."""
    if field_name == "content":
        return ""
    if field_name == "metadata":
        return {}
    return None


def _same_value(a, b) -> bool:
    """值比对（bool/int 同值视为一致：JSON false/0 语义等价）. """
    return a == b
