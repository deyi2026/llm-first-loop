"""D3 会话 fork 事件编排（design.md §2.2.2-A / spec §5.1）.

`fork_session` 为编排纯函数：从源会话事件日志物理复制截至 fork 点的事件流到新会话，
追加 session.created + session.forked，同步生成 session JSON（双轨）。

- 源会话仅读不写（事件文件 mtime/哈希不变，spec §5.1.1-5）
- 新会话事件日志独立（物理复制，seq 从 1 递增，session_id/event_id 重分配，spec §5.1.1-7）
- fail-open：事件写入 IO 异常 → 已写入部分保留 + success=False + error 标注（spec §5.1.3-3）
- event_store 不可用（禁用/未注入）→ 仅生成 session JSON（零回归）
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ForkReport:
    """fork 操作报告（design.md §2.2.2-A）."""

    new_session_id: str
    source_session_id: str
    fork_point: int | None
    inherited_event_count: int
    elapsed_ms: float
    success: bool
    error: str = ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_event_store_available(store: Any) -> bool:
    return store is not None and getattr(store, "enabled", False) is not False


def fork_session(
    event_store: Any,
    session_store: Any,
    source_session_id: str,
    *,
    fork_point: int | None = None,
    branch_summary: str = "",
) -> ForkReport:
    """从源会话 fork 出新会话（物理复制事件流 + session.created + session.forked + session JSON 双轨）.

    Args:
        event_store: EventStore 实例（None/禁用 → 仅生成 session JSON 零回归）.
        session_store: SessionStore 实例（用于 session JSON 双轨生成）.
        source_session_id: 源会话 ID.
        fork_point: fork 点（保留前 N 条消息，即 messages[:N]；None=继承全部）.
        branch_summary: 分支摘要（空=自动提炼）.

    Returns:
        ForkReport（含新会话 ID / 继承事件数 / 成功状态 / 错误标注）.
    """
    start = time.monotonic()

    def _report(
        new_id: str = "",
        inherited: int = 0,
        success: bool = False,
        error: str = "",
    ) -> ForkReport:
        return ForkReport(
            new_session_id=new_id,
            source_session_id=source_session_id,
            fork_point=fork_point,
            inherited_event_count=inherited,
            elapsed_ms=round((time.monotonic() - start) * 1000, 2),
            success=success,
            error=error,
        )

    # 加载源会话（session JSON）——用于 session JSON 双轨生成 + 消息数计算
    source_session = session_store.load(source_session_id)
    msg_count = len(source_session.messages)

    # ② fork 点越界检查（从"钳位"改为"报错"，spec §5.1.3-2）
    if fork_point is not None and (fork_point < 0 or fork_point > msg_count):
        return _report(
            error=(
                f"fork 点越界: {fork_point}，"
                f"合法范围 0..{msg_count}（{msg_count} 条消息）"
            )
        )

    effective_fp = fork_point if fork_point is not None else msg_count

    # 生成新 session_id
    new_id = str(uuid.uuid4())

    # 截断消息前缀 + 分支摘要
    prefix = source_session.messages[:effective_fp]
    summary = branch_summary or _default_branch_summary(source_session, effective_fp)

    # 事件日志写入（event_store 不可用 → 仅 session JSON 零回归）
    event_error = ""
    inherited_count = 0
    if _is_event_store_available(event_store):
        result = _write_event_log(
            event_store, source_session_id, new_id, effective_fp, summary
        )
        inherited_count = result[0]
        event_error = result[1]

    # 同步生成 session JSON（双轨）——先事件日志后 session JSON，_event_backfill 不重复
    from llm_loop.core.session import Session

    branch = Session(
        session_id=new_id,
        messages=list(prefix),
        created_at=_now_iso(),
        title=(source_session.title or "未命名") + "（分支）",
        parent_id=source_session_id,
        branch_id=new_id,
        branch_summary=summary,
        channel=source_session.channel,
    )
    try:
        session_store.save(branch)
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("fork session JSON 保存失败（fail-open）: %s", exc)

    if event_error:
        return _report(
            new_id=new_id,
            inherited=inherited_count,
            success=False,
            error=event_error,
        )
    return _report(new_id=new_id, inherited=inherited_count, success=True)


def _write_event_log(
    event_store: Any,
    source_session_id: str,
    new_id: str,
    fork_point: int,
    summary: str,
) -> tuple[int, str]:
    """写新会话事件日志：物理复制 + session.created + session.forked.

    Returns:
        (inherited_event_count, error_message)；error_message 非空 = 失败。
    """
    # ① 源会话事件日志存在性检查（spec §5.1.3-1）
    if not event_store.exists(source_session_id):
        return 0, f"源会话事件日志不存在: {source_session_id}（session JSON 已生成）"

    source_events = event_store.read(source_session_id)
    if not source_events:
        return 0, f"源会话事件日志为空: {source_session_id}（session JSON 已生成）"

    # ③ 截断事件流
    inherited_events = _truncate_events(source_events, fork_point)

    # ⑤ 物理复制事件（保留 type/ts/payload，重分配 seq + event_id + session_id）
    try:
        for e in inherited_events:
            event_store.append_event(new_id, e)
    except Exception as exc:  # noqa: BLE001 — fail-open：已写入部分保留
        return len(inherited_events), f"事件物理复制写入失败（fail-open）: {exc}"

    # ⑥ 追加 session.created（新会话顶层快照）
    source_created = next(
        (e for e in source_events if e.type == "session.created"), None
    )
    created_payload: dict = dict(source_created.payload) if source_created else {}
    created_payload["parent_id"] = source_session_id
    created_payload["branch_id"] = new_id
    created_payload["branch_summary"] = summary
    created_payload["created_at"] = _now_iso()
    created_payload["updated_at"] = _now_iso()
    created_payload["version"] = 4

    try:
        event_store.append(new_id, "session.created", created_payload)
    except Exception as exc:  # noqa: BLE001 — fail-open
        return len(inherited_events), f"session.created 写入失败（fail-open）: {exc}"

    # 追加 session.forked（承载 fork 元信息，spec §6.1）
    forked_payload = {
        "source_session_id": source_session_id,
        "fork_point": fork_point,
        "inherited_event_count": len(inherited_events),
        "new_session_id": new_id,
        "fork_ts": _now_iso(),
    }
    try:
        event_store.append(new_id, "session.forked", forked_payload)
    except Exception as exc:  # noqa: BLE001 — fail-open
        return len(inherited_events), f"session.forked 写入失败（fail-open）: {exc}"

    return len(inherited_events), ""


def _truncate_events(events: list, fork_point: int) -> list:
    """截断事件流：保留前 fork_point 条消息对应的事件 + 截断点前的非消息事件.

    策略：找到第一个 index >= fork_point 的消息事件的 seq（first_dropped_seq），
    保留所有 seq < first_dropped_seq 的事件（含非消息事件如 session.created）。
    fork_point >= 全部消息数时继承全部。
    """
    if not events:
        return []

    # 计算消息事件数
    msg_events = [
        e for e in events
        if e.type == "message.appended" and isinstance(e.payload.get("index"), int)
    ]
    if fork_point >= len(msg_events):
        return list(events)

    # 找到第一个 index >= fork_point 的消息事件的 seq
    first_dropped_seq = None
    for e in events:
        if e.type == "message.appended":
            idx = e.payload.get("index")
            if (
                isinstance(idx, int)
                and idx >= fork_point
                and (first_dropped_seq is None or e.seq < first_dropped_seq)
            ):
                first_dropped_seq = e.seq

    if first_dropped_seq is None:
        return list(events)

    return [e for e in events if e.seq < first_dropped_seq]


def _default_branch_summary(parent: Any, fork_point: int) -> str:
    """分支摘要（确定性，不调 LLM）：分叉点后最近一条 assistant 消息前 200 字符."""
    messages = getattr(parent, "messages", [])
    for m in reversed(messages[fork_point:]):
        if getattr(m, "role", None) == "assistant" and getattr(m, "content", None):
            return m.content[:200]
    return ""
