"""尾段装配阶段（B4-CLOSE-01 步A；语义原样迁自 build.py）.

user_truth wire 投影（R6 单信封 KEEP-HARD）→ 方向 C 持久化注入合并
（非 ingress 路径专用）→ 投影一致性门闸（seq/ver/built_hash 水印，
fail-open）→ cache 门禁后检（合规再出闸，fail-open）→ 压缩审计
（BuildAudit.compaction_audit 统计）。
"""

import logging
from dataclasses import dataclass, replace
from typing import Any

from llm_loop.core.loop.focus import _INJECTION_PREFIX
from llm_loop.core.prompt_build import BuildAudit
from llm_loop.core.prompt_build.stages.compaction_audit import run_compaction_audit
from llm_loop.core.prompt_build.stages.projection_gate import (
    run_projection_gate,
)
from llm_loop.core.prompt_build.stages.user_truth import run_user_truth_wire

logger = logging.getLogger(__name__)


def merge_persisted_tail_injections(
    built: list[dict], registered_idx: set[int]
) -> tuple[int, list[dict], list[int]]:
    """方向 C（2026-08-29）: 尾部持久化注入 wire 级合并（build 出口调用）.

    背景: EVO-20260827-f42496bc 将 memory 注入改为持久化（engine wrap+append 进
    sess.messages）后，历史投影尾部出现"用户消息+持久化注入"连续 user 对（主区
    883b4725 实测 510/511 形态，1210 结构触发根因形态）；_inject_parts 聚合只
    覆盖动态消费槽，不含已持久化消息。

    规则: 尾部连续 user 群（≥2 条）中，不在 registered_idx（动态注入登记）且
    content 以 _INJECTION_PREFIX 开头的持久化注入条，并入前一条 user（content
    追加 "\\n\\n"+原文，逐字保留）。群首注入（无前一条可并）/用户真实消息/登记条
    一律保留原位。
    """
    tail_start = len(built)
    for i in range(len(built) - 1, -1, -1):
        if built[i].get("role") != "user":
            tail_start = i + 1
            break
    else:
        tail_start = 0  # 全 user 极端形态（防御）
    if len(built) - tail_start < 2:
        return tail_start, [], []
    kept: list[dict] = []
    removed: list[int] = []
    for j in range(tail_start, len(built)):
        cand = built[j]
        if (
            kept
            and j not in registered_idx
            and str(cand.get("content") or "").startswith(_INJECTION_PREFIX)
        ):
            prev = kept[-1]
            if prev.get("role") == "user":  # 群内恒真，防御性保留
                prev["content"] = (
                    str(prev.get("content") or "")
                    + "\n\n"
                    + str(cand.get("content") or "")
                )
                removed.append(j)
                continue
        kept.append(cand)
    return tail_start, kept, removed


@dataclass(slots=True)
class TailAssemblyOutcome:
    """尾段装配产物（wire 最终序列 + 注入登记/门闸/缓存 hint 回写面）."""

    built: list[dict]
    injections: list[Any]
    gate_state: Any = None
    cache_gate_hint: str | None = None


