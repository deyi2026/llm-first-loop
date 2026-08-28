"""单元测试: 认知运行时 compiler + err1210 tier 拆解兼容 + history 投影持久化（tasks 2.7）.

覆盖:
1. classify_tier 规则表逐项断言（风险点②对照锚点，design 2.1.3.2）
2. compile_decision_packet: 空槽不占位 / interop 堆积折叠 / state 投影 / budget 降级
3. render_slots tier 段标记格式（--- [tier:x][slot:y] ---）
4. err1210.parse_aggregated_slots 对 tier 格式拆解可逆性 + 旧格式兼容（任务 2.3 验收红线）
5. history._cog_anchor_mode / _persist_semantic_state（决策线投影派生，tasks 2.4）
"""

import os
from pathlib import Path

from llm_loop.cognitive.compiler import (
    ContextTier,
    compile_decision_packet,
    semantic_projection,
)
from llm_loop.cognitive.state import StateEnvelope
from llm_loop.cognitive.state import (
    CheckpointPointer,
    SemanticStateStore,
    SemanticTaskState,
)
from llm_loop.core.loop.err1210 import parse_aggregated_slots


# ── 风险点②对照锚点: 规则表逐项断言（tier 先验假设锁定）──


def test_classify_tier_rule_table():
    assert classify("gate_note") is ContextTier.HOT
    assert classify("interop") is ContextTier.HOT
    assert classify("hotcard") is ContextTier.WARM
    assert classify("tip") is ContextTier.WARM
    assert classify("memory") is ContextTier.WARM
    assert classify(None) is ContextTier.WARM  # hint
    assert classify("hint") is ContextTier.WARM
    assert classify("evidence_refs") is ContextTier.COLD


def classify(kind: str | None) -> ContextTier:
    from llm_loop.cognitive.compiler import classify_tier

    return classify_tier(kind, "内容", None)


# ── compile_decision_packet ──


def test_compile_empty_slots_no_placeholder():
    packet = compile_decision_packet([("interop", ""), ("tip", "   "), ("gate_note", "G")])
    kinds = [s.slot_kind for s in packet.slots]
    assert kinds == ["gate_note"]  # 空槽不注入占位段（spec 5.2.1-3）


def test_compile_interop_first_hot_rest_warm():
    parts = [("interop", f"待办{i}") for i in range(3)]
    packet = compile_decision_packet(parts)
    interop_tiers = [s.tier for s in packet.slots if s.slot_kind == "interop"]
    assert interop_tiers == [ContextTier.HOT, ContextTier.WARM, ContextTier.WARM]


def test_compile_state_projection():
    state = SemanticTaskState(
        objective="审计任务", checkpoint=CheckpointPointer(what="完成框架", next="分析缓存")
    )
    packet = compile_decision_packet([], state)
    assert packet.objective_pointer == "[当前决策] 审计任务"
    assert packet.current_progress == "[下一步] 分析缓存"
    header = packet.render_header()
    assert "[当前决策] 审计任务" in header
    assert "[下一步] 分析缓存" in header


def test_compile_state_none_omits_header():
    packet = compile_decision_packet([("tip", "T")])
    assert packet.objective_pointer == ""
    assert packet.current_progress == ""
    assert packet.render_header() == ""


def test_compile_budget_degrades_to_hot_only():
    parts = [("gate_note", "G"), ("tip", "T" * 500), ("hotcard", "H" * 500)]
    packet = compile_decision_packet(parts, budget_chars=100)
    assert packet.degraded is True
    assert all(s.tier is ContextTier.HOT for s in packet.slots)  # 仅 HOT 位最小包
    assert [s.slot_kind for s in packet.slots] == ["gate_note"]


def test_render_slots_tier_markers():
    packet = compile_decision_packet([("gate_note", "G1"), ("tip", "T1")])
    rendered = packet.render_slots()
    assert "--- [tier:hot][slot:gate_note] ---\nG1" in rendered
    assert "--- [tier:warm][slot:tip] ---\nT1" in rendered


def test_semantic_projection_two_lines():
    state = SemanticTaskState(objective="目标X", checkpoint=CheckpointPointer(what="W", next="N"))
    text = semantic_projection(state)
    lines = text.split("\n")
    assert lines[0] == "[当前决策] 目标X"
    assert lines[1] == "[下一步] N"


# ── err1210 拆解可逆性（任务 2.3 验收红线: 两文件同提交，拆解单测通过）──


def test_parse_slots_tier_format():
    content = "--- [tier:hot][slot:gate_note] ---\nG\n\n--- [tier:warm][slot:tip] ---\nT"
    segs = parse_aggregated_slots(content)
    assert segs == [("gate_note", "G"), ("tip", "T")]


