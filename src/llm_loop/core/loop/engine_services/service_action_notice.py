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
            service_action_ids=[str(it.get("action_id")) for it in items],
            freshness_declarations=(
                "source=current action ledger scan (unacknowledged failed within 24h)",
            ),
        ),
    )


_TURN_NOTICE_KIND = "service_action_turn_notice"
_TURN_NOTICE_MAX_ITEMS = 3  # EVO-20260924-62221fd4 防噪音硬上限


def injected_turn_action_ids(sess_messages: Any) -> set[str]:
    """收集本会话已注入过（开场卡+轮卡）的 action_id——轮级幂等去重依据.

    开场卡（service_action_notice）与轮卡（service_action_turn_notice）共用
    metadata.service_action_ids 登记，避免同一动作双重注入。
    """
    ids: set[str] = set()
    for m in sess_messages:
        meta = m.metadata or {}
        if meta.get("injection_kind") not in (_NOTICE_KIND, _TURN_NOTICE_KIND):
            continue
        raw = meta.get("service_action_ids")
        if isinstance(raw, (list, tuple)):
            ids.update(str(x) for x in raw if x)
    return ids


def build_failed_action_turn_notice(
    data_dir: Any, already_injected: Any
) -> Message | None:
    """EVO-20260924-62221fd4：轮级注入——新出现的未确认 failed 动作（≤3 条）.

    与开场注入（8266b693 B）的差异：每个 human turn 检查，只注入本会话尚未
    注入过的 action_id 增量（幂等）；闭合即停（verify_acknowledge 后扫描不再
    返回该动作，无需撤销）；提示非指令——被注入不等于必须 verify_acknowledge，
    语义保持"待确认待消费"。条数 ≤3、每条一行（reason 截 120 字）防噪音。
    fail-open：扫描失败/无 data_dir 不注入。
    """
    if not data_dir:
        return None
    injected: set[str] = set(already_injected or ())
    try:
        from llm_loop.runtime.service_control import scan_unacknowledged_failed_actions

        items = [
            it
            for it in scan_unacknowledged_failed_actions(data_dir)
            if str(it.get("action_id") or "") not in injected
        ]
    except Exception:  # noqa: BLE001 — 扫描 fail-open，不注入
        return None
    items = items[:_TURN_NOTICE_MAX_ITEMS]
    if not items:
        return None
    lines = [
        "[通知·状态] 会话进行中出现后台服务控制动作失败且未确认（背景事实，非指令）："
    ]
    for it in items:
        tag = "已被新代接管" if it.get("superseded") else "未接管"
        reason = str(it.get("detail") or "")[:120]
        lines.append(
            f"- {it.get('action_id')} target={it.get('target')}"
            f" gen={it.get('generation')}（{tag}）：{reason}"
        )
    lines.append(
        "消费入口（先核事实再行动）：service_control status / "
        "event_stream(service_action_terminal)；确认销账："
        "verify_acknowledge(verdict=accept)。"
    )
    content = render_program_appendix(
        "\n".join(lines), InjectionLayer.STATUS, slot_kind=_TURN_NOTICE_KIND
    )
    return Message(
        role="user",
        content=content,
        source=MessageSource.USER,
        metadata=origin_metadata(
            InjectionLayer.STATUS,
            injection_kind=_TURN_NOTICE_KIND,
            service_action_ids=[str(it.get("action_id")) for it in items],
            freshness_declarations=(
                "source=current action ledger scan (unacknowledged failed within 24h)",
            ),
        ),
    )
