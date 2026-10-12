"""Prompt eligibility gates for program-origin context.

Eligibility is intentionally stricter than semantic labelling.  A program block may be
perfectly valid STATUS/REFERENCE material and still be ineligible for automatic prompt
projection.  Unknown producers are deny-by-default; durable state remains retrievable.

R8.24-B B-3.1（B-D1）: lifecycle describes message age, never authorization.  The
``current_turn`` grant path is closed; memory snapshots are durable retrieval state
only.  ``would_have_granted`` observation counters shadow-check that no legitimate
path was denied during the observation period.
"""

from __future__ import annotations

import logging
from typing import Any

from llm_loop.core.injection_labels import InjectionLayer, detect_program_layer, infer_layer

logger = logging.getLogger(__name__)

# Explicit automatic-prompt producer allowlist.  Keep this as plain strings so the
# eligibility core does not depend on loop/err1210 enums (which would create a cycle).
# R8.24-B B-4.1 / 2026-09-03 echo-loop correction:
# program-final needs a structural assistant boundary for providers that reject a
# historical user→user shape, but that boundary must carry *zero model-visible
# control tokens*.  GLM live probe proves user→assistant(content="")→user is legal.
# Storage/event truth remains elsewhere; this value is only the neutral role frame.
PROGRAM_FINAL_PROTOCOL_BOUNDARY = ""
# Pre-fix durable sessions may still contain this leaked marker, and a model may echo
# it.  Keep the literal only as a scrub/detection sentinel; never project it as content.
LEGACY_PROGRAM_FINAL_MARKER = "[program-final]"
# Agency-first producer registry (2026-09-03): no program-owned dynamic block has
# automatic prompt authority. Task/memory/recovery/capability/status state remains
# retrievable/observable through explicit tools and runtime telemetry.
PROMPT_DYNAMIC_PRODUCER_SLOTS: frozenset[str] = frozenset()


def dynamic_prompt_layer(content: str, *, slot_kind: str | None) -> InjectionLayer | None:
    """Return a semantic layer only for an explicitly eligible dynamic producer.

    Semantic classification and prompt eligibility are separate decisions.  ``infer_layer``
    retains its legacy STATUS fallback for rendering compatibility, but that fallback must
    never grant a new/unknown producer prompt access.
    """

    slot = str(slot_kind or "").strip().lower()
    if slot not in PROMPT_DYNAMIC_PRODUCER_SLOTS:
        return None
    return infer_layer(str(content or ""), slot_kind=slot)


def is_memory_snapshot(message: Any) -> bool:
    md = getattr(message, "metadata", None) or {}
    return md.get("injection_kind") == "memory_snapshot"


# R8.24-B B-3.1（B-D1）: would_have_granted 观察期计数——记录"若旧逻辑本会
# 放行"的次数（B-G6 shadow 核对无误伤；一个观察期后按设计包确认后移除）。
_WOULD_HAVE_GRANTED: dict[str, int] = {"current_turn": 0, "memory_snapshot": 0}


def would_have_granted_snapshot() -> dict[str, int]:
    """Observation-period counters for grants the pre-B-3.1 logic would have made."""
    return dict(_WOULD_HAVE_GRANTED)


def _legacy_turn_match(message: Any, current_turn_ref: int | None) -> bool:
    md = getattr(message, "metadata", None) or {}
    raw_turn_ref = md.get("turn_ref")
    if current_turn_ref is None or raw_turn_ref is None:
        return False
    try:
        return int(raw_turn_ref) == int(current_turn_ref)
    except (TypeError, ValueError):
        return False


def _note_would_have_granted(kind: str, message: Any, current_turn_ref: int | None) -> None:
    if _legacy_turn_match(message, current_turn_ref):
        _WOULD_HAVE_GRANTED[kind] = _WOULD_HAVE_GRANTED.get(kind, 0) + 1


def memory_snapshot_prompt_eligible(message: Any, *, current_turn_ref: int | None) -> bool:
    """R8.24-B B-3.1（B-D1）: memory producer 的自动 prompt 权限已闭合.

    生命周期（turn 匹配）只描述消息年龄，不再构成授权——快照恒为可检索的
    durable 状态而非自动工作上下文（producer 代码移除属 E 包，同文件分批
    B 先 E 后；本判定不改 producer 注册表）。would_have_granted 观察期计数
    保留 shadow 核对面。
    """

    if not is_memory_snapshot(message):
        return True
    _note_would_have_granted("memory_snapshot", message, current_turn_ref)
    return False

