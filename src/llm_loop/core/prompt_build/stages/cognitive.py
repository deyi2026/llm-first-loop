"""Cognitive 认知运行时门控与注入阶段（design §2.1.2 #12 / T5-C 第 4 批）.

authority = RETRIEVAL-ONLY（冻结态下 promote 禁止）：本模块只做认知运行时
的模式门控解析（off/shadow/enforce + 冻结/名单提升）与语义检索产物的
装配接线，不拥有终止/预算/缓存职责（R9-P4-04 职责单一：semantic 类模块
无 cache 职责引用）。

冻结语义（R8.24-E E-D4 / E-2.1）：LFL_COG_ENFORCE_FREEZE（默认 on）下
①allowlist 自动 promote 恒不触发；②显式/现网 enforce 配置降 shadow
（effective mode 恒 ∈ {off, shadow}，E-G4）。恢复 promote 须走
LFL_COG_ENFORCE_FREEZE=off 且绑定 E-2.2 五条件重新审批
（cognitive-refreeze-conditions.md）。

B4-C4-01 第 1 步迁入：门控解析（mode/freeze/promote/compute_candidate/
has_existing_program）+ 冻结/名单 helpers；决策落 BuildDecision.cog_freeze。
后续步骤：state 读取/Read Barrier/投影（第 2 步）、packet 装配/telemetry
（第 3 步）。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

from llm_loop.core.injection_labels import (
    InjectionLayer,
    detect_program_layer,
    ensure_semantic_label,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm_loop.core.prompt_build import BuildDecision


def _cog_freeze_enabled() -> bool:
    """R8.24-E E-2.1: enforce 冻结开关（LFL_COG_ENFORCE_FREEZE，默认 on）.

    off/false/0/空 视为回滚通道（恢复 promote 必须绑定 E-2.2 重新审批）。
    """
    return str(os.environ.get("LFL_COG_ENFORCE_FREEZE", "1")).strip().lower() not in (
        "",
        "0",
        "false",
        "off",
    )


def _cog_allowlist_hit(settings: Any, sess: Any) -> bool:
    """Stage 2 allowlist 求值（review R3 fail-closed 强化版）.

    任何失败（空配置/相对路径/sid 空/文件缺失/OSError/超 64KiB/超 256 条/
    运行用户可写/非 UTF-8/任意有效行非法 session_id）→ False（保持 shadow）。
    每轮 build 重读——热更语义（删行下一轮生效）。

    P0-1 R3: operator-owned 边界运行时验证——运行用户对文件可写即视为
    控制面不可信（self-promote 攻击链闭合点：agent 可写文件+可见路径）。
    绝对路径是必要非充分条件；root 运行时 os.access 恒真，须配合只读
    挂载/容器部署（见 DESIGN 部署约束）。
    P0-2 R3: all-valid-or-no-promotion——任意非注释有效行非法（非单个
    文件名组件/路径穿越/NUL）→ 整份名单 False，不静默跳过坏行。
    P1-3 R3: bounded read（read(65537) 硬界）——stat 后无界 read 的
    TOCTOU 免疫，最多读 65537B；严格 UTF-8 decode。
    """
    try:
        path_s = str(getattr(settings, "cog_enforce_file", "") or "")
        if not path_s:
            return False
        if not os.path.isabs(path_s):  # P0-1: 相对路径=配置无效
            return False
        sid = str(getattr(sess, "session_id", "") or "")
        if not sid:
            return False
        if os.access(path_s, os.W_OK):  # P0-1 R3: 运行用户可写=控制面越界
            return False
        with open(path_s, "rb") as fh:  # P1-3 R3: bounded read 硬界
            raw = fh.read(65537)
        if len(raw) > 65536:
            return False
        text = raw.decode("utf-8")  # 非 UTF-8 → UnicodeDecodeError → False
        from llm_loop.core.session import _validate_session_id

        valid: list[str] = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            _validate_session_id(s)  # P0-2 R3: 非法 raise → 整份名单 False
            valid.append(s)
        if len(valid) > 256:  # P1-3: 256 有效条目硬上限
            return False
        return sid in valid
    except Exception:  # noqa: BLE001 — P0-2: fail-closed，任何异常→shadow
        return False


@dataclass(slots=True)
class CognitiveGateOutcome:
    """门控解析产物（B4-C4-01；决策同步落 BuildDecision.cog_freeze）."""

    mode: str = "shadow"  # effective mode（含 allowlist 提升/冻结降级后）
    promoted: bool = False  # 名单提升触发（冻结态恒 False）
    freeze: bool = True  # LFL_COG_ENFORCE_FREEZE 生效态
    compute_candidate: bool = False  # shadow/enforce × anchor_mode(semantic/auto)
    has_existing_program: bool = False  # history 已有 program-origin 块（R2）


def resolve_cognitive_gate(
    settings: Any,
    *,
    sess: Any,
    built: list[dict[str, Any]],
    inject_parts_present: bool,
    decision: BuildDecision | None = None,
) -> CognitiveGateOutcome:
    """COG_RUNTIME 三态门控解析（tasks 2.2/2.3；冻结/名单提升语义见模块 docstring）.

    - off 硬关前置（名单不可覆盖 P0-2）；fail-closed 全语义在 _cog_allowlist_hit；
    - quiet shadow 同构计算预判（CR-R1.1a）与 R2 持久化 program-origin 存量检测
      均在 compute 条件内（检测逻辑原样迁入，行为逐字节等价）。
    """
    _cog_mode_candidate = (
        str(getattr(settings, "cog_runtime_mode", "shadow")).strip().lower()
    )
    if _cog_mode_candidate not in ("off", "shadow", "enforce"):
        _cog_mode_candidate = "shadow"
    _cog_freeze = _cog_freeze_enabled()
    if _cog_freeze and _cog_mode_candidate == "enforce":
        _cog_mode_candidate = "shadow"  # 现网 enforce 会话降 shadow（E-G4）
    _cog_promoted = False
    if (
        _cog_mode_candidate == "shadow"
        and not _cog_freeze
        and _cog_allowlist_hit(settings, sess)
    ):
        _cog_mode_candidate = "enforce"
        _cog_promoted = True
    _cog_compute_candidate = (
        _cog_mode_candidate in ("shadow", "enforce")
        and str(getattr(settings, "cog_runtime_anchor_mode", "auto"))
        in ("semantic", "auto")
    )
    _has_existing_program = any(
        detect_program_layer(str(_m.get("content") or ""))
        not in (None, InjectionLayer.USER_INSTRUCTION)
        for _m in built
    )
    outcome = CognitiveGateOutcome(
        mode=_cog_mode_candidate,
        promoted=_cog_promoted,
        freeze=_cog_freeze,
        compute_candidate=_cog_compute_candidate,
        has_existing_program=_has_existing_program,
    )
    if decision is not None:
        # COG 冻结决策入 BuildDecision（B4-C4-01；§2.2.1 允许字段增量语义）
        decision.cog_freeze = {
            "mode": outcome.mode,
            "promoted": outcome.promoted,
            "freeze": outcome.freeze,
            "compute_candidate": outcome.compute_candidate,
            "has_existing_program": outcome.has_existing_program,
            "inject_parts_present": bool(inject_parts_present),
        }
    return outcome


# ── B4-C4-01 第 2 步：认知运行时状态装配自持面 ─────────────────────────────
# 惰性容错导入（cognitive 子包独立演进，import 失败 → 回退 anchor 平铺旧行为零
# 回归；与 build.py 的 packet 装配面各自独立 fail-open，同环境同结果）。
try:  # noqa: SIM105
    from llm_loop.cognitive.compiler import compile_decision_packet, semantic_projection
    from llm_loop.cognitive.state import (
        SemanticStateStore,
        StateEnvelope,
        StateIdentity,
        rebuild_state,
    )
    from llm_loop.cognitive.telemetry import emit_cognitive_event
except Exception:  # noqa: BLE001 — fail-open 回退锚点（零回归）
    compile_decision_packet = None  # type: ignore[assignment]
    semantic_projection = None  # type: ignore[assignment]
    emit_cognitive_event = None  # type: ignore[assignment]
    SemanticStateStore = None  # type: ignore[assignment]
    StateEnvelope = None  # type: ignore[assignment]
    StateIdentity = None  # type: ignore[assignment]
    rebuild_state = None  # type: ignore[assignment]


@dataclass(slots=True)
class CognitiveStateOutcome:
    """状态装配产物（load/Read Barrier/投影/锚点消费面退出+投影替代）."""

    anchor_mode: str = "anchor"
    tier_on: bool = False
    mode: str = "shadow"  # effective mode（含 off 强制 anchor/tier off 后）
    enforce: bool = False
    sid: str = ""
    sem_state: Any = None  # SemanticTaskState | None（宁缺勿错）
    env: Any = None  # StateEnvelope | None（telemetry 归因面）
    projection: str = ""
    anchor: str = ""


def run_cognitive_state(
    settings: Any,
    *,
    sess: Any,
    mode_candidate: str,
    promoted: bool,
    lat_mode: str,
    anchor_sess: Any,
    record_action: Any,
) -> CognitiveStateOutcome:
    """认知运行时状态/投影/锚点装配（B4-C4-01 第 2 步；语义原样迁自 build.py）.

    - CR-R1（tasks 2.2）三态：off → anchor+平铺（tier off）；shadow 完整跑
      load/barrier/compile/telemetry 供预演（仅两处进 prompt 门控由 enforce 控）；
    - CR-R1.1（审查项1）会话身份解耦：Cognitive 路径全用 sess.session_id 字符串；
    - CR-R1（tasks 1.2）schema v2 三态解包：仅可信信封且无墓碑才投影；
    - CR-R1（tasks 3.1）+ CR-R1.1（审查项4）Read Barrier：信封/GoalStore 三路一致
      性核验 + rebuild 回存（state_revision 单调继承）+ telemetry(state_rebuild)；
    - R8.24-E E-D3（E-5.1）锚点消费面恒置空（shadow 态 would_inject 留痕）；
      enforce 投影替代锚点（DUAL_SOURCE_GUARD fail-open 剔除并存锚点）；semantic
      严格态语义不可用不回退（可观测零指针）。
    """
    import contextlib
    import os

    from llm_loop.core.loop.focus import build_task_anchor  # 惰性：loop 包边（防环）

    _anchor_mode = str(getattr(settings, "cog_runtime_anchor_mode", "auto"))
    _tier_on = bool(getattr(settings, "cog_runtime_tier_enabled", True))
    _cog_mode = mode_candidate
    _cog_enforce = _cog_mode == "enforce"
    if _cog_mode == "off":
        _anchor_mode = "anchor"
        _tier_on = False
    _sem_state = None
    _env = None  # CR-R1.1: 预初始化——load 失败时 Barrier 仍走 GoalStore 重建
    _projection = ""
    _cog_sid = str(getattr(sess, "session_id", "") or "")
    _state_store_cls = SemanticStateStore
    if _anchor_mode in ("semantic", "auto") and _state_store_cls is not None:
        try:
            _env = _state_store_cls(os.path.join(settings.data_dir, "audit")).load(
                _cog_sid
            )
            # CR-R1（tasks 1.2）：schema v2 三态解包——仅可信信封且无墓碑才投影；
            # STALE_UNTRUSTED/None/墓碑 → 不注入（宁缺勿错，spec 3.2-1）
            _sem_state = (
                _env.state
                if StateEnvelope is not None
                and isinstance(_env, StateEnvelope)
                and _env.tombstone is None
                else None
            )
        except Exception:  # noqa: BLE001 — 状态读取 fail-open → 回退 anchor
            _sem_state = None
        # CR-R1（tasks 3.1）+ CR-R1.1（审查项4）: Read Barrier——信封与 GoalStore
        # 严格会话读的一致性核验，三路统一：
        #   信封在场且 identity 匹配 → 直接用；
        #   信封 mismatch/缺失/STALE_UNTRUSTED → strict 读 GoalStore：能安全确认
        #     goal → rebuild+回存（envelope 缺失不再等 compact 触发——冷启动首轮
        #     即建 header）；
        #   goal 缺失/终态/异常 → 宁缺勿错置 None（header 不注入）。
        # "没有 envelope"本身不是"不可信"——GoalStore 无法安全确定当前 Goal 才是
        # 不可信（审查报告 §4）。墓碑防复活由三态解包（_sem_state=None）+
        # rebuild_state(终态)→None 双层保障。
        # StateIdentity 同守卫：cognitive import 全有全无，三者联合判定在可达
        # 路径上与原（双条件）完全等价（pyright Optional 收窄）
        if (
            StateEnvelope is not None
            and rebuild_state is not None
            and StateIdentity is not None
        ):
            _env_candidate = _env if isinstance(_env, StateEnvelope) else None
            try:
                from llm_loop.introspection.goal import GoalStore

                _goal = GoalStore(
                    os.path.join(settings.data_dir, "audit")
                ).get(prefer_session_id=_cog_sid, strict_session=True)
                if (
                    _env_candidate is not None
                    and _goal
                    and _goal.get("id")
                    and _env_candidate.identity.matches(_goal)
                ):
                    pass  # 一致：信封可信，直接用
                elif _goal and _goal.get("id"):
                    _rb = rebuild_state(_goal)  # 重建（终态→None 防复活）
                    if _rb is None:
                        _sem_state = None  # goal 已终态：投影不可用
                    else:
                        _cps = _goal.get("checkpoints") or [{}]
                        # CR-R1.1（审查项11）: state_revision 单调继承——在场
                        # mismatch → old+1；缺失/STALE 首建 → 1。
                        _prev_rev = (
                            _env_candidate.identity.state_revision
                            if _env_candidate is not None
                            else 0
                        )
                        _env = StateEnvelope(
                            identity=StateIdentity(
                                session_id=_cog_sid,
                                goal_id=str(_goal.get("id", "")),
                                goal_updated_at=str(_goal.get("updated_at", "")),
                                checkpoint_ts=str((_cps[-1] or {}).get("ts", "")),
                                state_revision=_prev_rev + 1,
                            ),
                            state=_rb,
                        )
                        _state_store_cls(
                            os.path.join(settings.data_dir, "audit")
                        ).save(_cog_sid, _env)
                        _sem_state = _rb
                        logger.info(
                            "build: Read Barrier 不一致→重建语义状态并回存 goal=%s",
                            _goal.get("id"),
                        )
                        if emit_cognitive_event is not None:  # CR-R1 6.2
                            emit_cognitive_event(
                                "state_rebuild",
                                data_dir=settings.data_dir,
                                session_id=_cog_sid,
                                goal_id=str(_goal.get("id", "")),
                                mode=_cog_mode,  # Stage 2 P1-4 同套归因
                                configured_mode=str(
                                    getattr(settings, "cog_runtime_mode", "")
                                ),
                                promoted=promoted,
                            )
                else:
                    _sem_state = None  # goal 缺失→宁缺勿错（header=None）
            except Exception:  # noqa: BLE001 — Barrier fail-open：宁缺勿错
                _sem_state = None
                logger.debug(
                    "build: Read Barrier 核验异常，fail-open 降级无投影",
                    exc_info=True,
                )
        _semantic_projection_fn = semantic_projection
        if _sem_state is not None and _semantic_projection_fn is not None:
            _projection = _semantic_projection_fn(_sem_state)
    _anchor = build_task_anchor(anchor_sess)
    # R8.24-E E-D3（E-5.1，E35 compact anchor 退出）: 压缩锚点不再作为模型可见
    # 语义注入——消费面恒置空（anchor 不承载任务身份；build_task_anchor 本体
    # 保留：审计/压缩热卡等 retrieval 用途不动，仅注入消费面退出）；shadow 态
    # would_inject 计数留痕。
    if _anchor:
        with contextlib.suppress(Exception):
            record_action(
                "action.latent_channel",
                "anchor_would_inject" if lat_mode == "shadow" else "anchor_exited",
                f"chars={len(_anchor)};mode={lat_mode}",
            )
        _anchor = ""
    if _projection and _cog_enforce:  # CR-R1.1（审查项6）: shadow 投影仅度量不进 prompt
        if _anchor and bool(getattr(settings, "cog_runtime_dual_source_guard", True)):
            logger.warning(
                "build: 锚点与投影同轮并存，fail-open 剔除锚点（DUAL_SOURCE_GUARD）"
            )
        _anchor = _projection  # 投影替代锚点（演进不并存，spec 5.2.1-7）
    elif _anchor_mode == "semantic" and _cog_enforce:
        _anchor = ""  # semantic 严格态: 语义不可用不回退锚点（可观测零指针）
    return CognitiveStateOutcome(
        anchor_mode=_anchor_mode,
        tier_on=_tier_on,
        mode=_cog_mode,
        enforce=_cog_enforce,
        sid=_cog_sid,
        sem_state=_sem_state,
        env=_env,
        projection=_projection,
        anchor=_anchor,
    )


class _CogPacketEvt(TypedDict):
    """CR-R1.1（审查项10）: packet telemetry 事件显式键型.

    替代裸 dict[str, str|int] 联合——TypedDict 使 **_evt 展开时逐参数
    类型可检（emit_cognitive_event 具名签名对齐），消除 24 处 union 报错。
    """

    data_dir: str
    session_id: str
    round_no: int
    goal_id: str
    state_revision: int
    hot_tokens: int
    warm_tokens: int
    cold_ref_count: int
    packet_tokens: int
    mode: str
    configured_mode: str
    promoted: bool


@dataclass(slots=True)
class CognitivePacketOutcome:
    """packet 装配产物（enforce header 聚合 / shadow 平铺 + anchor 位裁决）."""

    agg: str = ""
    agg_anchor: str = ""


def run_cognitive_packet(
    settings: Any,
    *,
    inject_parts: list[Any],
    packet_parts: list[Any],
    sem_state: Any,
    anchor: str,
    tier_on: bool,
    enforce: bool,
    sid: str,
    env: Any,
    mode: str,
    promoted: bool,
) -> CognitivePacketOutcome:
    """决策包装配 + packet telemetry（B4-C4-01 第 3 步；语义原样迁自 build.py）.

    - CR-R1（tasks 3.2）header 先行：Barrier 通过即含投影前导，空 slots 不抑制
      header；header+slots 合并单条聚合条（header 在前，沿 P1 形态）；header 已含
      投影 → anchor 位不重复注入（tier 关时投影仍占 anchor 位，旧行为保留）；
    - CR-R1.1（审查项6）shadow 同构：产物仅 telemetry 度量，prompt 走平铺旧行为；
    - CR-R1 4.2 生产预算接线：超上界降级仅 HOT（compiler degraded 路径生产可达，
      不变量⑧）；tier 关/不可用 → 平铺路径 anchor 位（旧行为）；
    - CR-R1 6.2 telemetry：packet_compile / tier_degraded（_CogPacketEvt 显式
      键型；归因 CR-R1.1 审查项7：goal_id/state_revision 取 env.identity，round
      取 current_round_no contextvar，run_id 生产无来源留空——诚实归因不编造）。
    """
    _packet = (
        compile_decision_packet(
            packet_parts,  # CR-R1.1 批次D: packet 输入面=真实注入面（含持久化 memory_snapshot 投影）
            sem_state,
            # CR-R1 4.2: 生产预算接线——超上界降级仅 HOT（compiler degraded
            # 路径生产可达，不变量⑧）
            budget_chars=int(getattr(settings, "cog_runtime_packet_budget", 2000)),
        )
        if tier_on and compile_decision_packet is not None
        else None
    )
    if _packet is not None:
        _packet_text = _packet.render()  # header 在前 + tier 槽位（空 slots→header-only）
        if enforce:  # CR-R1.1（审查项6）: shadow 产物仅 telemetry 度量
            _agg = ensure_semantic_label(
                _packet_text, InjectionLayer.STATUS, slot_kind="decision_packet"
            )
            _agg_anchor = anchor if not _packet.render_header() else ""
        else:
            _agg = "\n\n".join(  # shadow: prompt 走平铺旧行为（不进投影）
                f"--- [slot:{s if s else 'hint'}] ---\n{c}" for s, c in inject_parts
            )
            _agg_anchor = anchor
        if emit_cognitive_event is not None:  # CR-R1 6.2: packet_compile/tier_degraded
            _tier_of = lambda _s: str(  # noqa: E731
                getattr(getattr(_s, "tier", None), "value", "")
            )
            _hot_chars = sum(
                len(getattr(_s, "content", "") or "")
                for _s in _packet.slots
                if _tier_of(_s) == "hot"
            )
            _warm_chars = sum(
                len(getattr(_s, "compact_repr", "") or "")
                for _s in _packet.slots
                if _tier_of(_s) == "warm"
            )
            _cold_n = sum(1 for _s in _packet.slots if _tier_of(_s) == "cold")
            _ctx_round = 0
            try:
                from llm_loop.core.run_context import current_round_no

                _ctx_round = int(current_round_no.get() or 0)
            except Exception:  # noqa: BLE001 — contextvar 未设按 0
                _ctx_round = 0
            _evt = _CogPacketEvt(
                data_dir=settings.data_dir,
                session_id=sid,
                round_no=_ctx_round,
                goal_id=str(
                    getattr(getattr(env, "identity", None), "goal_id", "") or ""
                ),
                state_revision=int(
                    getattr(getattr(env, "identity", None), "state_revision", 0) or 0
                ),
                hot_tokens=_hot_chars // 4,
                warm_tokens=_warm_chars // 4,
                cold_ref_count=_cold_n,
                packet_tokens=len(_packet_text) // 4,
                mode=mode,  # Stage 2 P1-4: effective mode（含 allowlist 提升）
                configured_mode=str(getattr(settings, "cog_runtime_mode", "")),
                promoted=promoted,
            )
            emit_cognitive_event("packet_compile", **_evt)
            if getattr(_packet, "degraded", False):
                emit_cognitive_event("tier_degraded", **_evt)
    else:
        _agg = "\n\n".join(
            f"--- [slot:{s if s else 'hint'}] ---\n{c}" for s, c in inject_parts
        )
        _agg_anchor = anchor  # 平铺路径：投影/锚点经 anchor 位（旧行为）
    return CognitivePacketOutcome(agg=_agg, agg_anchor=_agg_anchor)
