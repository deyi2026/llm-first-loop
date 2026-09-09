"""CR-R1 11 不变量整合门（spec §5.3 验收矩阵，GOAL-20260828-c1159d5c）。

组织方式（tasks.md 7.1）：
- ⑥-⑪ 赋值别名 re-export 既有承载测试（保 fixture 语义，勿重复实现）；
- ①③④⑤ 无既有承载（grep 零命中确认），此处补写机械测试。
本文件全绿是 COG_RUNTIME_MODE=enforce 的 CI 前置门（spec 3.2-1）。
"""

from __future__ import annotations

from pathlib import Path

# ── ⑨⑩⑪ 类方法承载（TestCrR1TwoPhaseAndHardBlock/TestCrR1Telemetry），薄封装保 fixture 语义 ──
from tests.unit.test_cognitive_benchmark import (  # noqa: F401
    TestCrR1Telemetry,
    TestCrR1TwoPhaseAndHardBlock,
)
from tests.unit.test_cognitive_compiler import (  # noqa: F401
    test_compile_budget_degrades_to_hot_only as test_invariant_08_budget_live,
)

# ── ⑥-⑪ re-export（承载测试见各文件；断言核心见 spec §5.3）──
from tests.unit.test_cognitive_compiler import (  # noqa: F401
    test_compile_interop_first_hot_rest_warm as test_invariant_06_warm_bounded,
)
from tests.unit.test_cognitive_compiler import (  # noqa: F401
    test_render_slots_tier_markers as test_invariant_07_cold_ref_only,
)


def test_invariant_09_gate_zero_call(tmp_path):
    """⑨ re-export: TestCrR1TwoPhaseAndHardBlock.test_hard_block_unmet_zero_runner_calls."""
    TestCrR1TwoPhaseAndHardBlock().test_hard_block_unmet_zero_runner_calls(tmp_path)


def test_invariant_10_control_first(tmp_path):
    """⑩ re-export: TestCrR1TwoPhaseAndHardBlock.test_pair_up_two_phase_control_first."""
    TestCrR1TwoPhaseAndHardBlock().test_pair_up_two_phase_control_first(tmp_path)


def test_invariant_11_attribution(tmp_path, monkeypatch):
    """⑪ re-export: TestCrR1Telemetry.test_emit_event_four_elements_and_fields."""
    TestCrR1Telemetry().test_emit_event_four_elements_and_fields(tmp_path, monkeypatch)


# ── ① 跨会话隔离（补写：无既有承载）──


def test_invariant_01_cross_session(tmp_path: Path):
    """① B load ≠ A state：分片路径物理隔离（spec §5.3-①）."""
    from llm_loop.cognitive.state import (
        CheckpointPointer,
        SemanticStateStore,
        SemanticTaskState,
        StateEnvelope,
        StateIdentity,
    )

    store = SemanticStateStore(tmp_path / "audit")
    state = SemanticTaskState(
        objective="会话A目标", checkpoint=CheckpointPointer(what="w", next="n")
    )
    store.save(
        "sess-aaaa1111",
        StateEnvelope(
            identity=StateIdentity(
                session_id="sess-aaaa1111",
                goal_id="g1",
                goal_updated_at="2026-08-28T00:00:00",
                checkpoint_ts="2026-08-28T00:00:00",
                state_revision=1,
                source_digest="0" * 12,
            ),
            state=state,
        ),
    )
    got_b = store.load("sess-bbbb2222")
    assert got_b is None, "跨会话读取必须物理隔离（B load ≠ A state）"
    got_a = store.load("sess-aaaa1111")
    assert got_a is not None and got_a.state is not None
    assert got_a.state.objective == "会话A目标"


# ── ③ 终态墓碑（补写：rebuild_state 终态前置检查在生产代码 L336-344）──


def test_invariant_03_tombstone():
    """③ complete/blocked goal 零投影：rebuild_state → None（spec 4.1-3）."""
    from llm_loop.cognitive.state import rebuild_state

    assert rebuild_state(None) is None
    assert (
        rebuild_state({"id": "G", "objective": "done", "status": "complete", "checkpoints": []})
        is None
    )
    assert (
        rebuild_state({"id": "G", "objective": "hold", "status": "blocked", "checkpoints": []})
        is None
    )


# ── ④ 每轮 header（补写：enforce + active goal + 填槽）──


