"""injection_assembly 阶段（design T5-C 第三批 / B4-C3-02）

注入装配五联：①R8.8 eligibility 过滤（unknown producer denied +
appendix 剥离 + 语义标注）；②leak quarantine 回滚分支 α 降级附加
（D-G2：默认 off 不可达，回滚期结束后整段退役）；③β 聚合口未知槽
观测（overreach 事件不阻断）；④inject_keys/packet 双面初始化；
⑤memory 授权探测（E-D1 detect_memory_reference）+ memory_snapshot
循环（consumed_filtering 判定 + 未授权 shadow 计数 + 授权双面注入）。
决策回传 BuildDecision.consumed_filtering（A-4）/ injection_eligibility。
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.injection_labels import (
    ensure_semantic_label,
    strip_program_appendix_notice,
)
from llm_loop.core.program_recovery import PROGRAM_RECOVERY_SLOT
from llm_loop.core.prompt_build.stages.consumed_filtering import (
    ADMIT,
    SKIP_UNAUTHORIZED,
    memory_snapshot_admission,
)
from llm_loop.core.prompt_eligibility import dynamic_prompt_layer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InjectionAssemblyOutcome:
    """注入装配产出（后续 COG/预算段消费）."""

    inject_parts: list[tuple[str | None, str]] = field(default_factory=list)
    inject_keys: list[str] = field(default_factory=list)
    packet_parts: list[tuple[str | None, str]] = field(default_factory=list)
    packet_keys: list[str] = field(default_factory=list)
    packet_memory_seq: int = 0
    consumed_filtering: dict[str, Any] = field(default_factory=dict)
    injection_eligibility: dict[str, Any] = field(default_factory=dict)


def assemble_injections(
    *,
    inject_parts: list[tuple[str | None, str]],
    leak_downgrade_parts: list[tuple[str | None, str]] | None,
    sess: Any,
    r6_ingress_truth: Any,
    record_action: Callable[..., Any],
) -> InjectionAssemblyOutcome:
    """注入装配主函数（原 _build_llm_messages L840-972 段语义原样）."""
    out = InjectionAssemblyOutcome(inject_parts=list(inject_parts))
    _eligibility = {"unknown_producer_denied": 0, "admitted": 0}
    # R8.8 eligibility precedes semantic profile/budget. ``infer_layer`` may retain
    # its legacy STATUS rendering fallback, but an unknown producer must not gain
    # prompt access merely by reaching this list.
    _eligible_inject_parts: list[tuple[str | None, str]] = []
    for _slot, _content in out.inject_parts:
        if not str(_content or "").strip():
            continue
        _eligible_layer = dynamic_prompt_layer(_content, slot_kind=str(_slot or ""))
        if _eligible_layer is None:
            with contextlib.suppress(Exception):
                record_action(
                    "action.prompt_eligibility",
                    "unknown_producer_denied",
                    f"slot={str(_slot or '<none>')[:64]}",
                )
            _eligibility["unknown_producer_denied"] += 1
            continue
        _eligible_inject_parts.append(
            (
                _slot,
                ensure_semantic_label(
                    strip_program_appendix_notice(_content),
                    _eligible_layer,
                    slot_kind=str(_slot or ""),
                ),
            )
        )
        _eligibility["admitted"] += 1
    out.inject_parts = _eligible_inject_parts
    out.injection_eligibility = _eligibility
    # agent_trace_leak 4.2/4.3 + R8.24-D DT-1.2（D-G2）: α 降级产物并入段仅存于
    # LFL_LEAK_QUARANTINE=on/shadow 回滚分支内（默认 off 不可达；回滚期结束后
    # 整段退役删除）；β 聚合口槽键一致性观测（未知槽 → overreach 观测事件，
    # 不阻断——注入位置 P1-10 缓存前缀零破坏）。leak_downgrade 槽键已从
    # _known_slots 移除（D-G2：allowlist 外旁路身份退役；on 回滚态产物触发
    # overreach 观测事件 = 回滚通道使用审计留痕）。
    with contextlib.suppress(Exception):
        from llm_loop.core.trace_leak.leak_events import current_quarantine_mode

        if leak_downgrade_parts and current_quarantine_mode() in ("on", "shadow"):
            out.inject_parts = list(out.inject_parts) + [
                (slot, content) for slot, content in leak_downgrade_parts
            ]
    try:
        # 惰性 import（结构性）：err1210 位于 loop 包，顶层 import 会形成
        # stages→loop→build→stages 环（B4-C3-03 实证）；SlotKind 仅观测用。
        from llm_loop.core.loop.err1210 import SlotKind

        _known_slots = {
            str(SlotKind.INTEROP),
            str(SlotKind.TIP),
            str(PROGRAM_RECOVERY_SLOT),
            "memory",
            "task_active",
        }
        for _slot, _content in out.inject_parts:
            if _slot is not None and str(_slot) not in _known_slots:
                from llm_loop.core.trace_leak import leak_events as _tle

                _tle.emit_leak_event(
                    _tle.LEAK_CHANNEL_OVERREACH,
                    entry="build.inject_parts_aggregate",
                    session_id=sess.session_id,
                    content=str(_content or ""),
                    basis=f"聚合口未知注入槽 slot={str(_slot)[:64]}（来源一致性观测）",
                )
    except Exception:  # noqa: BLE001 — 观测 fail-open
        logger.debug("build β 聚合口观测失败（fail-open）", exc_info=True)
    out.inject_keys = [f"dynamic:{i}" for i in range(len(out.inject_parts))]
    out.packet_parts = list(out.inject_parts)
    out.packet_keys = list(out.inject_keys)
    # R8.24-E E-D1（E-1.x/E-3.2②）: E07 auto memory 退出 → RETRIEVABLE_ONLY。
    # 自动投影通道死亡（B-3.1 恒 False 底线保留）；恢复路径 1 = input-side
    # 显式指代（"按我之前的 X/你记得 Y 吗"）授权一次——命中本轮 ingress 时
    # 全部 memory_snapshot 以真实数据投影（memory_authorized 授权通道，非
    # 自动 producer）；路线 2 = search_records(kind=memory)（E7 实证已有）；
    # 路线 3 = playbook 显式查询。shadow 态 would_inject 计数留痕。
    try:
        from llm_loop.core.loop.input_authorization import (
            current_latent_channel_mode,
            detect_memory_reference,
        )

        _mem_ref_text = str(r6_ingress_truth or "")
        _mem_authorized = detect_memory_reference(_mem_ref_text)
        _lat_mode = current_latent_channel_mode()
    except Exception:  # noqa: BLE001 — resolver 不可用 fail-open 视为未授权
        _mem_authorized = False
        _lat_mode = "off"
    _consumed = {
        "mem_authorized": bool(_mem_authorized),
        "lat_mode": _lat_mode,
        "resolved_episode_skipped": 0,
        "not_memory_skipped": 0,
        "unauthorized_skipped": 0,
        "blank_or_ineligible_skipped": 0,
        "admitted": 0,
    }
    for _m in sess.messages:
        _adm = memory_snapshot_admission(_m, mem_authorized=_mem_authorized)
        if _adm.kind == SKIP_UNAUTHORIZED:
            # 未授权零投影（E-G1：automatic memory chars=0）；shadow 计数
            if _lat_mode == "shadow":
                with contextlib.suppress(Exception):
                    record_action(
                        "action.latent_channel",
                        "memory_would_inject",
                        f"chars={_adm.chars};reason=unauthorized_shadow_count",
                    )
            _consumed["unauthorized_skipped"] += 1
            continue
        if _adm.kind == "skip_resolved_episode":
            _consumed["resolved_episode_skipped"] += 1
            continue
        if _adm.kind == "skip_not_memory":
            _consumed["not_memory_skipped"] += 1
            continue
        if _adm.kind != ADMIT:
            _consumed["blank_or_ineligible_skipped"] += 1
            continue
        _labeled = _adm.labeled or ""
        out.inject_parts.append(("memory_authorized", _labeled))
        out.inject_keys.append(f"memory-authorized:{out.packet_memory_seq}")
        out.packet_parts.append(("memory_authorized", _labeled))
        out.packet_keys.append(f"packet-memory:{out.packet_memory_seq}")
        out.packet_memory_seq += 1
        with contextlib.suppress(Exception):
            record_action(
                "action.memory_authorization",
                "authorized_retrieval_inject",
                f"chars={len(_labeled)}",
            )
        _consumed["admitted"] += 1
    out.consumed_filtering = _consumed
    return out
