"""尾部槽收集阶段（design T5-C 第二批 / B4-C2-04）.

四槽聚合收集（P1 9.1 / err1210 8.4 Verdict：尾部连续 user 条数结构性
消除）：recovery one-shot（R4）/ memory fail-open 回退（f42496bc 持久化
后的兜底）/ interop+tip 尾槽消费（E-D2 tip 视图退出）/ defer 回填身份
匹配 / β 出口观测 / hotcard+gate_note 回放标记退休（R8.14/R8.11）。
一次性消费清理由调用点回写（stage 不持 self 面）。
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.loop.err1210 import SlotKind
from llm_loop.core.program_recovery import PROGRAM_RECOVERY_SLOT

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TailSlotsOutcome:
    """尾槽消费产出（状态机新值由调用点回写 self 面）."""

    defer_refs: list[Any] = field(default_factory=list)
    replay_slots: set[Any] = field(default_factory=set)


def collect_persisted_and_recovery(
    *,
    inject_parts: list[tuple[str | None, str]],
    current_turn_ref: Any,
    pending_recovery: Any,
    memory_msgs: Any,
    sess: Any,
    r6_ingress_truth: Any,
    record_action: Callable[..., Any],
) -> None:
    """memory 持久化探测（ed4c1350 turn_ref 身份匹配）+ recovery 消费 + 兜底."""
    # EVO-20260818（spec §5.3.1-1 c/d，grill-me B1）: interop 外部协调注入——
    # 尾部追加（GATE_NOTE 模式，转 user），system+稳定历史前缀字节不变（注入轮不断前缀）;
    # env INTEROP_INJECT_TAIL=0 回退旧行为（头部插入，见 interop.py）
    # EVO-2026XXXX（spec §5.3.1-1c）: memory 检索注入尾部追加（GATE_NOTE 模式，转 user）——
    # 检索结果随查询变化（top_k 语义/关键词召回），前置注入每轮改变前缀首段 → 前缀断；
    # 尾部追加保持 system+稳定历史前缀字节不变（命中率不因 memory 变化受损）。
    # 2026-08-22 记忆注入统一包装（用户决策）: memory_msgs（[相关记忆]）此前直接
    # 转 user 尾部追加, 无"[上下文注入·非新指令] 继续当前任务"前缀 → AI 误读为
    # 独立消息 → "没有明确任务" → 反复 search 找回（实证 d1192d8c: 健康检查任务
    # 15+ 次 search_archive/search_records 死循环）。与 tail_msgs 同包装机制。
    # EVO-20260827-f42496bc: memory 注入已改为一次性持久化（engine 检索后
    # wrap+append 进 sess.messages，见 engine.py 理解段）——本函数不再追加
    # 动态 memory 段：历史投影自然带出持久化注入（存储字节稳定，下轮前缀
    # 命中不断崖）。此前每轮在此重新包装追加（含动态 anchor），下一轮真实
    # 回复顶替注入位置 → 前缀字节分叉 → provider 前缀缓存全断（断崖根因）。
    # memory_msgs 参数保留（签名兼容 + fail-open 路径: engine 持久化异常时
    # 仍可走旧动态注入，见下方 fallback 判断）。
    # EVO-20260827-ed4c1350: turn 快照注入位于 turn 入口（会话前部），多轮后
    # 尾部 8 条不再包含它——检查升级为 turn_ref 身份匹配（本 turn 已持久化
    # 即视为成功）；无 turn 上下文（旧会话/直调 build）回退旧尾部检查（零回归）。
    _turn_ref = current_turn_ref
    if _turn_ref is not None:
        _persisted_ok = any(
            (getattr(_m, "metadata", None) or {}).get("turn_ref") == _turn_ref
            and (getattr(_m, "metadata", None) or {}).get("injection_kind")
            == "memory_snapshot"
            for _m in sess.messages
        )
    else:
        _persisted_ok = any(
            getattr(_m, "metadata", None)
            and _m.metadata.get("persisted_injection")
            for _m in sess.messages[-8:]
        )
    # R4: recovery lives in a one-shot runtime slot.  Consume it at build start so it
    # cannot leak into a later tool-followup/rebuild.  Only an initial human ingress with
    # matching turn_ref may activate it; otherwise it is safely discarded.
    _pending_recovery = pending_recovery
    if _pending_recovery is not None:
        _pr_meta = getattr(_pending_recovery, "metadata", None) or {}
        _pr_turn_ref = _pr_meta.get("recovery_turn_ref")
        if r6_ingress_truth is not None and _pr_turn_ref == _turn_ref:
            inject_parts.append((PROGRAM_RECOVERY_SLOT, _pending_recovery.content))
        else:
            with contextlib.suppress(Exception):
                record_action(
                    "action.program_recovery",
                    "dropped_without_user_boundary",
                    f"recovery_turn_ref={_pr_turn_ref}; current_turn_ref={_turn_ref}",
                )
    if not _persisted_ok and memory_msgs:
        # fail-open 回退: 持久化失败（engine 异常路径）→ 兜底收集进聚合
        # （P1 9.1: 旧独立 wrap+append 撤销——保尾部连续 user ≤1；memory 非消费槽）
        for _m in memory_msgs:
            _c = str(_m.to_llm_dict().get("content") or "")
            if _c:
                inject_parts.append(("memory", _c))


def consume_tail_slots(
    *,
    inject_parts: list[tuple[str | None, str]],
    interop_tail: Any,
    tip_tail: Any,
    defer_refs: list[Any],
    replay_slots: set[Any],
    note_defer_replayed: Callable[..., Any],
    record_action: Callable[..., Any],
    cache_monitor: Any,
    session_id: str,
) -> TailSlotsOutcome:
    """interop/tip 尾槽消费 + defer 回填检测 + β 观测 + 回放标记退休."""
    tail_msgs = interop_tail
    _interop_orig = tail_msgs  # err1210 T4.1: 身份匹配用（区分 interop/tip/local 提示）
    # EVO-20260819-7bb7d689: 经验提示尾部追加槽并入统一消费（与 interop 同机制）——
    # 不进历史存储，build 末尾一次性追加（转 user），system+稳定历史前缀字节不变
    tip_msgs = tip_tail
    _tip_orig = tip_msgs
    if tip_msgs:
        tail_msgs = (tail_msgs or []) + tip_msgs
    # R8.8: provider-local evaluation/behaviour patches are not runtime prompt
    # authority. The old per-build command-shaped local hint is deliberately gone.
    # R8.18/E09: SessionDigest remains a deterministic diagnostic/retrieval helper,
    # but build no longer turns its generic catalog into prompt material or durable
    # session history.  Current tool results are already present in the active history
    # when the old catalog was emitted; after compaction the exact tool_call_id is
    # searchable through ArchiveStore/search_archive (which accepts ``digest:`` refs).
    # ``digest_enabled`` is therefore a compatibility capability flag, not an
    # automatic-prompt entitlement.
    # ── P1 尾部注入聚合（err1210 8.4 Verdict: STRUCTURE_TRIGGER 尾部连续 user 条数，
    # tasks 9.1 方案 A）：四槽产物合并单条 user（--- [slot:xxx] --- 分段标记保留语义），
    # wrap_injection 只包装一次、anchor 单份——build 尾部连续 user 条数恒 ≤1，
    # compact 首请求 1210 结构性消除（merge 变体双样本生产验证）。
    for _m in tail_msgs or []:
        # R8.24-E E-D2（E-5.1，E08 TIP replay 退出）: TIP 消息不再进入注入
        # parts（tail 视图消费面门控；存储/事件真相不动，retrieval plane
        # 保留一切）。shadow 态 would_inject 计数留痕。
        if _tip_orig and any(_m is _x for _x in _tip_orig):
            with contextlib.suppress(Exception):
                from llm_loop.core.loop.input_authorization import (
                    current_latent_channel_mode,
                )

                _lat_mode = current_latent_channel_mode()
                record_action(
                    "action.latent_channel",
                    "tip_tail_would_inject" if _lat_mode != "off" else "tip_tail_exited",
                    (
                        f"chars={len(str(getattr(_m, 'content', '') or ''))};"
                        f"mode={_lat_mode}"
                    ),
                )
            continue
        _d = _m.to_llm_dict()
        if _d.get("role") == "system":
            _d["role"] = "user"  # system 静态: 转独立 user 尾部追加
            _c = str(_d.get("content") or "")
            if _c:
                _d["content"] = _c
        _slot = None
        if _interop_orig and any(_m is _x for _x in _interop_orig):
            _slot = SlotKind.INTEROP
        inject_parts.append((_slot, str(_d.get("content") or "")))
    # err1210 T4.1→9.1: defer 回填消息消费检测（is 身份匹配，聚合收尾统一处理）
    _refs = defer_refs or []
    if _refs and tail_msgs:
        _consumed_ids = {id(_m) for _m in tail_msgs}
        _kept = [
            (_r_slot, _r_ref)
            for _r_slot, _r_ref in _refs
            if not (
                id(_r_ref) in _consumed_ids
                and note_defer_replayed(session_id, _r_slot)
            )
        ]
        defer_refs = _kept

    _observe_tail_exit(tail_msgs=tail_msgs, record_action=record_action, session_id=session_id)
    _slots = _retire_replay_markers(
        replay_slots=replay_slots,
        cache_monitor=cache_monitor,
        session_id=session_id,
        record_action=record_action,
    )
    return TailSlotsOutcome(defer_refs=defer_refs, replay_slots=_slots)


def _observe_tail_exit(*, tail_msgs, record_action, session_id) -> None:
    # agent_trace_leak 4.3: β 挂载点——休眠 tail 消费链视图出口一致性观测。
    # 该链路现行生产者恒空（R8.13 后 live path 返回空），本观测不激活不改语义；
    # 若历史 defer 残留经此出口进入视图，须携带程序层标记（SlotKind 身份
    # 匹配不破坏，err1210.py:460,534 引用面零影响）。
    try:
        if tail_msgs:
            _tail_no_mark = [
                _m
                for _m in tail_msgs
                if not (getattr(_m, "metadata", None) or {}).get("origin_layer")
            ]
            if _tail_no_mark:
                from llm_loop.core.trace_leak import leak_events as _tle

                _tle.emit_leak_event(
                    _tle.LEAK_CHANNEL_OVERREACH,
                    entry="build.interop_tail_view",
                    session_id=session_id,
                    content=str(getattr(_tail_no_mark[0], "content", "") or ""),
                    basis=(
                        f"tail 视图出口存在无程序层标记消息 count={len(_tail_no_mark)}"
                        "（休眠链路观测；仅视图不落盘）"
                    ),
                )
    except Exception:  # noqa: BLE001 — 观测 fail-open（spec 5.4.3-1）
        logger.debug("build β tail 出口观测失败（fail-open）", exc_info=True)


def _retire_replay_markers(
    *,
    replay_slots,
    cache_monitor,
    session_id,
    record_action,
) -> set:
    # R8.14/E24: hotcard remains a durable handoff artifact, not an automatic prompt source.
    # Cross-session is not continuation authorization.  Retire any pre-upgrade defer marker
    # here so a hot-reloaded process cannot resurrect an old HOTCARD slot into a later build.
    _slots = replay_slots or set()
    if str(SlotKind.HOTCARD) in _slots:
        _slots.discard(str(SlotKind.HOTCARD))
        replay_slots = _slots
        try:
            record_action(
                "handoff.hotcard",
                "retired_replay",
                "prompt_chars=0;reason=user_authorization_required",
            )
        except Exception:  # noqa: BLE001 — observability must not affect build
            logger.debug("build: hotcard replay retirement action failed", exc_info=True)
    # R8.11/E20: cache-gate intervention is runtime observability, not model input.
    # Consume its one-shot marker so it cannot churn forever, but emit zero prompt chars.
    # Legacy err1210 may have restored a gate_note slot; retire that replay marker here
    # rather than resurrecting old program prose into a new provider request.
    if cache_monitor.take_gate_note(session_id=session_id):
        _slots = replay_slots or set()
        if str(SlotKind.GATE_NOTE) in _slots:
            _slots.discard(str(SlotKind.GATE_NOTE))
            replay_slots = _slots
        try:
            record_action(
                "run.cache_gate",
                "observed_only",
                "prompt_chars=0",
            )
        except Exception:  # noqa: BLE001 — observability must not affect build
            logger.debug("build: cache gate observability action failed", exc_info=True)
    return _slots


@dataclass(slots=True)
class TailCollectionOutcome:
    """尾部槽收集 wiring 产物（B4-CLOSE-01 步C2；一次性消费面）."""

    inject_parts: list[tuple[str | None, str]]
    tail_msgs: Any
    defer_refs: list[Any]
    replay_slots: set[Any]


def run_tail_collection(
    *,
    sess: Any,
    memory_msgs: list[Any],
    r6_ingress_truth: Any,
    record_action: Any,
    cache_monitor: Any,
    current_turn_ref: Any,
    pending_recovery: Any,
    interop_tail: Any,
    tip_tail: Any,
    defer_refs: list[Any],
    replay_slots: set[Any],
    note_defer_replayed: Any,
) -> TailCollectionOutcome:
    """持久化/恢复/interop/tip 四路尾部槽收集接线（语义原样迁自 build.py）.

    collect_persisted_and_recovery（P1 9.1 聚合收集）→ tail_msgs
    原位合并（gate 水印面：interop+tip 合列表）→ consume_tail_slots
    （一次性消费 + replay 状态机推进）。调用点回写 self 面。
    """
    _inject_parts: list[tuple[str | None, str]] = []  # (slot|None=hint, content)——P1 9.1 聚合收集
    collect_persisted_and_recovery(
        inject_parts=_inject_parts,
        current_turn_ref=current_turn_ref,
        pending_recovery=pending_recovery,
        memory_msgs=memory_msgs,
        sess=sess,
        r6_ingress_truth=r6_ingress_truth,
        record_action=record_action,
    )
    tail_msgs = interop_tail  # 原位合并语义（gate 水印面用：interop+tip 合列表）
    if tip_tail:
        tail_msgs = (tail_msgs or []) + tip_tail
    _outcome = consume_tail_slots(
        inject_parts=_inject_parts,
        interop_tail=interop_tail,
        tip_tail=tip_tail,
        defer_refs=defer_refs,
        replay_slots=replay_slots,
        note_defer_replayed=note_defer_replayed,
        record_action=record_action,
        cache_monitor=cache_monitor,
        session_id=sess.session_id,
    )
    return TailCollectionOutcome(
        inject_parts=_inject_parts,
        tail_msgs=tail_msgs,
        defer_refs=_outcome.defer_refs,
        replay_slots=_outcome.replay_slots,
    )
