"""上下文投影与决策包（Cognitive Runtime 5.2，冻结点①分级算法）.

对应: `.codeartsdoer/specs/cognitive_runtime/spec.md` §5.2 + design 2.1.3.2 / 2.2.2.2 / 2.3.2。

设计约束:
- 在既有 T1 单一决策包管线（build.py P1 统一聚合器，f52e8ca）**之上**做 HOT/WARM/COLD
  分级与槽位语义保留，非从零重构四槽、不新建第二条聚合管线（spec 5.2.1-6 / design 2.1.3.2）。
- classify_tier 是确定性规则函数（纯函数，不调 LLM），保证单轮 build 耗时上界可测（spec 4.1-1）。
- 空槽不注入占位段（spec 5.2.1-3）；决策包注入管线保持单一（spec 5.2.3-1）。
- 段标记格式: ``--- [tier:{hot|warm|cold}][slot:xxx] ---``（tier 由本模块打标，
  err1210._AGG_SLOT_RE 同步兼容，见任务 2.3 合并约束——两文件必须同任务提交，
  否则中间态 P1 defer 回存拆解 fail-open 丢段）。

【风险点②·tier 先验假设】（须与单测共同锁定，作为 A/B 校准对照锚点）:
分级规则表是先验假设而非由数据校定。tier 误判影响半径——
- HOT 误判为 WARM/COLD → 漏看关键信息（决策依据缺失 → 任务漂移/重复探测）；
- WARM/COLD 误判为 HOT → token 膨胀（注入过宽 → 认知负担回升）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from llm_loop.cognitive.state import SemanticTaskState

logger = logging.getLogger(__name__)

# interop 首条 HOT（当前必须处理），第 2 条起折叠 WARM（design 2.1.3.2 规则表「首条 inline，其余折叠」）。
_INTEROP_INLINE_FIRST = 1


class ContextTier(StrEnum):
    """上下文分级（design 2.1.3.2）。"""

    HOT = "hot"  # 必须 inline，逐轮可见
    WARM = "warm"  # compact summary + 引用（超阈值折叠）
    COLD = "cold"  # 仅 evidence://v1 引用，按需检索


@dataclass(frozen=True)
class TieredSlot:
    """带 tier 标记的槽位段（design 2.3.2）。"""

    slot_kind: str | None  # SlotKind 名 / "memory" / None=hint（对齐 build._inject_parts）
    content: str
    tier: ContextTier
    evidence_ref: str | None = None  # COLD 项携带 evidence://v1 引用
    compact_repr: str = ""  # CR-R1 4.1: WARM 投影用紧凑摘要（空则首行 120 chars 截断+ref）


@dataclass
class DecisionPacket:
    """唯一决策包（design 2.3.2；每轮 build 创建、build 结束即焚，不入状态存储）。"""

    objective_pointer: str = ""  # HOT 位首行（语义状态投影派生）
    hard_constraints: list[str] = field(default_factory=list)  # HOT 位硬约束块（v0.2）
    current_progress: str = ""  # HOT 位次行（checkpoint next 指针）
    slots: list[TieredSlot] = field(default_factory=list)
    degraded: bool = False  # 超上界降级为仅 HOT 位最小包（观测字段，spec 5.2.3-3）

    def render_header(self) -> str:
        """投影前导（HOT 位首行区）——不带段标记，不参与 err1210 defer 槽位拆解。"""
        lines: list[str] = []
        if self.objective_pointer:
            lines.append(self.objective_pointer)
        if self.current_progress:
            lines.append(self.current_progress)
        for hc in self.hard_constraints:
            lines.append(f"[硬约束] {hc}")
        return "\n".join(lines)

    def render_slots(self) -> str:
        """槽位段（tier 分段标记，err1210._AGG_SLOT_RE 同步兼容）。空槽不注入占位段。

        CR-R1 4.1 真投影规则（不变量⑥⑦）：
        - HOT  → 原文 inline（逐轮可见）
        - WARM → compact_repr（原文零 inline）；空 compact_repr 回退首行 120 chars 截断+ref
        - COLD → 仅 evidence ref（raw=0，不变量⑦）
        """
        segments: list[str] = []
        for s in self.slots:
            if not s.content.strip():
                continue  # spec 5.2.1-3 空槽不占位
            if s.tier is ContextTier.HOT:
                body = s.content  # HOT 原文 inline
            elif s.tier is ContextTier.WARM:
                if s.compact_repr.strip():
                    body = s.compact_repr
                else:
                    first = s.content.split("\n", 1)[0][:120]
                    ref = f"  (+ref: {s.evidence_ref})" if s.evidence_ref else ""
                    body = first + ref
            else:  # COLD
                body = f"(ref: {s.evidence_ref})" if s.evidence_ref else "（内容已折叠，按需检索）"
            segments.append(f"--- [tier:{s.tier.value}][slot:{s.slot_kind or 'hint'}] ---\n{body}")
        return "\n\n".join(segments)

    def render(self) -> str:
        """完整决策包文本 = 投影前导 + tier 分段槽位。"""
        parts = [p for p in (self.render_header(), self.render_slots()) if p]
        return "\n\n".join(parts)


def classify_tier(
    slot_kind: str | None,
    content: str,
    state: SemanticTaskState | None = None,
) -> ContextTier:
    """确定性分级（纯函数，不调 LLM，design 2.1.3.2 规则表）。

    规则表（v1 先验假设，风险点②见模块 docstring）:
    - gate_note            → HOT（门禁知情，A/B 受控变量必须 inline）
    - interop              → HOT（首条当前必须处理；堆积折叠由 compile 阶段降级为 WARM）
    - hotcard / tip        → WARM（compact summary + 引用）
    - memory / hint / 其它  → WARM（辅助信息，保守折叠）
    - evidence://v1 引用内容 → COLD（仅引用，按需检索）
    - objective / checkpoint.next / hard_constraints 由投影派生（compile 阶段），恒 HOT。

    state 参数为 v0.2 预留（objective 引用关系匹配）；v0.1 四槽分级仅看 slot_kind。
    """
    del content, state  # v0.1 分级仅由 slot_kind 决定（确定性规则，不看内容）
    kind = (slot_kind or "hint").strip().lower()
    if kind == "gate_note":
        return ContextTier.HOT
    if kind == "interop":
        return ContextTier.HOT
    if kind in ("hotcard", "tip", "memory", "hint"):
        return ContextTier.WARM
    if kind.startswith("evidence"):
        return ContextTier.COLD
    return ContextTier.WARM


def compile_decision_packet(
    parts: Sequence[tuple[str | None, str]],
    state: SemanticTaskState | None = None,
    *,
    budget_chars: int | None = None,
) -> DecisionPacket:
    """四槽融合 → 唯一决策包（spec 5.2.1-2/3，design 2.2.2.2）。

    - 逐项打 tier（classify_tier）；interop 首条 HOT、第 2 条起折叠 WARM（堆积折叠）。
    - 空槽（content 空白）不注入占位段。
    - state 未初始化/objective 缺省 → 首行降级为 checkpoint 指针或省略（design 2.2.2.2 前置条件）。
    - budget_chars 给定时：WARM 内容总量超上界 → 降级仅保留 HOT 位（degraded=True，spec 5.2.3-3）。
    """
    packet = DecisionPacket()
    if state is not None:
        packet.objective_pointer = f"[当前决策] {state.objective}"
        if state.checkpoint is not None and state.checkpoint.next:
            packet.current_progress = f"[下一步] {state.checkpoint.next}"
        elif state.checkpoint is not None:
            packet.current_progress = f"[下一步] {state.checkpoint.what}"
        else:
            packet.current_progress = "[下一步] （无 checkpoint；见 objective）"
        packet.hard_constraints = list(state.hard_constraints)

    interop_seen = 0
    for slot, content in parts:
        if not str(content).strip():
            continue  # 空槽不占位（spec 5.2.1-3）
        tier = classify_tier(slot, content, state)
        kind = (slot or "hint").strip().lower()
        if kind == "interop":
            interop_seen += 1
            if interop_seen > _INTEROP_INLINE_FIRST:
                tier = ContextTier.WARM  # 堆积折叠：首条 HOT，其余 WARM
        packet.slots.append(TieredSlot(slot_kind=slot, content=str(content), tier=tier))

    if budget_chars is not None:
        # CR-R1 4.1: 预算按投影后长度计（WARM 投影=compact_repr 或首行截断，非原文）
        warm_chars = sum(
            len(s.compact_repr.strip() or s.content.split("\n", 1)[0][:120])
            for s in packet.slots
            if s.tier is ContextTier.WARM
        )
        if warm_chars > budget_chars:
            packet.slots = [s for s in packet.slots if s.tier is ContextTier.HOT]
            packet.degraded = True
            logger.warning(
                "决策包组装超上界（warm=%d > budget=%d），降级仅 HOT 位最小包", warm_chars, budget_chars
            )
    return packet


def semantic_projection(state: SemanticTaskState) -> str:
    """语义状态 → 决策线两行指针投影（决策包 HOT 位首行，design 2.1.3.5）。

    T2 决策线（history._decision_line_frame 的 [当前决策]+[下一步]）升级演进为本投影，
    代码演进不并存（spec 5.1.1-3b）——投影作为前导文本注入（wrap_injection 的 anchor 位），
    落在尾部聚合条内，不插入前缀区（design 1.2.4 前缀缓存约束）。
    """
    return compile_decision_packet([], state).render_header()


__all__ = [
    "ContextTier",
    "TieredSlot",
    "DecisionPacket",
    "classify_tier",
    "compile_decision_packet",
    "semantic_projection",
]
