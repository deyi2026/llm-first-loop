"""guard_user_write 写入守卫核心（tasks 3.4，design C2，spec 5.3.1-1）.

user 身份写入权的唯一判定点：``engine.run()`` 落盘前与 ``SessionStore.append()``
内部调用。

判定依据是"内容是否由人类输入通道产生"（白名单凭据），而非"写入代码位于
哪个模块"（spec 5.2.1-3）。模式配置 ``LFL_LEAK_GUARD_MODE``：

- ``observe``（缺省——灰度期安全兜底）：无凭据 user 写入放行 + 越权告警事件
- ``downgrade``：无凭据 user 写入降级为程序附录层标记（如实标记落盘）
- ``enforce``：无凭据 user 写入拒绝（不落盘 + 隔离记录 + 拒绝事件）

灰度策略（design §2.1.2 CG）：observe 先行，验收后切 enforce；fail-open
约束下 guard 异常回落放行 + ``leak.guard_fault`` 告警（spec 4.2-1）。
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass
from enum import Enum

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message
from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.ingress_token import is_whitelisted

logger = logging.getLogger(__name__)

GUARD_MODE_ENV = "LFL_LEAK_GUARD_MODE"
# 缺省 observe：web/routes.py 签发改造（红线 R-1）合入前，无凭据人类通道
# 必须保持 fail-open 放行；验收后切 enforce（design §2.1.2 取值策略）。
DEFAULT_GUARD_MODE = "observe"
_VALID_MODES = frozenset({"observe", "downgrade", "enforce"})


class GuardAction(Enum):
    """守卫动作值域（design §2.3.2）。"""

    ALLOW = "allow"
    DOWNGRADE = "downgrade"
    DENY = "deny"


@dataclass
class GuardVerdict:
    """守卫回执：动作 + 消息（DOWNGRADE 时为程序附录层改写体）+ 判定依据。"""

    action: GuardAction
    message: Message
    basis: str


def current_guard_mode() -> str:
    """读取守卫模式（每次现读，供灰度切换与测试 monkeypatch）。"""
    mode = str(os.environ.get(GUARD_MODE_ENV, "") or DEFAULT_GUARD_MODE).strip().lower()
    return mode if mode in _VALID_MODES else DEFAULT_GUARD_MODE


def downgrade_message(message: Message, *, injection_kind: str = "leak_downgrade") -> Message:
    """将 user 消息重构造为程序附录层标记（经单一真相源；保留既有可选键）。

    role/source 不变（对消费方投影零感知面）；仅 metadata 来源判定如实化。
    """
    preserved = {
        k: v
        for k, v in (message.metadata or {}).items()
        if k not in ("origin_layer", "program_origin")
    }
    message.metadata = origin_metadata(
        InjectionLayer.PROGRAM_RECOVERY,
        injection_kind=injection_kind,
        **preserved,
    )
    return message


def guard_user_write(
    sess: object,
    message: Message,
    ingress: object | None,
    *,
    entry: str = "user_ingress_guard",
) -> GuardVerdict:
    """user 身份写入权判定（fail-open；异常放行 + leak.guard_fault 告警）."""
    session_id = str(getattr(sess, "session_id", "") or "?")
    try:
        if message.role != "user":
            return GuardVerdict(GuardAction.ALLOW, message, "非 user-role 写入不在通道管辖面")

        if ingress is not None:
            if is_whitelisted(ingress):
                # 合法凭据路径：固化通道快照（token 本身不持久化）
                channel = str(getattr(ingress, "channel", "") or "?")
                ingress_entry = str(getattr(ingress, "entry", "") or "?")
                md = dict(message.metadata or {})
                md.setdefault("ingress_channel", channel)
                md.setdefault("ingress_entry", ingress_entry)
                message.metadata = md
                return GuardVerdict(
                    GuardAction.ALLOW, message, f"白名单通道凭据: {channel}/{ingress_entry}"
                )
            # 提供了凭据但不在白名单 → 通道越权（任何模式都告警）
            leak_events.emit_leak_event(
                leak_events.LEAK_CHANNEL_OVERREACH,
                entry=entry,
                session_id=session_id,
                content=message.content,
                basis="凭据不在白名单（越权通道写入）",
            )

        mode = current_guard_mode()
        if mode == "observe":
            leak_events.emit_leak_event(
                leak_events.LEAK_CHANNEL_OVERREACH,
                entry=entry,
                session_id=session_id,
                content=message.content,
                basis="observe 灰度：无白名单凭据的 user 写入放行并告警",
                extra={"guard_mode": mode},
            )
            return GuardVerdict(
                GuardAction.ALLOW, message, "observe 模式：放行 + 越权告警（灰度兜底）"
            )
        if mode == "downgrade":
            leak_events.emit_leak_event(
                leak_events.LEAK_DOWNGRADED,
                entry=entry,
                session_id=session_id,
                content=message.content,
                basis="downgrade 模式：无凭据 user 写入降级为程序附录层标记",
                extra={"guard_mode": mode, "injection_kind": "leak_downgrade"},
            )
            return GuardVerdict(
                GuardAction.DOWNGRADE,
                downgrade_message(message),
                "downgrade 模式：程序附录层标记如实化",
            )
        # enforce
        leak_events.emit_leak_event(
            leak_events.LEAK_CHANNEL_DENIED,
            entry=entry,
            session_id=session_id,
            content=message.content,
            basis="enforce 模式：白名单外 user 身份写入被拒绝",
            extra={"guard_mode": mode},
        )
        leak_events.write_quarantine(
            leak_events.LEAK_CHANNEL_DENIED,
            session_id=session_id,
            content=message.content,
            basis="enforce 拒绝的 user 写入内容（隔离留痕，不静默丢弃）",
        )
        return GuardVerdict(
            GuardAction.DENY, message, "enforce 模式：白名单外 user 写入拒绝"
        )
    except Exception:  # noqa: BLE001 — fail-open（spec 4.2-1）
        logger.warning("guard_user_write 异常（fail-open 放行）", exc_info=True)
        with contextlib.suppress(Exception):  # noqa: BLE001 — 告警失败不覆盖原判定
            leak_events.emit_leak_event(
                leak_events.LEAK_GUARD_FAULT,
                entry=entry,
                session_id=session_id,
                content=message.content if message is not None else "",
                basis="guard 内部异常，回落放行（fail-open）",
            )
        return GuardVerdict(GuardAction.ALLOW, message, "guard 异常 fail-open 放行")
