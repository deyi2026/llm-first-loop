"""EVO-20260920-213965a1 伴生修复: 恢复身份比较忽略委派 span 富化键.

Incident（session 32d694c9, 2026-09-20 12:03 起）: scheduled:schedule_wake
委派 run 被 episode_history 打上 delegated_span_ref/delegated_span_state
后，session-JSON 侧与事件重放侧逐条身份 diff 恒不匹配（343 条、仅差这
两个键），导致每条真人消息必现 interruption_recovery repair_failed
(prefix_mismatch)。富化键为 append 后运行态，不应视为历史分叉。
"""

from __future__ import annotations

from llm_loop.core.loop.events import _recovery_message_identity
from llm_loop.core.message import Message, MessageSource


def _msg(metadata: dict) -> Message:
    return Message(role="user", content="hi", source=MessageSource.USER, metadata=metadata)


def test_identity_ignores_delegated_span_enrichment() -> None:
    live = _msg({"delegated_span_ref": "span-1", "delegated_span_state": "closed"})
    replay = _msg({})
    assert _recovery_message_identity(live) == _recovery_message_identity(replay)


def test_identity_still_detects_real_metadata_divergence() -> None:
    live = _msg({"delegated_span_ref": "span-1", "real_key": "a"})
    replay = _msg({"real_key": "b"})
    assert _recovery_message_identity(live) != _recovery_message_identity(replay)
