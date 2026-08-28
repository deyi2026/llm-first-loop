"""CR-R1 任务组 4 单测（tasks 4.3）：tier 真投影 + budget 生产接线。

不变量映射：
- ⑥ WARM 无原文 inline（compact_repr 优先；空则首行 120 chars 截断+ref）
- ⑦ COLD raw=0（仅 evidence ref）
- ⑧ 生产超预算 degraded（WARM 投影超上界 → 仅 HOT 最小包 + degraded=True）
- 4.2b err1210 parse_aggregated_slots 对 header+slots 聚合条兼容（header 行跳过不破坏拆解）
"""
from llm_loop.cognitive.compiler import (
    ContextTier,
    DecisionPacket,
    TieredSlot,
    compile_decision_packet,
)
from llm_loop.core.loop.err1210 import parse_aggregated_slots

LONG_RAW = "A" * 400 + "\n" + "B" * 400  # 800 chars 两行原文


def _render_slot(tier: ContextTier, *, compact: str = "", ref: str | None = None) -> str:
    pkt = DecisionPacket(
        slots=[TieredSlot(slot_kind="tip", content=LONG_RAW, tier=tier,
                          evidence_ref=ref, compact_repr=compact)]
    )
    return pkt.render_slots()


# ── 不变量⑥：WARM 原文零 inline ──────────────────────────────────────


def test_warm_compact_repr_wins():
    out = _render_slot(ContextTier.WARM, compact="紧凑摘要", ref="evidence://v1/x1")
    assert "紧凑摘要" in out
    assert "A" * 400 not in out  # 原文零 inline
    assert "B" * 400 not in out


def test_warm_fallback_first_line_120_plus_ref():
    out = _render_slot(ContextTier.WARM, ref="evidence://v1/x2")
    assert "A" * 120 in out  # 首行截断 120 chars
    assert "A" * 121 not in out  # 不超过 120
    assert "B" * 400 not in out  # 第二行不出现
    assert "(+ref: evidence://v1/x2)" in out


def test_hot_full_inline():
    out = _render_slot(ContextTier.HOT)
    assert "A" * 400 in out and "B" * 400 in out  # HOT 原文完整 inline


# ── 不变量⑦：COLD raw=0 ─────────────────────────────────────────────


def test_cold_ref_only_raw_zero():
    out = _render_slot(ContextTier.COLD, ref="evidence://v1/x3")
    assert "(ref: evidence://v1/x3)" in out
    assert "A" * 400 not in out and "B" * 400 not in out  # raw=0


# ── 不变量⑧：超预算 degraded（投影长度口径）──────────────────────────


def test_budget_degraded_by_projection_length():
    # WARM 原文 800 chars 但投影首行截断 120 → 预算 150 时（120 < 150）不降级
    pkt = compile_decision_packet([("tip", LONG_RAW)], budget_chars=150)
    assert pkt.degraded is False
    assert any(s.tier is ContextTier.WARM for s in pkt.slots)
    # 预算 50 < 投影 120 → 降级仅 HOT
    pkt2 = compile_decision_packet([("tip", LONG_RAW), ("gate_note", "门禁通知")], budget_chars=50)
    assert pkt2.degraded is True
    assert pkt2.slots and all(s.tier is ContextTier.HOT for s in pkt2.slots)
    assert all(s.slot_kind == "gate_note" for s in pkt2.slots)  # 仅 HOT（gate_note）保留


def test_budget_production_wiring_default():
    # 生产默认预算 2000 在 config；compile 直调等价性冒烟（接线断言在受影响面 golden）
    pkt = compile_decision_packet([("tip", "x" * 999)], budget_chars=2000)
    assert pkt.degraded is False


# ── 4.2b：err1210 parse 对 header+slots 聚合条兼容 ────────────────────


def test_parse_agg_header_compat():
    content = (
        "[当前决策] 测试目标X\n[下一步] 执行B\n\n"
        "--- [tier:hot][slot:interop] ---\n协调消息原文\n\n"
        "--- [tier:warm][slot:tip] ---\n经验提示首行截断  (+ref: evidence://v1/abc)\n\n"
        "--- [tier:cold][slot:memory] ---\n(ref: evidence://v1/def)"
    )
    parts = parse_aggregated_slots(content)
    slots = [s for s, _ in parts]
    assert slots == ["interop", "tip", "memory"]  # header 行不破坏拆解（3 段全出）
    segs = dict(parts)
    assert segs["interop"] == "协调消息原文"
    assert segs["memory"] == "(ref: evidence://v1/def)"
