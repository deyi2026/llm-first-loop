"""尾段装配阶段（B4-CLOSE-01 步A；语义原样迁自 build.py）.

投影一致性门闸（seq/ver/built_hash 水印，
fail-open）→ cache 门禁后检（合规再出闸，fail-open）→ 压缩审计
（BuildAudit.compaction_audit 统计）。
"""

import logging
from dataclasses import dataclass
from typing import Any

from llm_loop.core.loop.focus import _INJECTION_PREFIX
from llm_loop.core.prompt_build import BuildAudit
from llm_loop.core.prompt_build.stages.compaction_audit import run_compaction_audit
from llm_loop.core.prompt_build.stages.projection_gate import (
    run_projection_gate,
)
from llm_loop.core.recent_continuity import apply_recent_continuity_suffix

logger = logging.getLogger(__name__)


def merge_persisted_tail_injections(
    built: list[dict], registered_idx: set[int]
) -> tuple[int, list[dict], list[int]]:
    """方向 C（2026-08-29）: 尾部持久化注入 wire 级合并（build 出口调用）.

    语义原样迁自 r9 e5ea806 权威线（tail_assembly 随迁版）; storage 不动。

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
    """尾段装配产物（wire 最终序列 + 门闸/缓存 hint 回写面）."""

    built: list[dict]
    gate_state: Any = None
    cache_gate_hint: str | None = None
    continuity: dict[str, Any] | None = None


def run_tail_assembly(
    *,
    built: list[dict],
    base: list[Any],
    system_prompt: str,
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
    settings: Any,
    sess: Any,
    decision: Any,
    record_action: Any,
    cache_monitor: Any,
    cache_gate_stable_fp: Any,
    cache_gate_system_fp: Any = "",
    tool_prefix_fp: Any = "",
    last_history_compacted: Any,
    anchor_sess: Any,
    current_turn_ref: int | None = None,
    interruption_resume: dict[str, Any] | None = None,
) -> TailAssemblyOutcome:
    """Projection gate → cache postcheck → compaction audit."""
    # No program-owned user tail is created by current production paths.  Historical
    # program frames are filtered before this stage; there is nothing to merge.
    built, _continuity = apply_recent_continuity_suffix(
        built,
        session_messages=list(getattr(sess, "messages", []) or []),
        current_turn_ref=current_turn_ref,
        interruption_resume=interruption_resume,
    )
    if _continuity.get("applied"):
        try:
            record_action(
                "run.recent_continuity",
                str(_continuity.get("source") or "applied"),
                "moved_after_user={};rehydrated={}".format(
                    int(_continuity.get("moved_after_user") or 0),
                    str(bool(_continuity.get("rehydrated"))).lower(),
                ),
            )
        except Exception:  # noqa: BLE001 — continuity observability is fail-open
            logger.debug("recent continuity telemetry failed", exc_info=True)
    # EVO-20260817-b6554376: 投影一致性门闸（seq 历史水印 + ver 参数水印 +
    # built_hash 输出水印；借鉴 DSH seq 水印，fail-open 不阻断 run）
    _gate_state = run_projection_gate(
        built=built,
        base=base,
        system_prompt=system_prompt,
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
        # 双轴后检（契约 §5.2）：system 轴判定漂移；tools 轴合法变更仅审计计数。
        # cache_gate_stable_fp（组合指纹）保留给调用方做边界保护/引擎引用，不进门禁。
        cache_gate_hint = cache_monitor.postcheck(
            sess.session_id, cache_gate_system_fp, tool_prefix_fp
        )
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
        gate_state=_gate_state,
        cache_gate_hint=cache_gate_hint,
        continuity=dict(_continuity),
    )