def test_parse_slots_legacy_format_zero_regression():
    content = "--- [slot:gate_note] ---\nG\n\n--- [slot:interop] ---\nI"
    segs = parse_aggregated_slots(content)
    assert segs == [("gate_note", "G"), ("interop", "I")]


def test_parse_slots_roundtrip_render_then_parse():
    parts = [("gate_note", "G"), ("tip", "T2"), (None, "hint 内容"), ("hotcard", "H")]
    rendered = compile_decision_packet(parts).render_slots()
    segs = parse_aggregated_slots(rendered)
    assert [(k, v) for k, v in segs] == [
        ("gate_note", "G"),
        ("tip", "T2"),
        ("hint", "hint 内容"),
        ("hotcard", "H"),
    ]


def test_parse_slots_interop_fold_roundtrip():
    parts = [("interop", f"待办{i}") for i in range(3)]
    rendered = compile_decision_packet(parts).render_slots()
    segs = parse_aggregated_slots(rendered)
    assert [k for k, _ in segs] == ["interop", "interop", "interop"]  # 槽名可逆（tier 不影响复位）


# ── history 投影持久化（tasks 2.4）──


def test_cog_anchor_mode_default_auto(monkeypatch):
    from llm_loop.core.history import _cog_anchor_mode

    monkeypatch.delenv("COG_RUNTIME_ANCHOR_MODE", raising=False)
    assert _cog_anchor_mode() == "auto"
    monkeypatch.setenv("COG_RUNTIME_ANCHOR_MODE", "anchor")
    assert _cog_anchor_mode() == "anchor"
    monkeypatch.setenv("COG_RUNTIME_ANCHOR_MODE", "bogus")
    assert _cog_anchor_mode() == "auto"  # 非法回退 auto


def test_persist_semantic_state_roundtrip(tmp_path: Path, monkeypatch):
    from llm_loop.core.history import _persist_semantic_state
    from llm_loop.introspection.goal import GoalStore

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    store = GoalStore(tmp_path / "audit")
    g = store.create("压缩后目标任务", session_id="s1")
    store.checkpoint(g.id, what="完成阶段一", next_step="开始阶段二")

    assert _persist_semantic_state("s1") is True
    loaded_env = SemanticStateStore(tmp_path / "audit").load("s1")
    assert isinstance(loaded_env, StateEnvelope)
    assert loaded_env.identity.session_id == "s1"  # CR-R1：identity 头随分片写入
    assert loaded_env.state is not None
    assert loaded_env.state.objective == "压缩后目标任务"
    assert loaded_env.state.checkpoint is not None
    assert loaded_env.state.checkpoint.next == "开始阶段二"


def test_persist_semantic_state_no_goal_keeps_old(tmp_path: Path, monkeypatch):
    from llm_loop.core.history import _persist_semantic_state

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    assert _persist_semantic_state("s-none") is False  # 无 goal → 不覆盖
    assert SemanticStateStore(tmp_path / "audit").load("s-none") is None


def test_decision_line_frame_anchor_mode_unchanged():
    """过渡期 anchor 模式保留旧决策线函数（零回归，spec 4.5-1）。"""
    from llm_loop.core.history import _decision_line_frame

    os.environ.pop("LFL_DATA_DIR", None)
    # 无 GoalStore 环境 → fail-open 空串（不抛异常）
    assert isinstance(_decision_line_frame("no-such"), str)

def test_history_cognitive_reads_are_strict_session(tmp_path: Path, monkeypatch):
    """CR-R1.1a: compact/legacy decision line 都不得回退到他会 active Goal."""
    from llm_loop.core.history import _decision_line_frame, _persist_semantic_state
    from llm_loop.introspection.goal import GoalStore

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    store = GoalStore(tmp_path / "audit")
    ga = store.create("A 已完成目标", session_id="session-A")
    store.update(ga.id, "complete")
    store.create("B foreign active", session_id="session-B")

    # 旧版这里会把 B active 写进 A shard；strict-session 后 A 只看到自己的终态。
    assert _persist_semantic_state("session-A") is False
    assert SemanticStateStore(tmp_path / "audit").load("session-A") is None
    # anchor 过渡路径同样不得把 B 的 active Goal 显示成 A 的决策线。
    assert _decision_line_frame("session-A") == ""
    # 缺失会话身份 fail-closed，不允许退化成 GoalStore 全局读取。
    assert _persist_semantic_state("") is False
    assert _decision_line_frame("") == ""
