"""注入装配 + 认知预算接线簇（B4-CLOSE-01 步C3；语义原样迁自 build.py）.

授权投影（B4-C3-01）→ 注入装配（B4-C3-02）→ 认知门控/状态/
预算切分/packet（B4-C4-01）→ 聚合登记；聚合失败 fail-open 零注入
降级。decision/built/injections 同对象就地演进。
"""

import logging
from dataclasses import dataclass
from typing import Any

from llm_loop.core.injection_budget import DEFAULT_INJECTION_BUDGET_CHARS
from llm_loop.core.loop.err1210 import InjectedEntry, SlotKind, content_prefix_sha
from llm_loop.core.loop.focus import wrap_injection
from llm_loop.core.prompt_build.stages.authorization import resolve_authorized
from llm_loop.core.prompt_build.stages.budget_application import (
    apply_injection_budget,
)
from llm_loop.core.prompt_build.stages.cognitive import (
    resolve_cognitive_gate,
    run_cognitive_packet,
    run_cognitive_state,
)
from llm_loop.core.prompt_build.stages.injection_assembly import assemble_injections

logger = logging.getLogger(__name__)

# 写回哨兵：UNSET = 本轮未产生新预算值（调用点不写回，保留旧值——语义原样：
# 原代码 if 不进或 except 降级时 self._last_injection_budget 不更新）
_UNSET = object()

try:  # 惰性容错：import 失败回退平铺（语义随迁 build.py）
    from llm_loop.cognitive.compiler import compile_decision_packet
except Exception:  # pragma: no cover - 环境缺认知编译器时回退
    compile_decision_packet = None  # type: ignore[assignment]


@dataclass(slots=True)
class InjectionCognitiveOutcome:
    """注入+认知簇产物（self 面写回值；decision/built/injections 就地演进）."""

    last_injection_budget: Any