def run_tail_assembly(
    *,
    built: list[dict],
    base: list[Any],
    memory_msgs: list[Any],
    system_prompt: str,
    tail_msgs: list[Any] | None,
    prefix_len: int,
    resolved_label: str,
    effective_budget: int,
    sess_anchor: int,
    provider_id: str,
    evidence_manifest_content: str,
    registry_snapshot: Any = None,
    reasoning_tail_fn: Any,
    compact_view_box: Any,
    anchor_moved: bool,
    ingress_truth: Any,
    injections: list[Any],
    settings: Any,
    sess: Any,
    decision: Any,
    record_action: Any,
    cache_monitor: Any,
    cache_gate_stable_fp: Any,
    last_history_compacted: Any,
    anchor_sess: Any,
) -> TailAssemblyOutcome:
    """R6 单信封 → 方向 C → 投影门 → cache 后检 → 压缩审计（语义原样）."""
    # ── INJECTION-GOVERNANCE R6: initial human-ingress wire projection ──
    # KEEP-HARD：用户语义保真；storage 原文零改动，仅 provider 视图投影为
    # program appendix -> fixed boundary -> exact user truth 单信封；工具轮
    # 排除语义见 stages/user_truth.py docstring。
    built, injections, _r6_applied = run_user_truth_wire(
        built,
        ingress_truth=ingress_truth,
        injections=injections,
        record_action=record_action,
    )

    # ── 方向 C（2026-08-29）: legacy/tool-followup tail merge ──
    # R6 initial ingress already owns the single-envelope contract. Direction C remains
    # only for non-ingress/tool-followup/legacy direct-build paths; it must never append
    # program material after a current human truth that R6 has just projected.
    if not _r6_applied and ingress_truth is None:
        try:
            _reg_idx = {e.msg_idx for e in injections}
            _ts, _kept, _removed = merge_persisted_tail_injections(built, _reg_idx)
            if _removed:
                built[_ts:] = _kept
                # InjectedEntry is frozen; remap by replacement rather than mutating
                # msg_idx in place.  Otherwise strip/defer may target the pre-merge index.
                injections = [
                    replace(
                        _entry,
                        msg_idx=_entry.msg_idx
                        - sum(
                            1
                            for _removed_idx in _removed
                            if _removed_idx < _entry.msg_idx
                        ),
                    )
                    for _entry in injections
                ]
        except Exception:  # noqa: BLE001 — 合并失败 fail-open（原样发送）
            logger.warning(
                "build: 方向 C 持久化注入合并失败，原样发送（fail-open）", exc_info=True
            )
    # EVO-20260817-b6554376: 投影一致性门闸（seq 历史水印 + ver 参数水印 +
    # built_hash 输出水印；借鉴 DSH seq 水印，fail-open 不阻断 run）
    _gate_state = run_projection_gate(
        built=built,
        base=base,
        memory_msgs=memory_msgs,
        system_prompt=system_prompt,
        tail_msgs=tail_msgs,
        prefix_len=prefix_len,
        resolved_label=resolved_label,
        effective_budget=effective_budget,
        sess_anchor=sess_anchor,
        provider_id=provider_id,
        evidence_manifest_content=evidence_manifest_content,
        reasoning_tail=reasoning_tail_fn(
            settings,
            resolved_label=resolved_label,
            registry_snapshot=registry_snapshot,
        ),
        settings=settings,
        last_history_compacted=last_history_compacted,
        sess=sess,
        decision=decision,
        record_action=record_action,
    )
    # EVO-20260817-72fcd94a L3 发送前门禁·后检（合规再出闸）: 校验稳定段与该 session
    # 基线一致；不一致 → 审计 + hint（run 末注入 final_answer），fail-open 不阻断发送。
    cache_gate_hint: str | None = None
    try:
        cache_gate_hint = cache_monitor.postcheck(sess.session_id, cache_gate_stable_fp)
        if cache_gate_hint:
            record_action("run.cache_gate", "drift", cache_gate_hint)
    except Exception:  # noqa: BLE001 — 门禁失败 fail-open
        cache_gate_hint = None
    # R8.17/E10 压缩审计（统计落 BuildAudit.compaction_audit）
    audit = BuildAudit()
    run_compaction_audit(
        built=built,
        decision=decision,
        audit=audit,
        compact_view_box=compact_view_box,
        anchor_moved=anchor_moved,
        session_id=sess.session_id,
        anchor_sess=anchor_sess,
        data_dir=settings.data_dir,
        record_action=record_action,
    )
    return TailAssemblyOutcome(
        built=built,
        injections=injections,
        gate_state=_gate_state,
        cache_gate_hint=cache_gate_hint,
    )