# Legacy program-control frames predate lifecycle metadata.  New emitters MUST carry
# ``prompt_lifecycle=current_turn``; an unlabelled system frame with one of these exact
# prefixes is therefore historical control state and has no automatic prompt entitlement.
_LEGACY_EPHEMERAL_SYSTEM_PREFIXES = (
    "[停滞提醒]",
    "[搜索空结果提醒]",
    "[上下文溢出]",
    "[模型降级:",
    "[模型降级] 事实:",
)
_LEGACY_DECLARATION_REMINDER_PREFIX = (
    "[声明提醒] 你的最终回答中存在与工具回执不符的完成声明，请知悉"
    "（不影响本次输出，后续请如实声明）。"
)
# Pre-R8.10 auxiliary component failures were persisted as ordinary system messages.
# They remain durable history/audit facts but have no automatic prompt entitlement.
_LEGACY_PROGRAM_FAULT_PREFIX = "[程序异常]"


def current_turn_program_prompt_eligible(
    message: Any, *, current_turn_ref: int | None
) -> bool:
    """Gate persisted current-turn-only program controls by human-turn identity.

    A current-turn program frame may be replayed across tool/LLM rounds inside one human
    turn, but it loses prompt authority as soon as a new human turn starts.  Legacy
    unlabelled system control frames are deny-by-default because their controlling event
    has already happened and durable action/event state remains the source of truth.
    """

    md = getattr(message, "metadata", None) or {}
    # Canonical current human ingress is explicit provenance and never confused with a
    # program frame merely because the user discusses an internal-looking label.
    if (
        md.get("program_origin") is not True
        and str(md.get("origin_layer") or "") == InjectionLayer.USER_INSTRUCTION.value
    ):
        return True
    # R8.15/E08 + R8.18/E09: generic reference catalogs are durable/retrievable
    # state, not automatic working context. Deny canonical catalog frames even when
    # their turn_ref still matches the current human turn. Explicit search/tool
    # results use different message kinds and are unaffected.
    if md.get("injection_kind") in {"experience_tip", "session_digest_catalog"}:
        return False
    lifecycle = str(md.get("prompt_lifecycle") or "").strip().lower()
    if lifecycle == "current_turn":
        # R8.24-B B-3.1（B-D1）: current_turn 生命周期不再作为 prompt 授权——
        # 生命周期只描述消息年龄（fresh program_recovery 自动权限删除）。
        # would_have_granted 观察期计数保留 shadow 核对面（B-G6）。
        _note_would_have_granted("current_turn", message, current_turn_ref)
        return False
    if lifecycle:
        # Unknown persisted lifecycle is not an eligibility grant.
        return False
    # Explicit program provenance never gets an implicit history-side grant. New
    # producers must not bypass the dynamic producer registry by persisting a frame.
    if md.get("program_origin") is True:
        return False

    role = str(getattr(message, "role", "") or "")
    content = str(getattr(message, "content", "") or "").lstrip()
    if role == "system" and any(content.startswith(p) for p in _LEGACY_EPHEMERAL_SYSTEM_PREFIXES):
        return False
    if role == "system" and content.startswith(_LEGACY_PROGRAM_FAULT_PREFIX):
        return False
    # Legacy labelled program frames may predate metadata. Treat an explicit program
    # semantic label as program provenance; canonical modern human turns were already
    # returned above via origin_layer=user_instruction.
    if role in {"user", "system"}:
        layer = detect_program_layer(content)
        if layer not in (None, InjectionLayer.USER_INSTRUCTION):
            return False
    # Pre-R8.9 declaration reminders were program-generated as role=user without
    # metadata.  Match the exact historical sentence rather than the generic label so a
    # human discussing "[声明提醒]" remains ordinary user truth.
    return not (role in {"user", "system"} and content.startswith(_LEGACY_DECLARATION_REMINDER_PREFIX))