def run_injection_cognitive(
    *,
    sess: Any,
    settings: Any,
    built: list[dict],
    inject_parts: list[tuple[str | None, str]],
    leak_downgrade_parts: Any,  # 原调用点即 list[str]（trace_isolation 半面），assemble_injections 签名宽收
    r6_ingress_truth: Any,
    current_turn_ref: Any,
    record_action: Any,
    identity_cache: dict,
    anchor_sess: Any,
    injections: list[Any],
    decision: Any,
) -> InjectionCognitiveOutcome:
    """授权 → 注入装配 → 认知门控/状态/预算/packet → 聚合登记（语义原样）."""
    _inject_parts = inject_parts
    # B4-C3-01: task_active 升格 authorization 阶段（A-2 承载）；决策入 BuildDecision.authorization_slots
    decision.authorization_slots = resolve_authorized(
        inject_parts=_inject_parts,
        sess=sess,
        settings=settings,
        current_turn_ref=current_turn_ref,
        r6_ingress_truth=r6_ingress_truth,
        identity_cache=identity_cache,
        record_action=record_action,
    )
    # R8.8 eligibility precedes semantic profile/budget. ``infer_layer`` may retain
    # B4-C3-02: 注入装配迁 stages/injection_assembly（eligibility→quarantine→
    # β 观测→packet init→memory 授权双面注入）；consumed_filtering 判定独立
    # 防护模块（A-1 consumed 半面，D13 验收面①）；决策入 BuildDecision（A-4）。
    _assembly = assemble_injections(
        inject_parts=_inject_parts,
        leak_downgrade_parts=leak_downgrade_parts,
        sess=sess,
        r6_ingress_truth=r6_ingress_truth,
        record_action=record_action,
    )
    _inject_parts = _assembly.inject_parts
    _inject_keys = _assembly.inject_keys
    _packet_parts = _assembly.packet_parts
    _packet_keys = _assembly.packet_keys
    _packet_memory_seq = _assembly.packet_memory_seq
    _lat_mode = _assembly.consumed_filtering.get("lat_mode", "off")  # COG 锚点观测用（同轮同值）
    decision.consumed_filtering = _assembly.consumed_filtering
    decision.injection_eligibility = _assembly.injection_eligibility
    # 尾部连续 user 恒 ≤1（1210 结构性消除）；聚合失败 fail-open 降级零注入（不阻断构建）
    # Cognitive Runtime 门控解析 → stages/cognitive.py（B4-C4-01 第 1 步；design
    # §2.1.2 #12 独占模块，RETRIEVAL-ONLY，冻结态 promote 禁止）。tier/anchor_mode/
    # dual_source_guard 语义与 CR-R1 空 slots header-only 不变量（零注入安静轮
    # decision_visible=True）见该模块；冻结/提升决策入 decision.cog_freeze。
    _cog = resolve_cognitive_gate(
        settings,
        sess=sess,
        built=built,
        inject_parts_present=bool(_inject_parts),
        decision=decision,
    )
    _cog_mode_candidate = _cog.mode
    _cog_promoted = _cog.promoted
    _cog_compute_candidate = _cog.compute_candidate
    _has_existing_program = _cog.has_existing_program
    _recovery_render_parts: list[str] = []
    _budget_written = False
    if _inject_parts or _cog_compute_candidate or _has_existing_program:
        try:
            # 认知运行时状态装配 → stages/cognitive.py（B4-C4-01 第 2 步）：load/
            # schema v2 三态解包/Read Barrier（GoalStore 三路一致性 + rebuild
            # 回存 + state_revision 单调继承 + state_rebuild telemetry）/投影
            # 渲染/锚点消费面退出（E-D3 latent 留痕）+ 投影替代
            # （DUAL_SOURCE_GUARD）。语义原样，产物经 CognitiveStateOutcome 回接。
            _cs = run_cognitive_state(
                settings,
                sess=sess,
                mode_candidate=_cog_mode_candidate,
                promoted=_cog_promoted,
                lat_mode=_lat_mode,
                anchor_sess=anchor_sess,
                record_action=record_action,
            )
            _anchor_mode = _cs.anchor_mode
            _tier_on = _cs.tier_on
            _cog_mode = _cs.mode
            _cog_enforce = _cs.enforce
            _cog_sid = _cs.sid
            _sem_state = _cs.sem_state
            _env = _cs.env
            _projection = _cs.projection
            _anchor = _cs.anchor

            # B4-C3-03: 预算切分迁 stages/budget_application（R2/L2-1 单一总预算门闸
            # + R4 recovery 拉出）；决策入 BuildDecision.budget；self._last_injection_budget 回写。
            _budget_outcome = apply_injection_budget(
                built=built,
                inject_parts=_inject_parts,
                inject_keys=_inject_keys,
                packet_parts=_packet_parts,
                packet_keys=_packet_keys,
                projection=_projection,
                anchor=_anchor,
                sem_state=_sem_state,
                cog_enforce=_cog_enforce,
                tier_on=_tier_on,
                compile_decision_packet=compile_decision_packet,
                recovery_render_parts=_recovery_render_parts,
                injection_budget_chars=int(
                    getattr(
                        settings,
                        "injection_budget_chars",
                        DEFAULT_INJECTION_BUDGET_CHARS,
                    )
                ),
                record_action=record_action,
            )
            _inject_parts = _budget_outcome.inject_parts
            _inject_keys = _budget_outcome.inject_keys
            _packet_parts = _budget_outcome.packet_parts
            _packet_keys = _budget_outcome.packet_keys
            _recovery_render_parts = _budget_outcome.recovery_render_parts
            _projection = _budget_outcome.projection
            _anchor = _budget_outcome.anchor
            _sem_state = _budget_outcome.sem_state
            _last_injection_budget = _budget_outcome.budget_result
            _budget_written = True
            decision.budget = _budget_outcome.budget

            # packet 装配/telemetry → stages/cognitive.py（B4-C4-01 第 3 步）：CR-R1
            # header 先行（空 slots 不抑制 header；header 已含投影 → anchor 位不重复
            # 注入）/CR-R1.1 shadow 同构（产物仅 telemetry 度量，prompt 平铺旧行为）/
            # CR-R1 4.2 生产预算接线（超上界降级仅 HOT）/CR-R1 6.2 packet_compile +
            # tier_degraded telemetry（_CogPacketEvt 显式键型随迁）。产物经
            # CognitivePacketOutcome 回接。
            _cp = run_cognitive_packet(
                settings,
                inject_parts=_inject_parts,
                packet_parts=_packet_parts,
                sem_state=_sem_state,
                anchor=_anchor,
                tier_on=_tier_on,
                enforce=_cog_enforce,
                sid=_cog_sid,
                env=_env,
                mode=_cog_mode,
                promoted=_cog_promoted,
            )
            _agg = _cp.agg
            _agg_anchor = _cp.agg_anchor
            # R4 recovery is rendered as its own program message before the ordinary
            # background appendix.  R6 immediately absorbs both into one user envelope,
            # leaving recovery as the explicit executable exception before exact user truth.
            if _recovery_render_parts and r6_ingress_truth is not None:
                built.append({"role": "user", "content": _recovery_render_parts[0]})
            if _agg.strip():
                _agg_content = wrap_injection(_agg, _agg_anchor)
                built.append({"role": "user", "content": _agg_content})
                # err1210 9.1: 聚合登记（单 entry；strip/defer 消费端经 AGGREGATED 分支）
                # CR-R1.1（审查项5）: seg_sources 携带投影前原始段——defer 恢复
                # 不从 wire 反推（WARM 投影截断会永久丢失原文）。
                injections.append(
                    InjectedEntry(
                        msg_idx=len(built) - 1,
                        slot_kind=SlotKind.AGGREGATED,
                        prefix_sha=content_prefix_sha(_agg_content),
                        message_ref=None,
                        seg_sources=tuple(
                            (str(_k), _c) for _k, _c in _inject_parts
                        ),
                    )
                )
            # 空 slots 且无 header：安静轮零注入（不造空条、不登记）
        except Exception:  # noqa: BLE001 — 聚合失败 fail-open（零注入降级 + WARN）
            logger.warning(
                "build: 尾部注入聚合失败，本轮零注入降级（fail-open）", exc_info=True
            )
            return InjectionCognitiveOutcome(last_injection_budget=_UNSET)
    return InjectionCognitiveOutcome(last_injection_budget=_UNSET if _budget_written is False else _last_injection_budget)
