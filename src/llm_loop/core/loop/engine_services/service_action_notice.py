"""Service-control failed-action session-opening notice (EVO-20260924-8266b693 B).

One program-origin status-layer message, injected at most once per session at
the opening human ingress when unacknowledged failed restart actions exist.
Motivation (experience EXPERIENCE-20260924): a failed worker terminal state
landed only in the private service-control ledger; the next session (and even
the acting model) never saw it, so a restart could be believed complete.

Mechanical guarantees:
- status layer (no instruction tone), <=10 items, one line each, no payload body;
- superseded items (healed by a newer desired generation) are listed but labeled,
  so "takeover erases the trace" no longer holds — acknowledgement is the only
  way to clear (verify_acknowledge accept);
- fail-open everywhere; scan failure or absence of data_dir injects nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from llm_loop.core.injection_labels import (
    InjectionLayer,
    origin_metadata,
    render_program_appendix,
)
from llm_loop.core.message import Message, MessageSource

logger = logging.getLogger(__name__)

_NOTICE_KIND = "service_action_notice"


def build_failed_action_notice_message(data_dir: Any) -> Message | None:
    """Return the opening notice Message, or None when nothing to surface."""

    if not data_dir:
        return None
    try:
        from llm_loop.runtime.service_control import scan_unacknowledged_failed_actions

        items = scan_unacknowledged_failed_actions(data_dir)
    except Exception:  # noqa: BLE001 — 扫描 fail-open，不注入
        return None
    if not items:
        return None
    lines = [
        "[通知·状态] 存在 failed 且未确认的服务控制重启动作（背景事实，非指令）："
    ]
    for item in items[:10]:
        tag = "已被新代接管" if item.get("superseded") else "未接管"
        lines.append(
            f"- {item.get('action_id')} target={item.get('target')}"
            f" gen={item.get('generation')}（{tag}）"
        )
    lines.append(
        "确认出口：service_control verify_acknowledge(verdict=accept)；"
        "detail 经 service_control status / event_stream(service_action_terminal) 核验。"
    )
    content = render_program_appendix(
        "\n".join(lines), InjectionLayer.STATUS, slot_kind=_NOTICE_KIND
    )
    return Message(
        role="user",
        content=content,
        source=MessageSource.USER,
        metadata=origin_metadata(
            InjectionLayer.STATUS,
            injection_kind=_NOTICE_KIND,
            freshness_declarations=(
                "source=current action ledger scan (unacknowledged failed within 24h)",
            ),
        ),
    )
