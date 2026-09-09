"""cognitive/benchmark 语义重置基准单测（tasks 3.5）.

覆盖:
- CognitiveOverheadMeter 分子/分母口径提取正确性 + 口径冻结锁定（spec 6.3 / 5.3.3-2）
- FixtureRegistry 双轨加载与 reset/control 1:1 配对 + 风险点①回退缩小标注
- SemanticResetBenchmark: 前置依赖阻断（结论暂缓）、基线先于优化、首 miss 分子组（spec 5.3）
- state.ResetResult.cleared 增量字段（A/B 编排 reset 组消费）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.cognitive.benchmark import (
    CognitiveOverheadMeter,
    CostEstimate,
    FirstMissCost,
    FixtureRegistry,
    FixtureSpec,
    PreconditionState,
    SampleOutcome,
    SemanticResetBenchmark,
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


# ── T3.1 CognitiveOverheadMeter 口径 ──


class TestEfficiencyMeter:
    def _meter_inputs(self, tmp_path: Path):
        trace = _write_jsonl(
            tmp_path / "action_trace.jsonl",
            [
                # CR-R1 6.3: 真实 trace 结构——恢复性读取 = tool_call + detail=工具名
                {"ts": "t1", "phase": "p", "action_type": "tool_call", "detail": "memory_search"},
                {"ts": "t2", "phase": "p", "action_type": "tool_call", "detail": "search_archive"},
                {"ts": "t3", "phase": "p", "action_type": "tool_call", "detail": "read_file"},
                {
                    "ts": "t4",
                    "phase": "p",
                    "action_type": "tool_call",
                    "detail": "checkpoint_replay",
                },
                {"ts": "t5", "phase": "p", "action_type": "memory_search", "detail": "字" * 40},
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
                {
                    "round": 1,
                    "tokens_in": 10000,
                    "tokens_out": 500,
                    "cache_hit": 9000,
                    "cache_miss": 1000,
                },
                {
                    "round": 2,
                    "tokens_in": 20000,
                    "tokens_out": 1500,
                    "cache_hit": 19000,
                    "cache_miss": 1000,
                },
            ],
        )
        return trace, goals, usage

    def test_numerator_denominator_extraction(self, tmp_path: Path):
        """分子=恢复性动作 detail + 活跃 goal checkpoint 投影；分母=Σ(in+out)（口径锁定）."""
        trace, goals, usage = self._meter_inputs(tmp_path)
        m = CognitiveOverheadMeter().measure(
            action_trace=trace, goal_checkpoints=goals, usage_cost=usage
        )
        # 分子①（CR-R1 6.3 修正）: 废除 detail 长度/4 估算 → tokens=0 仅计数
        #   （3 次: memory_search/search_archive/checkpoint_replay；read_file 非
        #   白名单、t5 旧结构行非 tool_call 均不计入——前缀匹配已废除）
        # 分子②: (20+20+20)//4 = 15（complete goal 不计入）
        assert m.numerator_tokens == 0 + 15
        assert m.retrieval_action_count == 3  # 真实结构 trace 上计数非零
        assert m.checkpoint_replay_tokens == 15
        assert m.denominator_tokens == 32000  # 10500 + 21500
        assert m.ratio == round((0 + 15) / 32000, 6)
        assert m.inputs_missing == ()
        assert m.measurement_frozen is True
        # 口径可追溯: 分子/分母来源明细非空（spec 6.3-1 注明提取来源）
        assert m.numerator_sources and m.denominator_sources

    def test_measurement_spec_frozen(self):
        """口径冻结锁定（spec 5.3.3-2）: 动作表/冻结标记变更即本用例红灯."""
        meter = CognitiveOverheadMeter()
        assert meter.MEASUREMENT_FROZEN is True
        assert meter.RECOVERY_TOOLS == meter.NUMERATOR_ACTION_PREFIXES  # 兼容别名同源
        assert meter.NUMERATOR_ACTION_PREFIXES == (
            "memory_search",
            "search_archive",
            "search_records",
            "state_rebuild",
            "checkpoint_replay",
        )

    def test_missing_inputs_marked_not_zero_faked(self, tmp_path: Path):
        """输入缺失 → inputs_missing 标注（不以 0 冒充存在，分母 0 → ratio 0.0）."""
        m = CognitiveOverheadMeter().measure(
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
        m = CognitiveOverheadMeter().measure(
            action_trace=trace, goal_checkpoints=goals, usage_cost=empty
        )
        assert m.denominator_tokens == 0
        assert m.ratio == 0.0
        assert m.inputs_missing == ()

    def test_recovery_rate_scales_token_unknown(self, tmp_path: Path):
        """CR-R1.1（审查项8）: 拆分双指标——rate 随次数变化，token 未计量标 unknown.

        审查复现场景：多次恢复性调用 vs 0 次——旧 ratio 同为 0.0（numerator
        恒 0），不可作为 A/B 主指标；rate（次数口径）与 token overhead（计量
        口径）分离，未计量显式标 unknown 不以 0 冒充。
        """
        trace, goals, usage = self._meter_inputs(tmp_path)
        m = CognitiveOverheadMeter().measure(
            action_trace=trace, goal_checkpoints=goals, usage_cost=usage
        )
        # fixture: 3 次白名单恢复动作 / 2 决策轮（usage 行数）→ rate=1.5
        assert m.retrieval_action_count == 3
        assert m.recovery_action_rate == 1.5
        assert m.token_overhead_known is False  # retrieval_tokens 恒 0 → unknown
        # 0 次恢复（非白名单 trace）→ rate 0.0，token 仍 unknown（非 0 冒充）
        trace0 = _write_jsonl(
            tmp_path / "trace0.jsonl",
            [{"action_type": "tool_call", "detail": "read_file"}],
        )
        m0 = CognitiveOverheadMeter().measure(
            action_trace=trace0, goal_checkpoints=goals, usage_cost=usage
        )
        assert m0.retrieval_action_count == 0
        assert m0.recovery_action_rate == 0.0
        assert m0.token_overhead_known is False


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
                {
                    "type": "request.usage",
                    "payload": {"round": r, "tokens_in": 100, "tokens_out": 10},
                }
                for r in range(1, 46)
            ]
            + [
                {
                    "type": "message.appended",
                    "payload": {"content": "audit: run.compact warn history 642827→647593 字符"},
                },
            ],
        )
        short = _write_jsonl(
            tmp_path / "s2.jsonl",
            [
                {
                    "type": "request.usage",
                    "payload": {"round": r, "tokens_in": 100, "tokens_out": 10},
                }
                for r in range(1, 10)
            ],
        )
        no_compact = _write_jsonl(
            tmp_path / "s3.jsonl",
            [
                {
                    "type": "request.usage",
                    "payload": {"round": r, "tokens_in": 100, "tokens_out": 10},
                }
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
    triggered = sample.group == "reset" and int(sample.pair_id.rsplit("-", 1)[-1]) % 2 == 0
    return SampleOutcome(
        sample_id=sample.sample_id,
        group=sample.group,
        first_miss=FirstMissCost(
            triggered=triggered,
            token_delta=1000 if triggered else 0,
            latency_delta_ms=500.0 if triggered else 0.0,
        ),
        efficiency=CognitiveOverheadMeter().measure(
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


# ── CR-R1 5.4：两阶段执行序列 + 前置硬阻断（不变量⑨⑩）──


class TestCrR1TwoPhaseAndHardBlock:
    def test_pair_up_two_phase_control_first(self, tmp_path: Path):
        """不变量⑨: 执行序列 control 全部先于 reset（Phase A 冻结 baseline 再 Phase B）."""
        for i in range(6):
            (tmp_path / f"llm-first-loop.swe-{i}.json").write_text("{}", encoding="utf-8")
        spec = FixtureSpec(track="A", root=tmp_path, limit=6)
        samples = FixtureRegistry().load(spec)
        groups = [s.group for s in samples]
        assert len(samples) == 6
        # control 全部在前半、reset 全部在后半（两阶段序列）
        assert groups == ["control"] * 3 + ["reset"] * 3
        # 配对关系保持（每对共享 pair_id）
        assert len({s.pair_id for s in samples}) == 3

    def test_hard_block_unmet_zero_runner_calls(self, tmp_path: Path):
        """不变量⑩: 前置依赖未满足 → run() 硬阻断，runner 零调用（provider_calls=0）."""
        for i in range(4):
            (tmp_path / f"llm-first-loop.swe-{i}.json").write_text("{}", encoding="utf-8")
        calls: list = []

        def counting_runner(s):
            calls.append(s)
            raise AssertionError("硬阻断生效时 runner 不应被调用")

        bench = SemanticResetBenchmark(
            preconditions=PreconditionState(),  # 两项 None → unmet 非空
            runner=counting_runner,
        )
        spec = FixtureSpec(track="A", root=tmp_path, limit=4)
        report = bench.run(spec, track="A")
        assert len(calls) == 0  # runner 零调用
        assert report.conclusion_deferred is True
        assert report.pending_dependencies  # 阻断原因可读
        assert report.baseline == {} and report.comparison == {}  # 不产出结论（默认空 dict）


# ── CR-R1 6.4：telemetry 事件流 + to_dict session_id（不变量⑪）──


class TestCrR1Telemetry:
    def test_to_dict_contains_session_id(self):
        """6.1: ActionTraceItem.to_dict 含 session_id（旧 trace 行读侧 .get() 容忍）."""
        from llm_loop.introspection.status import ActionTraceItem

        item = ActionTraceItem(
            ts="t", phase="p", action_type="tool_call", detail="memory_search", session_id="s-123"
        )
        d = item.to_dict()
        assert d["session_id"] == "s-123"

    def test_emit_env_off_no_write(self, tmp_path, monkeypatch):
        """6.2: env COG_RUNTIME_TELEMETRY 未开 → 零写入."""
        from llm_loop.cognitive import telemetry

        monkeypatch.delenv("COG_RUNTIME_TELEMETRY", raising=False)
        wrote = telemetry.emit_cognitive_event("packet_compile", data_dir=tmp_path, session_id="s1")
        assert wrote is False
        assert not (tmp_path / "audit" / "cognitive_telemetry.jsonl").exists()

    def test_emit_event_four_elements_and_fields(self, tmp_path, monkeypatch):
        """6.2: 事件四要素（session/run/round/goal_id）+ 认知维度字段齐全落盘."""
        from llm_loop.cognitive import telemetry

        monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
        wrote = telemetry.emit_cognitive_event(
            "state_rebuild",
            data_dir=tmp_path,
            session_id="s-abc",
            run_id="run-1",
            round_no=7,
            goal_id="G-9",
            cognitive_epoch=2,
            state_revision=11,
            hot_tokens=40,
            warm_tokens=10,
            cold_ref_count=3,
            packet_tokens=64,
            mode="enforce",
        )
        assert wrote is True
        rows = [
            __import__("json").loads(ln)
            for ln in (tmp_path / "audit" / "cognitive_telemetry.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == 1
        r = rows[0]
        assert r["event"] == "state_rebuild"
        # 四要素
        assert r["session_id"] == "s-abc" and r["run_id"] == "run-1"
        assert r["round"] == 7 and r["goal_id"] == "G-9"
        # 认知维度
        assert r["cognitive_epoch"] == 2 and r["state_revision"] == 11
        assert (r["hot_tokens"], r["warm_tokens"], r["cold_ref_count"]) == (40, 10, 3)
        assert r["packet_tokens"] == 64 and r["mode"] == "enforce"

    def test_emit_fail_open_on_bad_path(self, monkeypatch):
        """6.2: 写失败 fail-open（返回 False，不抛出）."""
        from llm_loop.cognitive import telemetry

        monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
        wrote = telemetry.emit_cognitive_event(
            "tier_degraded", data_dir="/dev/null/不可写路径", session_id="s1"
        )
        assert wrote is False