def _prime_goal_and_envelope(engine, sess, objective):
    """预置 active goal + 匹配信封（Read Barrier L881 前置门要求信封在场，一致→用）."""
    import os

    from llm_loop.cognitive.state import (
        SemanticStateStore,
        StateEnvelope,
        StateIdentity,
        rebuild_state,
    )
    from llm_loop.introspection.goal import GoalStore

    audit = os.path.join(engine.settings.data_dir, "audit")
    goal = GoalStore(audit).create(objective, session_id=sess.session_id)
    # CR-R1.1: build cognitive 路径已与 anchor_sess 解耦（统一 sess.session_id），
    # 不再需要"显式设锚"workaround——测试与生产同一身份链路（审查项9）。
    anchor = sess.session_id
    g = goal.to_dict() if hasattr(goal, "to_dict") else goal
    state = rebuild_state(g)
    assert state is not None, "active goal 必可 rebuild"
    SemanticStateStore(audit).save(
        anchor,
        StateEnvelope(
            identity=StateIdentity(
                session_id=anchor,
                goal_id=str(g.get("id", "")),
                goal_updated_at=str(g.get("updated_at", "")),
                checkpoint_ts=str((g.get("checkpoints") or [{}])[-1].get("ts", "")),
            ),
            state=state,
        ),
    )
    return state


def test_invariant_04_every_turn(tmp_path: Path):
    """④ 100% 决策轮 header 在：聚合条含 active goal 的语义投影（spec §5.3-④）."""
    from tests.integration.test_cognitive_integration import _arm_slots, _engine

    engine, sess = _engine(tmp_path)
    _prime_goal_and_envelope(engine, sess, "不变量④目标")
    object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")
    _arm_slots(engine, sess)
    out = engine._build_llm_messages(sess, [], max_chars=200_000, planned_label="zhipu/glm-5")
    tail = [m for m in out if m.get("role") == "user"][-1:]
    assert len(tail) == 1, "尾部注入恒单条聚合 user"
    assert "不变量④目标" in str(tail[0]["content"]), "header（语义投影）必须在场"


# ── ⑤ 安静轮 decision_visible（补写：零注入槽，header 单独成条，build.py:839）──


def test_invariant_05_quiet_round(tmp_path: Path):
    """⑤ 零注入轮 decision_visible：无槽注入时 header 不被抑制（spec §5.3-⑤）."""
    from tests.integration.test_cognitive_integration import _engine

    engine, sess = _engine(tmp_path)
    _prime_goal_and_envelope(engine, sess, "安静轮目标")
    object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")
    # 刻意不 arm 任何槽（零注入安静轮）
    out = engine._build_llm_messages(sess, [], max_chars=200_000, planned_label="zhipu/glm-5")
    tail = [m for m in out if m.get("role") == "user"][-1:]
    assert len(tail) == 1, "安静轮 header 单独成条（decision_visible）"
    assert "安静轮目标" in str(tail[0]["content"]), "零注入轮 header 不得被空 slots 抑制"


# ── CR-R1.1（审查项9）: 聚合门映射修正——⑥⑦⑧ 补真实断言 + engine.run 生产路径 ──


def test_invariant_06b_warm_wire_no_raw_inline():
    """⑥ 补（审查: 旧映射 test_compile_interop_first_hot_rest_warm 只验 tier 标签）.

    WARM wire 段不含 raw 全文（inline 有界）——审查实测 314 chars tip 投影后
    wire 仅 120 chars：Projection 是 view，不是 Source of Truth。
    """
    from llm_loop.cognitive.compiler import compile_decision_packet

    raw = "RAW-" + "X" * 310  # 314 chars 单行
    packet = compile_decision_packet([("tip", raw)])
    wire = packet.render_slots()
    assert wire, "WARM 槽位应有渲染段"
    assert raw not in wire, "raw 全文不得 inline（WARM 投影有界）"
    assert "X" * 130 not in wire, "超 120 chars 的连续原文不得整段出现"


