"""Cognitive Runtime 集成测试（tasks 4.1/4.2，spec §4 DFX 约束）.

T4.1 跨边界状态可恢复:
- 持久化-重载循环（模拟重启）: Durable 完整恢复 / Ephemeral 丢弃（spec 4.2-1 / 5.1.1-1）
- rebuild_state 从 GoalStore 回填 checkpoint 四要素（spec 5.1.1-4）
- 硬约束跨 reset 保留 + 决策包 HOT 位可见（spec 4.3-1 / 5.1.1-5）
- 模型切换: 投影纯函数稳定（状态不依赖模型）

T4.2 单管线与降级:
- 单决策包注入管线（tier on/off 恒单条聚合 user，spec 4.2-3 / 5.2.3-1）
- 投影生成耗时上界 + 单独测量（spec 4.1-1）
- budget 超上界 → 仅 HOT 位最小包 + degraded 观测标记（spec 5.2.3-3）
- 首 miss 成本量化计入 A/B 报告（spec 4.1-2 / 5.3.3-1）
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from llm_loop.cognitive.benchmark import (
    CognitiveOverheadMeter,
    FirstMissCost,
    PreconditionState,
    SampleOutcome,
    SemanticResetBenchmark,
)
from llm_loop.cognitive.compiler import (
    ContextTier,
    compile_decision_packet,
    semantic_projection,
)
from llm_loop.cognitive.state import (
    CheckpointPointer,
    ConfirmedFact,
    SemanticResetController,
    SemanticStateStore,
    SemanticTaskState,
    rebuild_state,
)
from llm_loop.core.loop.err1210 import SlotKind
from llm_loop.introspection.goal import GoalStore


def _rich_state() -> SemanticTaskState:
    state = SemanticTaskState(
        objective="完成认知运行时 v1 落地",
        checkpoint=CheckpointPointer(what="任务组 4 集成验证", next="跑全量回归"),
        hard_constraints=["禁止修改 src 外文件", "必须保持既有测试全绿"],
    )
    state.confirmed_facts.append(ConfirmedFact(claim="pyright 配置为 basic"))
    state.ephemeral.hypotheses.append("临时假设：聚合器在极端输入下可能有边界情况需要跨轮观察确认")
    return state


# ── T4.1 跨边界状态可恢复 ──


class TestCrossBoundaryRecovery:
    def test_durable_survives_reload_ephemeral_dropped(self, tmp_path: Path):
        """持久化 → 重载（模拟重启）: Durable 完整 / Ephemeral 丢弃（spec 4.2-1）."""
        store = SemanticStateStore(tmp_path / "audit")
        state = _rich_state()
        # CR-R1 T1: save/load 已 envelope 化（save(session_id, envelope)/load(session_id)）
        from llm_loop.cognitive.state import StateEnvelope, StateIdentity

        store.save(
            "itest-sess",
            StateEnvelope(
                identity=StateIdentity(
                    session_id="itest-sess",
                    goal_id="itest-goal",
                    goal_updated_at="2026-08-28T00:00:00",
                    checkpoint_ts="2026-08-28T00:00:00",
                    state_revision=1,
                    source_digest="0" * 12,
                ),
                state=state,
            ),
        )
        # "重启": 新 Store 实例从磁盘加载（CR-R1 T1: load(session_id) 三态返回）
        _env_reloaded = SemanticStateStore(tmp_path / "audit").load("itest-sess")
        assert _env_reloaded is not None
        reloaded = _env_reloaded.state  # 解包 envelope
        assert reloaded is not None
        assert reloaded.objective == state.objective
        assert reloaded.checkpoint is not None
        assert reloaded.checkpoint.next == "跑全量回归"
        assert reloaded.hard_constraints == state.hard_constraints
        assert len(reloaded.confirmed_facts) == 1
        assert reloaded.confirmed_facts[0].claim == "pyright 配置为 basic"
        assert reloaded.ephemeral.hypotheses == []  # Ephemeral 不持久化

    def test_rebuild_state_from_goal_store(self, tmp_path: Path):
        """rebuild_state: GoalStore checkpoint 四要素回填投影（spec 5.1.1-4）."""
        store = GoalStore(tmp_path / "audit")
        g = store.create(objective="修复注入拆解回归", session_id="s1")
        store.checkpoint(g.id, what="定位到段标记正则", evidence="e", path="p", next_step="更新黄金摘要")
        state = rebuild_state(store.get())
        assert state.objective == "修复注入拆解回归"
        assert state.checkpoint is not None
        assert "更新黄金摘要" in state.checkpoint.next
        # 投影呈现最近进展与确切下一步（spec 5.1.1-4a）
        projection = semantic_projection(state)
        assert "[当前决策] 修复注入拆解回归" in projection
        assert "[下一步] 更新黄金摘要" in projection

    def test_hard_constraints_survive_reset_and_visible_in_hot(self):
        """硬约束跨 reset 保留 + 决策包 HOT 位可见（spec 4.3-1 / 5.1.1-5a）."""
        state = _rich_state()
        result = SemanticResetController().reset(state)
        assert result.ok and result.cleared is not None
        assert len(result.cleared.hard_constraints) == 2  # reset 不丢硬约束
        packet = compile_decision_packet([], result.cleared)
        header = packet.render_header()
        assert "[硬约束] 禁止修改 src 外文件" in header
        assert "[硬约束] 必须保持既有测试全绿" in header

    def test_model_switch_projection_stable(self):
        """模型切换: 投影纯函数，状态恢复不依赖模型标签（spec 4.2-1）."""
        state = _rich_state()
        p1, p2 = semantic_projection(state), semantic_projection(state)
        assert p1 == p2  # 确定性（同状态字节一致，模型无关）
        packet = compile_decision_packet([("interop", "协调A")], state)
        assert packet.render_slots() == "--- [tier:hot][slot:interop] ---\n协调A"


# ── T4.2 单管线与降级 ──


def _engine(tmp_path: Path):
    """最小 LoopEngine（复用 test_model_attribution 装配，与黄金指纹测试同源）."""
    os.environ.setdefault("ZHIPU_API_KEY", "k")
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    providers = json.dumps(
        {
            "zhipu": {
                "base_url": "https://api.zhipu.local/v1",
                "api_key_env": "ZHIPU_API_KEY",
                "models": {"glm-5": {"context": 300000, "thinking": True, "cost_tier": "low"}},
                "default_model": "glm-5",
            },
        }
    )
    settings = _settings(
        tmp_path,
        model_providers_raw=providers,
        llm_model="zhipu/glm-5",
        history_max_chars=300_000,
    )
    fake = _FakeLLMClient("zhipu/glm-5")
    pool = _make_pool(settings, fake, cached={"zhipu": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    return engine, sess


def _arm_slots(engine, sess) -> None:
    from llm_loop.core.loop.hotcard import write_hotcard
    from llm_loop.core.message import Message, MessageSource

    engine._interop_tail_messages = [
        Message(role="system", content="跨模块协调信息", source=MessageSource.SYSTEM)
    ]
    engine._tip_tail_messages = [
        Message(role="system", content="经验提示内容", source=MessageSource.SYSTEM)
    ]
    write_hotcard(origin_session="other", anchor="锚", data_dir=engine.settings.data_dir)
    engine._cache_monitor._get_bucket(sess.session_id).gate_note_pending = True


class TestSinglePipelineAndDegradation:
    def test_single_packet_pipeline_tier_on_and_off(self, tmp_path: Path):
        """单决策包管线: tier 开/关恒单条聚合 user + 单 AGGREGATED entry（spec 4.2-3）."""
        from llm_loop.core.loop.focus import _INJECTION_PREFIX

        engine, sess = _engine(tmp_path)
        # CR-R1 T2: 默认 MODE=shadow（packet 不进 prompt），tier 标记断言需 enforce
        object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")
        _arm_slots(engine, sess)
        out = engine._build_llm_messages(sess, [], max_chars=200_000, planned_label="zhipu/glm-5")
        tail_users = [m for m in out if m.get("role") == "user"][-1:]
        assert len(tail_users) == 1, "尾部注入恒单条聚合 user（单管线）"
        assert str(tail_users[0]["content"]).startswith(_INJECTION_PREFIX)
        entries = engine._run_state().last_build_injections
        assert len(entries) == 1 and entries[0].slot_kind == SlotKind.AGGREGATED
        assert "[tier:hot][slot:gate_note]" not in str(tail_users[0]["content"])
        # R8.13/E26: interop live path 恒空 + 手工武装的 _interop_tail_messages 在
        # _inject_interop_messages 装配点被识别为 legacy defer 并退役（interop.py
        # legacy_defer_retired）——外部正文不再自动获得 prompt 权威。断言退役语义
        #（不进包），而非旧的进包行为。
        assert "[slot:interop]" not in str(tail_users[0]["content"])

        # tier 关闭: 原子回退平铺（同单条，旧格式——不叠加第二管线）
        # Settings 为 frozen dataclass，测试内以 __setattr__ 覆盖（不引入新构造路径）
        object.__setattr__(engine.settings, "cog_runtime_tier_enabled", False)
        _arm_slots(engine, sess)  # 重新武装（gate_note/hotcard 为取走语义，首轮已消费）
        engine._run_state().last_build_injections.clear()
        out2 = engine._build_llm_messages(sess, [], max_chars=200_000, planned_label="zhipu/glm-5")
        tail2 = [m for m in out2 if m.get("role") == "user"][-1:]
        assert len(tail2) == 1
        assert "[slot:gate_note]" not in str(tail2[0]["content"])
        # R8.13/E26: interop 退役在 tier 开/关两种模式下均成立（live eligible slot
        # 同样不进包——外部内容须走用户输入侧显式授权）
        assert "[slot:interop]" not in str(tail2[0]["content"])
        assert len(engine._run_state().last_build_injections) == 1

    def test_projection_time_upper_bound(self):
        """投影+组装耗时上界: 大输入确定性规则路径（spec 4.1-1 相对开销可测）."""
        state = _rich_state()
        big_parts = [("tip", f"经验条目{i}-" + "内" * 200) for i in range(200)]
        t0 = time.monotonic()
        packet = compile_decision_packet(big_parts, state)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert len(packet.slots) == 200
        assert elapsed_ms < 100.0, f"确定性分级+组装 {elapsed_ms:.1f}ms 超上界（纯函数无 LLM）"

    def test_budget_degradation_hot_minimal_packet(self):
        """budget 超上界 → 仅 HOT 位最小包 + degraded 观测标记（spec 5.2.3-3）."""
        state = _rich_state()
        parts = [
            ("gate_note", "门禁知情标记"),
            ("tip", "暖" * 500),   # WARM 超预算
            ("interop", "首条协调"),  # HOT
        ]
        packet = compile_decision_packet(parts, state, budget_chars=100)
        assert packet.degraded is True
        tiers = [s.tier for s in packet.slots]
        assert ContextTier.WARM not in tiers, "降级后 WARM 应被剔除"
        assert tiers == [ContextTier.HOT, ContextTier.HOT]
        rendered = packet.render()
        assert "门禁知情标记" in rendered and "首条协调" in rendered
        assert "暖" * 100 not in rendered  # WARM 内容不进最小包

    def test_first_miss_quantified_in_ab_report(self, tmp_path: Path):
        """首 miss 成本量化计入 A/B 报告（spec 4.1-2: 不以忽略方式陈述）."""
        for i in range(2):
            (tmp_path / f"llm-first-loop.swe-{i}.json").write_text("{}", encoding="utf-8")

        def runner(sample):
            triggered = sample.group == "reset"
            return SampleOutcome(
                sample_id=sample.sample_id,
                group=sample.group,
                first_miss=FirstMissCost(
                    triggered=triggered,
                    token_delta=2345 if triggered else 0,
                    latency_delta_ms=890.0 if triggered else 0.0,
                ),
                efficiency=CognitiveOverheadMeter().measure(
                    action_trace=tmp_path / "t.jsonl",
                    goal_checkpoints=tmp_path / "g.jsonl",
                    usage_cost=tmp_path / "u.jsonl",
                ),
                objective_fidelity_passed=True,
            )

        from llm_loop.cognitive.benchmark import FixtureSpec

        bench = SemanticResetBenchmark(
            preconditions=PreconditionState(True, True), runner=runner
        )
        report = bench.run(FixtureSpec(track="A", root=tmp_path, limit=2), track="A")
        fm = report.comparison["first_miss_cost_mean_triggered_only"]
        assert fm is not None and fm["n"] == 1
        assert fm["token_delta_mean"] == 2345.0 and fm["latency_delta_ms_mean"] == 890.0
        # 未触发子组分开呈现（不以 0 冒充，spec 5.3.3-1）
        assert report.first_miss_subgroups["not_triggered"] == []
