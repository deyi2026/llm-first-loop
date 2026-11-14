"""Publish-completion closeout notice (EVO-20261112-fd945e83, D8, human exec_override).

发布完成事件钩子的通知侧：update 链（publish+restart）verify=confirmed_ok
落账后，向会话注入 STATUS 层提醒（非指令），把「发布已完成、收口待办」
从模型自觉（PLAN D1 文档约束）变为程序侧必然可见。

通道与治理（对齐 EVO-20260924-8266b693/62221fd4 先例）：
- 开场卡（每会话首个 genuine human turn 注入一次）+ 轮卡（会话进行中出现
  的增量，幂等去重，≤3 条）；
- STATUS 层非祈使语调、程序附录仲裁句（render_program_appendix）、
  不写 payload 正文、每条一行；
- 闭合即停：promo_closeout.py 收口成功后经
  write_publish_closeout_dismissal 写豁免标记，扫描不再返回该动作；
- fail-open：扫描失败/无 data_dir 不注入任何内容。

L2-2/L2-6 准入理由（provider prompt 面影响声明）：本通知是
STATUS 层程序附录（origin_layer=status，非 user_instruction），
不携带指令性祈使内容，消费入口全部指向工具调用（promo_closeout.py /
service_control status），与既有 service_action_notice 同一契约；
弱模型档行为对照见 tests/unit/test_publish_closeout_notice.py
（注入位置/元数据/语调与先例逐字段同构，行为面等价于已验证先例）。
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

_NOTICE_KIND = "publish_closeout_notice"
_TURN_NOTICE_KIND = "publish_closeout_turn_notice"
_TURN_NOTICE_MAX_ITEMS = 3  # 防噪音硬上限（对齐 62221fd4）


def _closeout_hint_line() -> str:
    return (
        "收口出口（先核事实再行动）：按 docs/promotion/PLAN-20261011"
        "-new-original-topics.md 班次规程 D1 第 2–5 步收口，或执行 "
        "scripts/promo_closeout.py（成功后本提醒自动闭合）。"
    )


def build_publish_closeout_notice_message(data_dir: Any) -> Message | None:
    """开场卡：存在已验证发布完成且未收口的动作时返回提醒 Message，否则 None."""

    if not data_dir:
        return None
    try:
        from llm_loop.runtime.service_control import scan_publish_closeout_pending

        items = scan_publish_closeout_pending(data_dir)
    except Exception:  # noqa: BLE001 — 扫描 fail-open，不注入
        return None
    if not items:
        return None
    lines = [
        "[通知·状态] 存在已验证完成、尚未收口的发布动作（背景事实，非指令）："
    ]
    for item in items[:5]:
        lines.append(
            f"- {item.get('action_id')} target={item.get('target')}"
            f" gen={item.get('generation')}（{str(item.get('updated_at') or '')[:19]}）"
        )
    lines.append(_closeout_hint_line())
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
                "source=current action ledger scan (verified update succeeded within 24h)",
            ),
        ),
    )


def injected_publish_action_ids(sess_messages: Any) -> set[str]:
    """收集本会话已注入过（开场卡+轮卡）的发布 action_id——轮级幂等去重依据."""

    ids: set[str] = set()
    for m in sess_messages:
        meta = m.metadata or {}
        if meta.get("injection_kind") not in (_NOTICE_KIND, _TURN_NOTICE_KIND):
            continue
        raw = meta.get("service_action_ids")
        if isinstance(raw, (list, tuple)):
            ids.update(str(x) for x in raw if x)
    return ids


def build_publish_closeout_turn_notice(
    data_dir: Any, already_injected: Any
) -> Message | None:
    """轮卡：会话进行中新完成的发布（≤3 条，幂等，闭合即停）.

    发布在后台异步完成 verify——从「下次碰巧查到」变成「下一轮必然看到」。
    被注入不等于必须立即收口（非指令）；promo_closeout 成功或 24h TTL
    自然过期后不再出现。
    """

    if not data_dir:
        return None
    injected: set[str] = set(already_injected or ())
    try:
        from llm_loop.runtime.service_control import scan_publish_closeout_pending

        items = [
            it
            for it in scan_publish_closeout_pending(data_dir)
            if str(it.get("action_id") or "") not in injected
        ]
    except Exception:  # noqa: BLE001 — 扫描 fail-open，不注入
        return None
    items = items[:_TURN_NOTICE_MAX_ITEMS]
    if not items:
        return None
    lines = [
        "[通知·状态] 会话进行中出现后台发布完成且已验证（背景事实，非指令）："
    ]
    for it in items:
        lines.append(
            f"- {it.get('action_id')} target={it.get('target')}"
            f" gen={it.get('generation')}：{str(it.get('verify_evidence') or '')[:100]}"
        )
    lines.append(_closeout_hint_line())
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
                "source=current action ledger scan (verified update succeeded within 24h)",
            ),
        ),
    )
