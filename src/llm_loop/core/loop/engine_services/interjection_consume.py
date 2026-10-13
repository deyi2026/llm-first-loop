"""Phase4 断环抽取（R9-P2-06a：runtime 环恒 0）.

`_consume_live_interjections` 原属 engine.py；Phase4 M1 起被 tool_cycle 间隙
收割复用（函数级 import 形成 engine<->tool_cycle 新环，守卫拦截）。抽取为独立
模块：engine 与 tool_cycle 均从本模块 import，依赖方向保持无环（本模块仅依赖
core 层外部模块，不回引 engine/tool_cycle）。
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, cast

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak.invariant import (
    correct_mislabeled_metadata,
    metadata_satisfies_invariant,
)

logger = logging.getLogger(__name__)


def _consume_live_interjections(
    engine: Any,
    session_id: str,
    sess: Any,
    *,
    at_final_gate: bool = False,
    via: str = "round_start",
) -> list[str]:
    """Persist pending genuine-human steer messages at a safe model-round boundary.

    The Web thread only queues frozen facts into the active RunHandle.  This function
    runs on the owning engine worker, keeping Session mutation single-writer.  A row is
    acknowledged only after it has crossed the same ingress guard and Session/Event
    persistence path as an ordinary human message.

    Phase4 M3：via∈{round_start, final_gate, gap_harvest} 为消费点事实戳记
    （供 hq 条目四桶机械归属，§7），不参与任何决策。
    """
    runner = getattr(engine, "runner", None)
    take = getattr(runner, "take_interjections", None)
    if runner is None or not getattr(runner, "enabled", False) or not callable(take):
        return []
    rows = cast(list[dict[str, Any]], take(session_id))
    if not rows:
        return []

    accepted_texts: list[str] = []
    for _row_idx, row in enumerate(rows):
        text = str(row.get("message") or "")
        metadata: dict[str, Any] = {}
        raw_attachments = row.get("attachment_facts")
        if isinstance(raw_attachments, list):
            metadata["attachments"] = [
                dict(item) for item in raw_attachments if isinstance(item, dict)
            ]
        queue_id = str(row.get("queue_id") or "")
        if queue_id:
            metadata["human_turn_queue_id"] = queue_id
            metadata["human_interjection"] = True
        metadata.update(origin_metadata(InjectionLayer.USER_INSTRUCTION))
        msg = Message(
            role="user",
            content=text,
            source=MessageSource.USER,
            metadata=metadata,
        )

        try:
            from llm_loop.core.trace_leak.user_ingress_guard import GuardAction, guard_user_write

            verdict = guard_user_write(
                sess,
                msg,
                row.get("_ingress"),
                entry="engine.interject",
                data_dir=engine.settings.data_dir,
            )
            if verdict.action is GuardAction.DENY:
                logger.warning("interjection ingress denied: sid=%s qid=%s", session_id, queue_id)
                # Phase3 G1 denied 分级（D5 前同形路径：被拒项此前静默滞留 pending，
                # 最终被 reaper 误标为 interject_run_ended，与孤儿不可区分）。
                # 回执回调 fail-open（不变量 6）；原因取守卫 verdict 摘要，不打正文（D6）。
                _deny_reason = str(getattr(verdict, "reason", "") or "ingress_denied")[:120]
                _cb = row.get("_on_denied")
                if callable(_cb):
                    try:
                        _cb(_deny_reason)
                    except Exception:  # noqa: BLE001 — 回执失败不得阻断消费循环
                        logger.warning("interjection denied-receipt failed (fail-open)", exc_info=True)
                with contextlib.suppress(Exception):
                    engine._record_action(
                        "human.interjection",
                        "denied",
                        f"queue_id={queue_id}; reason={_deny_reason}",
                    )
                continue
            msg = verdict.message
        except ImportError:  # pragma: no cover - same fail-open assembly rule as run ingress
            logger.warning("interjection ingress guard unavailable (fail-open)", exc_info=True)

        try:
            if metadata_satisfies_invariant(msg.metadata) is False:
                msg.metadata = correct_mislabeled_metadata(msg.metadata)
        except Exception:  # noqa: BLE001 - invariant diagnostics must not invent a denial
            logger.warning("interjection metadata invariant check failed (fail-open)", exc_info=True)

        try:
            sess.messages.append(msg)
            engine._append_message_event(sess, msg)
            engine.session.save(sess)
        except Exception:
            # Phase4 §4.4 消费故障恢复（M1 审查 P1-1）：持久化失败的行与其后
            # 未处理行按原序回插 mailbox 头；ack 未触发 → 持久队列条目保持必达；
            # 异常按轮首同款语义传播使 run 可见失败（不静默丢行）。
            with contextlib.suppress(Exception):
                _requeue = getattr(runner, "requeue_interjections_front", None)
                if callable(_requeue):
                    _requeue(session_id, rows[_row_idx:])
            raise
        engine._run_state().current_turn_ref = len(sess.messages) - 1
        engine._run_state().active_run_ingress_message = msg
        accepted_texts.append(text)
        ack = getattr(runner, "acknowledge_interjection", None)
        if callable(ack):
            # Phase4 M3 分桶戳记（§7）：消费点事实（via）+ 本轮打断回执事实
            # （run_state.last_receipt_interrupted，tool_cycle 回执落盘时置位）；
            # fail-open（acknowledge 内部兜底），分桶派生在 aggregate。
            with contextlib.suppress(Exception):
                ack(
                    row,
                    consumed_via=via,
                    interrupt_receipt=bool(
                        getattr(engine._run_state(), "last_receipt_interrupted", False)
                    ),
                )
        with contextlib.suppress(Exception):
            engine._record_action(
                "human.interjection",
                "received",
                f"queue_id={queue_id}; turn_ref={len(sess.messages) - 1}",
            )
        # Phase3 G1 applied/cbf 回执 stash（fail-open，不变量 6）：applied 在首个
        # 工具派发或终答出口由 _fire_interject_applied 触发；cbf 仅在终答结算
        # 边界消费（at_final_gate=True）时 stash——轮边界消费的行不该被后续
        # gate 误触发 CBF 分级；同批多行的回执全部保留（审查 P2-2：不再逐行重置）。
        try:
            rs = engine._run_state()
            if callable(row.get("_on_applied")):
                rs.interject_applied_callbacks.append(
                    {"queue_id": queue_id, "cb": row["_on_applied"]}
                )
            if at_final_gate and callable(row.get("_on_cbf")):
                rs.interject_cbf_pending.append(
                    {"queue_id": queue_id, "cb": row["_on_cbf"]}
                )
        except Exception:  # noqa: BLE001 — 回执 stash 失败不得阻断消费
            logger.warning("interjection receipt stash failed (fail-open)", exc_info=True)
    return accepted_texts