def test_invariant_07b_cold_ref_only():
    """⑦ 补（审查: 旧映射 test_render_slots_tier_markers 未测 COLD）.

    COLD 槽位 render 仅 evidence ref，raw content 零 inline（不变量⑦）。
    """
    from llm_loop.cognitive.compiler import (
        ContextTier,
        DecisionPacket,
        TieredSlot,
        compile_decision_packet,
    )

    raw = "RAWDATA-" + "Z" * 200
    # 走 classify_tier 真实路径: evidence* slot_kind → COLD
    ref = "evidence://v1/abc123"
    packet = compile_decision_packet([(ref, raw)])
    cold = [s for s in packet.slots if s.tier is ContextTier.COLD]
    assert cold, "evidence* slot_kind 应分级为 COLD"
    assert cold[0].evidence_ref == ref, "production compiler 必须自动物化 stable EvidenceRef"
    wire = packet.render_slots()
    assert f"(ref: {ref})" in wire, "production COLD 必须是可恢复的 ref-only，而非匿名折叠提示"
    assert raw not in wire, "COLD 段不得 inline raw content（不变量⑦）"
    # 显式 evidence_ref 的 renderer 路径仍保持兼容。
    pkt2 = DecisionPacket(
        slots=[
            TieredSlot(
                slot_kind="evidence://v1/xyz",
                content=raw,
                tier=ContextTier.COLD,
                evidence_ref="evidence://v1/xyz",
            )
        ]
    )
    wire2 = pkt2.render_slots()
    assert "(ref: evidence://v1/xyz)" in wire2, "COLD 段应为 ref 引用位"
    assert raw not in wire2


def test_invariant_08b_budget_live_build_path(tmp_path, monkeypatch):
    """⑧ 补（审查: 旧映射直接调 compiler，非真 build 路径）.

    生产 build 路径 budget live：超预算 WARM → 降级仅 HOT（prompt 无
    warm 槽段）+ tier_degraded 事件可观测（packet_budget 真接线）。
    """
    import json as _json

    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    from tests.integration.test_cognitive_integration import _engine
    from tests.unit.test_injection_fingerprint import _arm_all_slots

    engine, sess = _engine(tmp_path)
    _prime_goal_and_envelope(engine, sess, "预算路径目标")
    object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")
    object.__setattr__(engine.settings, "cog_runtime_packet_budget", 10)  # 极小预算必超
    _arm_all_slots(engine, sess, tip_extra=5)  # 武装大 WARM 群（tip/hotcard/memory）
    out = engine._build_llm_messages(sess, [], max_chars=200_000, planned_label="zhipu/glm-5")
    joined = "\n".join(str(m.get("content") or "") for m in out)
    assert "[tier:warm]" not in joined, "超预算 WARM 应降级剔除（degraded 仅 HOT）"
    tpath = Path(engine.settings.data_dir) / "audit" / "cognitive_telemetry.jsonl"
    assert tpath.exists(), "telemetry 应开启"
    rows = [_json.loads(ln) for ln in tpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert any(r.get("event") == "tier_degraded" for r in rows), "budget 降级事件可观测"


def test_engine_run_production_path_no_anchor_hack(tmp_path, monkeypatch):
    """审查红线: 完整 engine.run 生产路径——禁止测试手工改 anchor_sess 类型.

    批次 A 后 cognitive 全链用 sess.session_id（anchor_sess 双重身份解除）；
    run 全程 anchor_sess 由生产赋值（engine.py L452 Session 对象），测试
    不碰它；telemetry packet_compile.goal_id 归因在生产 run 路径可观测。
    """
    import json as _json

    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    from llm_loop.core.session import Session
    from tests.integration.test_cognitive_integration import _engine

    engine, sess = _engine(tmp_path)
    _prime_goal_and_envelope(engine, sess, "run生产路径目标")
    object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")
    engine.run(sess.session_id, "继续任务")  # FakeLLMClient 真跑完整循环
    # 本分支（fix 线）: anchor_sess 为 build 生产参数直传 Session（build.py anchor_sess=sess），
    # 无 engine._focus 挂载点——"生产赋值、测试不改类型"红线由构造保证；sess 本体即生产对象。
    assert isinstance(sess, Session)
    # 生产 run 路径 cognitive 归因可观测（批次 A/D 接线全通）
    tpath = Path(engine.settings.data_dir) / "audit" / "cognitive_telemetry.jsonl"
    assert tpath.exists()
    rows = [_json.loads(ln) for ln in tpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
    pcs = [r for r in rows if r.get("event") == "packet_compile"]
    assert pcs, "run 生产路径应产生 packet_compile 事件"
    assert pcs[0].get("goal_id"), "goal_id 归因非空（_env.identity 来源）"
