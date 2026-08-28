"""cognitive/benchmark 语义重置基准单测（tasks 3.5）.

覆盖:
- CognitiveEfficiencyMeter 分子/分母口径提取正确性 + 口径冻结锁定（spec 6.3 / 5.3.3-2）
- FixtureRegistry 双轨加载与 reset/control 1:1 配对 + 风险点①回退缩小标注
- SemanticResetBenchmark: 前置依赖阻断（结论暂缓）、基线先于优化、首 miss 分子组（spec 5.3）
- state.ResetResult.cleared 增量字段（A/B 编排 reset 组消费）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.cognitive.benchmark import (
    CostEstimate,
    CognitiveEfficiencyMeter,
    FixtureRegistry,
    FixtureSpec,
    PreconditionState,
    SampleOutcome,
    SemanticResetBenchmark,
    FirstMissCost,
)
from llm_loop.cognitive.state import (
    ConfirmedFact,
    SemanticResetController,
    SemanticTaskState,
)


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


# ── T3.1 CognitiveEfficiencyMeter 口径 ──


class TestEfficiencyMeter:
    def _meter_inputs(self, tmp_path: Path):
        trace = _write_jsonl(
            tmp_path / "action_trace.jsonl",
            [
                {"ts": "t1", "phase": "p", "action_type": "memory_search", "detail": "字" * 40},
                {"ts": "t2", "phase": "p", "action_type": "search_archive", "detail": "档" * 80},
                {"ts": "t3", "phase": "p", "action_type": "run_tool", "detail": "x" * 400},
                {"ts": "t4", "phase": "p", "action_type": "checkpoint_replay", "detail": "回" * 20},
            ],
        )
        goals = _write_jsonl(
            tmp_path / "goals.jsonl",
            [
                {
                    "id": "G1",
                    "objective": "obj",
                    "status": "active",
                    "checkpoints": [{"what": "W" * 20, "next": "N" * 20, "evidence": "E" * 20}],
                },
                {"id": "G2", "objective": "done", "status": "complete", "checkpoints": []},
            ],
        )
        usage = _write_jsonl(
            tmp_path / "usage.jsonl",
            [
                {"round": 1, "tokens_in": 10000, "tokens_out": 500, "cache_hit": 9000, "cache_miss": 1000},
                {"round": 2, "tokens_in": 20000, "tokens_out": 1500, "cache_hit": 19000, "cache_miss": 1000},
            ],
        )
        return trace, goals, usage

    def test_numerator_denominator_extraction(self, tmp_path: Path):
        """分子=恢复性动作 detail + 活跃 goal checkpoint 投影；分母=Σ(in+out)（口径锁定）."""
        trace, goals, usage = self._meter_inputs(tmp_path)
        m = CognitiveEfficiencyMeter().measure(
            action_trace=trace, goal_checkpoints=goals, usage_cost=usage
        )
        # 分子①: 40//4 + 80//4 + 20//4 = 10+20+5 = 35（run_tool 非恢复性不计入）
        # 分子②: (20+20+20)//4 = 15（complete goal 不计入）
        assert m.numerator_tokens == 35 + 15
        assert m.retrieval_action_count == 3
        assert m.checkpoint_replay_tokens == 15
        assert m.denominator_tokens == 32000  # 10500 + 21500
        assert m.ratio == round((35 + 15) / 32000, 6)
        assert m.inputs_missing == ()
        assert m.measurement_frozen is True
        # 口径可追溯: 分子/分母来源明细非空（spec 6.3-1 注明提取来源）
        assert m.numerator_sources and m.denominator_sources

    def test_measurement_spec_frozen(self):
        """口径冻结锁定（spec 5.3.3-2）: 动作表/冻结标记变更即本用例红灯."""
        meter = CognitiveEfficiencyMeter()
        assert meter.MEASUREMENT_FROZEN is True
        assert meter.NUMERATOR_ACTION_PREFIXES == (
            "memory_search",
            "search_archive",
            "search_records",
            "state_rebuild",
            "checkpoint_replay",
        )

    def test_missing_inputs_marked_not_zero_faked(self, tmp_path: Path):
        """输入缺失 → inputs_missing 标注（不以 0 冒充存在，分母 0 → ratio 0.0）."""
        m = CognitiveEfficiencyMeter().measure(
            action_trace=tmp_path / "nope1.jsonl",
            goal_checkpoints=tmp_path / "nope2.jsonl",
            usage_cost=tmp_path / "nope3.jsonl",
        )
        assert m.inputs_missing == ("action_trace", "goal_checkpoints", "usage_cost")
        assert m.numerator_tokens == 0 and m.denominator_tokens == 0
        assert m.ratio == 0.0

    def test_denominator_zero_ratio_zero(self, tmp_path: Path):
        """分母为 0（usage 空文件存在）→ ratio 0.0 不除零."""
        trace, goals, _ = self._meter_inputs(tmp_path)
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        m = CognitiveEfficiencyMeter().measure(
            action_trace=trace, goal_checkpoints=goals, usage_cost=empty
        )
        assert m.denominator_tokens == 0
        assert m.ratio == 0.0
        assert m.inputs_missing == ()


# ── T3.2 FixtureRegistry 双轨 ──


class TestFixtureRegistry:
    def test_track_a_load_and_pairing(self, tmp_path: Path):
        """A 轨: SWE fixture 枚举 + reset/control 1:1 配对（pair_id 成对）."""
        for i in range(6):
            (tmp_path / f"llm-first-loop.swe-{i}.json").write_text("{}", encoding="utf-8")
        spec = FixtureSpec(track="A", root=tmp_path, limit=6)
        samples = FixtureRegistry().load(spec)
        assert len(samples) == 6
        groups = [s.group for s in samples]
        assert groups.count("reset") == 3 and groups.count("control") == 3
        pair_ids = {s.pair_id for s in samples}
        assert len(pair_ids) == 3  # 每对 reset+control 共享 pair_id
        assert samples[0].oracle.startswith("fixture oracle")  # A 轨判定者冻结

    def test_track_a_shortfall_shrinks_with_notice(self, tmp_path: Path):
        """风险点①: 可用源不足 → 回退缩小样本量 + note 显式标注（不静默）."""
        for i in range(4):
            (tmp_path / f"llm-first-loop.swe-{i}.json").write_text("{}", encoding="utf-8")
        spec = FixtureSpec(track="A", root=tmp_path, limit=20)
        samples, note = FixtureRegistry().load_with_note(spec)
        assert len(samples) == 8  # 4 源 × (reset+control)，缩小到实际可用
        assert note.requested == 20 and note.loaded == 8
        assert "风险点①" in note.notice

    def test_track_b_filters_rounds_and_compact(self, tmp_path: Path):
        """B 轨: ≥40 轮 + natural compact 才入选；不满足被排除."""
        long_compact = _write_jsonl(
            tmp_path / "s1.jsonl",
            [
                {"type": "request.usage", "payload": {"round": r, "tokens_in": 100, "tokens_out": 10}}
                for r in range(1, 46)
            ]
            + [
                {"type": "message.appended", "payload": {"content": "audit: run.compact warn history 642827→647593 字符"}},
            ],
        )
        short = _write_jsonl(
            tmp_path / "s2.jsonl",
            [
                {"type": "request.usage", "payload": {"round": r, "tokens_in": 100, "tokens_out": 10}}
                for r in range(1, 10)
            ],
        )
        no_compact = _write_jsonl(
            tmp_path / "s3.jsonl",
            [
                {"type": "request.usage", "payload": {"round": r, "tokens_in": 100, "tokens_out": 10}}
                for r in range(1, 45)
            ],
        )
        spec = FixtureSpec(track="B", root=tmp_path, limit=2)
        samples = FixtureRegistry().load(spec)
        # 仅 long_compact 入选（short 轮数不足、no_compact 无 natural compact）
        selected = {Path(s.source_path).name for s in samples}
        assert selected == {Path(long_compact).name}
        assert Path(short).exists() and Path(no_compact).exists()  # 存在但被排除
        assert selected.isdisjoint({Path(short).name, Path(no_compact).name})

    def test_unknown_track_raises(self, tmp_path: Path):
        spec = FixtureSpec(track="C", root=tmp_path)
        with pytest.raises(ValueError, match="未知 track"):
            FixtureRegistry().load(spec)


# ── T3.3/T3.4 SemanticResetBenchmark 编排 ──


def _mk_track_spec(tmp_path: Path, n: int = 4) -> FixtureSpec:
    for i in range(n):
        (tmp_path / f"llm-first-loop.swe-{i}.json").write_text("{}", encoding="utf-8")
    return FixtureSpec(track="A", root=tmp_path, limit=n)


def _fake_outcome(sample):
    # reset 组偶数配对源触发首 miss（覆盖 triggered/not_triggered 两子组）
    triggered = (
        sample.group == "reset"
        and int(sample.pair_id.rsplit("-", 1)[-1]) % 2 == 0
    )
    return SampleOutcome(
        sample_id=sample.sample_id,
        group=sample.group,
        first_miss=FirstMissCost(
            triggered=triggered, token_delta=1000 if triggered else 0,
            latency_delta_ms=500.0 if triggered else 0.0,
        ),
        efficiency=CognitiveEfficiencyMeter().measure(
            action_trace=_write_jsonl(
                Path(sample.source_path).parent / f"trace-{sample.sample_id}.jsonl",
                [{"action_type": "memory_search", "detail": "字" * 40}],
            ),
            goal_checkpoints=_write_jsonl(
                Path(sample.source_path).parent / f"goal-{sample.sample_id}.jsonl",
                [{"status": "active", "checkpoints": []}],
            ),
            usage_cost=_write_jsonl(
                Path(sample.source_path).parent / f"usage-{sample.sample_id}.jsonl",
                [{"round": 1, "tokens_in": 10000, "tokens_out": 100}],
            ),
        ),
        objective_fidelity_passed=True,
    )


class TestSemanticResetBenchmark:
    def test_precondition_blocks_conclusion(self, tmp_path: Path):
        """前置依赖未过 → 结论暂缓 + 清单（spec 5.3.3-3）；dry-run 不产收益结论."""
        spec = _mk_track_spec(tmp_path)
        bench = SemanticResetBenchmark()  # 缺省 PreconditionState 全 None → 未满足
        report = bench.run(spec, track="A")
        assert report.conclusion_deferred is True
        assert len(report.pending_dependencies) == 2  # L2 + 自然 compact 两观察项
        assert report.dry_run is True
        assert report.baseline == {} and report.comparison == {}

    def test_baseline_before_comparison_with_runner(self, tmp_path: Path):
        """前置全过 + runner → baseline（control 聚合）先于 comparison（spec 5.3.1-5）."""
        spec = _mk_track_spec(tmp_path)
        bench = SemanticResetBenchmark(
            preconditions=PreconditionState(
                cache_monitor_l2_passed=True, natural_compact_observed=True
            ),
            runner=_fake_outcome,
        )
        report = bench.run(spec, track="A")
        assert report.conclusion_deferred is False
        assert report.dry_run is False
        assert report.baseline["label"] == "control_baseline"
        assert report.baseline["n"] == 2
        assert "reset_aggregate" in report.comparison
        # 首 miss 分子组: triggered/not_triggered 分开（spec 5.3.3-1）
        assert set(report.first_miss_subgroups) == {"triggered", "not_triggered"}

    def test_first_miss_mean_triggered_only(self, tmp_path: Path):
        """首 miss 均值仅对 triggered 子组；全未触发 → None（不以 0 冒充）."""
        spec = _mk_track_spec(tmp_path, n=2)

        def never_triggered(sample):
            o = _fake_outcome(sample)
            return SampleOutcome(
                sample_id=o.sample_id,
                group=o.group,
                first_miss=FirstMissCost(triggered=False),
                efficiency=o.efficiency,
                objective_fidelity_passed=o.objective_fidelity_passed,
            )

        bench = SemanticResetBenchmark(
            preconditions=PreconditionState(True, True), runner=never_triggered
        )
        report = bench.run(spec, track="A")
        assert report.first_miss_subgroups["not_triggered"]
        assert report.first_miss_subgroups["triggered"] == []
        assert report.comparison["first_miss_cost_mean_triggered_only"] is None
        assert report.comparison["not_triggered_count"] > 0

    def test_track_mismatch_raises(self, tmp_path: Path):
        spec = _mk_track_spec(tmp_path)
        with pytest.raises(ValueError, match="不一致"):
            SemanticResetBenchmark().run(spec, track="B")

    def test_cost_estimate_assumptions_flagged(self, tmp_path: Path):
        """风险点③: 成本上界估算 + 假设标注 + 未复测标记（design 2.3.3）."""
        spec = _mk_track_spec(tmp_path, n=4)
        cost = SemanticResetBenchmark().estimate_cost(spec)
        assert isinstance(cost, CostEstimate)
        assert cost.samples_total == 4
        assert cost.token_upper_bound == 4 * 60000  # A 轨假设 60k/样本
        assert cost.revalidated is False
        assert any("复测" in a for a in cost.assumptions)


# ── state.ResetResult.cleared 增量（A/B 编排消费）──


class TestResetResultCleared:
    def test_reset_returns_cleared_minimal_durable(self):
        """reset 成功 → cleared 保留最小 Durable + 硬约束/已确认事实不丢（spec 4.2-1）."""
        state = SemanticTaskState(objective="任务目标", hard_constraints=["禁止改动 src 外文件"])
        state.confirmed_facts.append(ConfirmedFact(claim="事实"))
        state.ephemeral.hypotheses.append("假设")
        result = SemanticResetController().reset(state)
        assert result.ok is True
        assert result.cleared is not None
        assert result.cleared.objective == "任务目标"
        assert result.cleared.hard_constraints == ["禁止改动 src 外文件"]
        assert len(result.cleared.confirmed_facts) == 1  # 已确认事实不因 reset 丢失
        assert result.cleared.ephemeral.hypotheses == []  # Ephemeral 清空
