"""语义重置基准（Cognitive Runtime 5.3，冻结点② A/B 选型）.

对应: `.codeartsdoer/specs/cognitive_runtime/spec.md` §5.3 / §6.3 + design 2.2.2.4 / 2.3.3。

定位: 离线/影子模式基准编排，**不进主循环热路径**（design 2.1.3）。
三类输入文件口径冻结（spec 6.3-3 测量口径先行冻结，未冻结禁止断言优化收益）:

- ``action_trace``（audit/action_trace.jsonl）: 每行 ``{ts, phase, action_type, detail}``
  （ArchitectureStatusProvider 落盘口径）；
- ``goal_checkpoints``（audit/goals.jsonl）: 每行 Goal.to_dict()（GoalStore 落盘口径，
  checkpoints 含 ``{ts, what, evidence, path, next}``）；
- ``usage_cost``（jsonl）: 每行 ``{round, tokens_in, tokens_out, cache_hit, cache_miss}``
  （event_log request.usage payload 口径，含模型输入输出；工具往返结果作为输入计入 tokens_in）。

风险点声明:
- 风险点①（A 轨 fixture 数量）: 根目录 ``llm-first-loop.swe-*.json`` 实测 26 份 ≥ 20（2026-08-28
  枚举验证）；FixtureRegistry.load 复检，不足需求量时回退缩小样本量并显式标注，禁止未验证启动 A/B。
- 风险点③（双轨成本假设）: estimate_cost 产出 token 上界估算并标注假设；单样本跑通后须复测
  校验（revalidated=False → True），超预算即停止并回写报告。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# token 估算口径与 cognitive/state.py 一致（4 字符≈1 token，中文友好折中）
_TOKEN_CHARS_PER_ESTIMATE = 4

# B 轨 natural compact 判定标记（action_trace 无 session_id 关联——event_log 割裂点 A，
# 故按 event_log 内容中 audit 留痕文本判定，口径可复现）
_COMPACT_MARK_RE = re.compile(r"run\.compact|history\s*\d+→\d+\s*字符")


def _read_jsonl(path: Path) -> list[dict]:
    """读 jsonl 文件（容错跳过空行/损坏行并 WARN——口径可追溯优先于硬失败）."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("benchmark: jsonl 损坏行跳过 %s:%d", path, line_no)
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _estimate_tokens(text: str) -> int:
    return len(text) // _TOKEN_CHARS_PER_ESTIMATE


# ── T3.1 认知效率度量（分子/分母口径冻结，spec 6.3）──


@dataclass(frozen=True)
class EfficiencyMetric:
    """认知效率指标（口径冻结产物）.

    ratio = numerator_tokens / denominator_tokens（分母 0 → 0.0 且 denominator_missing 标注，
    不以 0 冒充分母存在——对齐 spec 5.3.3-1「不以 0 冒充」精神）。
    """

    numerator_tokens: int  # 分子: 恢复寄存器 token（恢复性读取代价）
    denominator_tokens: int  # 分母: 本轮总 token
    ratio: float
    retrieval_action_count: int  # 恢复性读取动作次数（分子构成之一）
    checkpoint_replay_tokens: int  # checkpoint 投影回读 token（分子构成之二）
    numerator_sources: tuple[str, ...]  # 分子提取来源明细（冻结口径可追溯）
    denominator_sources: tuple[str, ...]
    inputs_missing: tuple[str, ...] = ()  # 缺失输入标注（缺失时禁止断言优化收益）
    measurement_frozen: bool = True


class CognitiveOverheadMeter:
    """认知开销度量（CR-R1 5.3 更名；spec 6.3 分子/分母口径冻结）.

    ratio = 恢复寄存器开销 token / 本轮总 token——**越小越好**（认知开销占比；
    原名 EfficiencyMeter 语义反转易误读，更名后语义与读法一致）。

    分子（恢复寄存器开销）提取来源:
    1. action_trace 中恢复性读取动作（memory_search / search_archive / search_records /
       state_rebuild / checkpoint_replay 前缀匹配）的 detail 文本 token 估算
       （manifest/记忆检索等恢复性读取代价）；
    2. goals.jsonl 活跃 goal 的 checkpoint 投影（what+next+evidence）token 估算。

    分母（本轮总 token）提取来源: usage_cost jsonl 的 Σ(tokens_in + tokens_out)。
    口径注明: 含模型输入输出；工具往返结果作为模型输入计入 tokens_in。

    口径冻结声明（MEASUREMENT_FROZEN）: 修改分子/分母提取规则须同步更新本类单测
    （tests/unit/test_cognitive_benchmark.py 口径锁定用例）——spec 5.3.3-2。
    """

    MEASUREMENT_FROZEN = True
    # 分子动作表（冻结）: 恢复性读取——重建"我是谁/做到哪/为什么"的检索代价
    NUMERATOR_ACTION_PREFIXES: tuple[str, ...] = (
        "memory_search",
        "search_archive",
        "search_records",
        "state_rebuild",
        "checkpoint_replay",
    )
    DENOMINATOR_NOTE = "Σ(tokens_in+tokens_out)，含模型输入输出；工具往返结果计入 tokens_in"

    def measure(
        self,
        *,
        action_trace: str | Path,
        goal_checkpoints: str | Path,
        usage_cost: str | Path,
    ) -> EfficiencyMetric:
        trace_rows = _read_jsonl(Path(action_trace))
        goal_rows = _read_jsonl(Path(goal_checkpoints))
        usage_rows = _read_jsonl(Path(usage_cost))

        missing: list[str] = []
        if not trace_rows and not Path(action_trace).exists():
            missing.append("action_trace")
        if not goal_rows and not Path(goal_checkpoints).exists():
            missing.append("goal_checkpoints")
        if not usage_rows and not Path(usage_cost).exists():
            missing.append("usage_cost")

        # 分子①: 恢复性读取动作 detail 估算
        retrieval_tokens = 0
        retrieval_count = 0
        for row in trace_rows:
            action = str(row.get("action_type", ""))
            if action.startswith(self.NUMERATOR_ACTION_PREFIXES):
                retrieval_count += 1
                retrieval_tokens += _estimate_tokens(str(row.get("detail", "")))
        # 分子②: 活跃 goal checkpoint 投影估算（what+next+evidence 三要素回读）
        checkpoint_tokens = 0
        active_goals = 0
        for row in goal_rows:
            if str(row.get("status", "active")) != "active":
                continue
            active_goals += 1
            for cp in row.get("checkpoints", []) or []:
                checkpoint_tokens += _estimate_tokens(
                    str(cp.get("what", "")) + str(cp.get("next", "")) + str(cp.get("evidence", ""))
                )

        numerator = retrieval_tokens + checkpoint_tokens
        # 分母: Σ(tokens_in + tokens_out)
        denominator = sum(
            int(r.get("tokens_in", 0) or 0) + int(r.get("tokens_out", 0) or 0)
            for r in usage_rows
        )
        ratio = (numerator / denominator) if denominator > 0 else 0.0

        return EfficiencyMetric(
            numerator_tokens=numerator,
            denominator_tokens=denominator,
            ratio=round(ratio, 6),
            retrieval_action_count=retrieval_count,
            checkpoint_replay_tokens=checkpoint_tokens,
            numerator_sources=(
                f"action_trace:{retrieval_count} 条恢复性读取 ≈{retrieval_tokens} tok",
                f"goals.jsonl:{active_goals} 活跃 goal checkpoint 投影 ≈{checkpoint_tokens} tok",
            ),
            denominator_sources=(f"usage_cost:{len(usage_rows)} 轮 {self.DENOMINATOR_NOTE}",),
            inputs_missing=tuple(missing),
        )


# ── T3.2 双轨 fixture 加载（冻结点②，design 2.3.3）──


@dataclass(frozen=True)
class FixtureSpec:
    """双轨 fixture 规格（冻结点②）."""

    track: str  # "A"（SWE-bench 子集）| "B"（LFL 长任务回放）
    root: Path  # A 轨: 项目根目录（glob llm-first-loop.swe-*.json）；B 轨: data/event_logs 目录
    limit: int = 20  # 每轨需求样本量（design 冻结: A 20 + B 20）
    min_rounds: int = 40  # B 轨: ≥40 轮
    require_natural_compact: bool = True  # B 轨: 含 ≥1 次 natural compact


@dataclass(frozen=True)
class Sample:
    """A/B 样本（reset/control 1:1 配对，pair_id 成对）."""

    sample_id: str
    track: str
    group: str  # "reset" | "control"
    source_path: str
    oracle: str  # objective fidelity 判定者（口径冻结，design 2.3.3 表）
    pair_id: str


@dataclass(frozen=True)
class RegistryLoadNote:
    """加载备注（风险点①回退缩小样本量的显式标注）."""

    requested: int
    loaded: int
    available: int
    notice: str = ""


class FixtureRegistry:
    """双轨 fixture 加载器（spec 5.3.1-6 / design 冻结点②）."""

    SWE_GLOB = "llm-first-loop.swe-*.json"

    # objective fidelity 判定者（口径冻结）:
    ORACLE_A = "fixture oracle（外部 scorer，test patch 通过率）"
    ORACLE_B = "action_trace 行为指标（重复探测率/完成轮次/objective retention）+ 真实环境结果；语义状态仅作解释性 telemetry"

    def load(self, spec: FixtureSpec) -> list[Sample]:
        if spec.track == "A":
            return self._load_track_a(spec)
        if spec.track == "B":
            return self._load_track_b(spec)
        raise ValueError(f"未知 track: {spec.track!r}（合法值 A/B）")

    def load_with_note(self, spec: FixtureSpec) -> tuple[list[Sample], RegistryLoadNote]:
        """加载 + 风险点①备注（数量不足 → 回退缩小样本量，显式标注不静默）."""
        samples = self.load(spec)
        pair_count = len({s.pair_id for s in samples})
        note = RegistryLoadNote(
            requested=spec.limit,
            loaded=len(samples),
            available=pair_count * 2,
            notice=(
                f"风险点①: 请求 {spec.limit} 实配 {len(samples)}（可用配对源 {pair_count}）"
                if len(samples) < spec.limit
                else ""
            ),
        )
        return samples, note

    def _load_track_a(self, spec: FixtureSpec) -> list[Sample]:
        """A 轨: 根目录 SWE fixture 枚举（风险点①实测复检）."""
        fixtures = sorted(spec.root.glob(self.SWE_GLOB))
        return self._pair_up(spec, [str(p) for p in fixtures])

    def _load_track_b(self, spec: FixtureSpec) -> list[Sample]:
        """B 轨: event_logs 提取 ≥min_rounds 轮 + natural compact 会话."""
        sources: list[str] = []
        for path in sorted(spec.root.glob("*.jsonl")):
            rows = _read_jsonl(path)
            rounds = max(
                (int(r.get("payload", {}).get("round", 0) or 0)
                 for r in rows if r.get("type") == "request.usage"),
                default=0,
            )
            if rounds < spec.min_rounds:
                continue
            if spec.require_natural_compact and not self._has_natural_compact(rows):
                continue
            sources.append(str(path))
        return self._pair_up(spec, sources)

    @staticmethod
    def _has_natural_compact(rows: list[dict]) -> bool:
        """natural compact 判定: event_log 内容含 audit 留痕的 run.compact/压缩标记."""
        for row in rows:
            payload = row.get("payload", {})
            if _COMPACT_MARK_RE.search(str(payload.get("content", ""))):
                return True
        return False

    def _pair_up(self, spec: FixtureSpec, sources: list[str]) -> list[Sample]:
        """同源 1:1 配对: 每个源产 reset+control 两个 Sample（同 pair_id，受控变量一致）.

        design 冻结点②「每轨内部 reset/对照组各 10 对」——limit 语义为样本总数，
        源数上限 = limit // 2；源不足时缩小的同样是样本数（偶数保证 1:1）。
        """
        max_sources = spec.limit // 2
        used = sources[:max_sources]
        oracle = self.ORACLE_A if spec.track == "A" else self.ORACLE_B
        samples: list[Sample] = []
        # CR-R1 5.1（不变量⑨）: 两阶段执行序列——Phase A 全部 control 先跑完冻结
        # baseline → Phase B 全部 reset；同一 pair_id 配对不变，仅执行顺序调整。
        for group in ("control", "reset"):
            for i, src in enumerate(used):
                samples.append(
                    Sample(
                        sample_id=f"{spec.track}-{i:03d}-{group}",
                        track=spec.track,
                        group=group,
                        source_path=src,
                        oracle=oracle,
                        pair_id=f"{spec.track}-pair-{i:03d}",
                    )
                )
        return samples


# ── T3.4 前置依赖检查（err1210 P1 观察项，结论暂缓机制）──


@dataclass(frozen=True)
class PreconditionState:
    """err1210 P1 治理观察项证据（spec 5.3.3-3 / design 2.2.2.4 前置条件）.

    None = 证据缺失（视为未满足）；False = 明确未通过；True = 已通过。
    """

    cache_monitor_l2_passed: bool | None = None
    natural_compact_observed: bool | None = None

    def unmet(self) -> list[str]:
        items: list[str] = []
        if self.cache_monitor_l2_passed is not True:
            items.append("err1210 P1 cache_monitor L2 治理观察项未通过/证据缺失（f52e8ca）")
        if self.natural_compact_observed is not True:
            items.append("首个自然 compact 观察项未通过/证据缺失")
        return items


# ── T3.3 A/B 编排（reset 收益 vs 首 miss 成本）──


@dataclass(frozen=True)
class FirstMissCost:
    """首 miss 成本（spec 5.3.1-2 可量化）.

    triggered=False 表示「未触发首 miss」——与 triggered 样本分子组统计，
    不得以 0 冒充成本（spec 5.3.3-1）。
    """

    triggered: bool
    token_delta: int = 0
    latency_delta_ms: float = 0.0


@dataclass(frozen=True)
class SampleOutcome:
    """单样本 A/B 执行观测（runner 协议产物）."""

    sample_id: str
    group: str
    first_miss: FirstMissCost
    efficiency: EfficiencyMetric
    objective_fidelity_passed: bool | None = None  # None=未判定（oracle 未接）


@dataclass(frozen=True)
class CostEstimate:
    """风险点③: 双轨成本上界估算（假设标注；单样本跑通后复测 revalidated→True）."""

    samples_total: int
    token_upper_bound: int
    assumptions: tuple[str, ...]
    revalidated: bool = False


@dataclass
class BenchmarkReport:
    """A/B 基准报告（spec 5.3.1-1 同时报告收益与成本）."""

    track: str
    fixture_root: str
    preconditions: PreconditionState
    conclusion_deferred: bool = False  # 前置依赖未过 → 结论暂缓
    pending_dependencies: list[str] = field(default_factory=list)
    sample_count_reset: int = 0
    sample_count_control: int = 0
    load_note: RegistryLoadNote | None = None
    cost_estimate: CostEstimate | None = None
    dry_run: bool = True
    # 基线先于优化（spec 5.3.1-5）: baseline 键先行生成，comparison 仅在 baseline 之后写入
    baseline: dict = field(default_factory=dict)
    comparison: dict = field(default_factory=dict)
    outcomes: list[SampleOutcome] = field(default_factory=list)
    first_miss_subgroups: dict = field(default_factory=dict)  # {"triggered": [...], "not_triggered": [...]}


class SemanticResetBenchmark:
    """语义重置 A/B 编排（离线/影子模式）.

    - 前置依赖未过 → 报告 conclusion_deferred + pending_dependencies，不给结论（spec 5.3.3-3）；
    - 基线先于优化: run 内先产 baseline（control 组聚合），后产 comparison（spec 5.3.1-5）；
    - 首 miss 分子组: triggered / not_triggered 分组统计，不以 0 冒充（spec 5.3.3-1）；
    - runner 未注入 → dry-run（产出计划/成本估算/配对，不产收益结论）。
    """

    def __init__(
        self,
        *,
        preconditions: PreconditionState | None = None,
        runner: Callable[[Sample], SampleOutcome] | None = None,
        meter: CognitiveOverheadMeter | None = None,
        registry: FixtureRegistry | None = None,
    ) -> None:
        self._preconditions = preconditions or PreconditionState()
        self._runner = runner
        self._meter = meter or CognitiveOverheadMeter()
        self._registry = registry or FixtureRegistry()

    def estimate_cost(self, spec: FixtureSpec) -> CostEstimate:
        """风险点③: token 上界估算（假设显式标注，未复测前 revalidated=False）."""
        samples, note = self._registry.load_with_note(spec)
        n = len(samples)
        # 假设（design 2.3.3 成本须先估并标注假设）:
        #   单样本回放上界 = min_rounds需求 × 平均轮 8k tok（输入+输出经验上界）；
        #   A 轨 SWE 任务按 fixture 输入 ≤60k tok 估。reset/control 双组 ×1。
        per_sample_upper = (
            spec.min_rounds * 8000 if spec.track == "B" else 60000
        )
        total_upper = n * per_sample_upper
        return CostEstimate(
            samples_total=n,
            token_upper_bound=total_upper,
            assumptions=(
                f"单样本上界 {per_sample_upper} tok（{'回放轮数×8k' if spec.track == 'B' else 'SWE fixture 输入 60k'}）",
                "reset/control 双组各执行一次",
                "假设未复测——单样本跑通后须复测校验成本上界（超预算即停止并回写报告）",
            ),
            revalidated=False,
        )

    def run(self, fixture: FixtureSpec, *, track: str) -> BenchmarkReport:
        """A/B 编排入口（spec 5.3.1 / 5.3.3）."""
        if track != fixture.track:
            raise ValueError(f"track 参数 {track!r} 与 fixture.track {fixture.track!r} 不一致")
        samples, note = self._registry.load_with_note(fixture)
        cost = self.estimate_cost(fixture)
        pending = self._preconditions.unmet()
        report = BenchmarkReport(
            track=track,
            fixture_root=str(fixture.root),
            preconditions=self._preconditions,
            conclusion_deferred=bool(pending),
            pending_dependencies=list(pending),
            sample_count_reset=sum(1 for s in samples if s.group == "reset"),
            sample_count_control=sum(1 for s in samples if s.group == "control"),
            load_note=note,
            cost_estimate=cost,
            dry_run=self._runner is None,
        )
        if self._runner is None:
            # dry-run: 只产计划（配对/成本/前置依赖），不产 baseline/comparison 收益结论
            return report
        if pending:
            # CR-R1 5.2（不变量⑩）: 前置依赖未满足 → 硬阻断——planning_report 即终态，
            # runner 零调用（provider_calls=0），不产出 baseline/comparison。
            return report

        outcomes = [self._runner(s) for s in samples]
        report.outcomes = outcomes
        # 基线先于优化（spec 5.3.1-5）: 先固化 control 组基线聚合
        control = [o for o in outcomes if o.group == "control"]
        reset = [o for o in outcomes if o.group == "reset"]
        report.baseline = self._aggregate(control, label="control_baseline")
        # 首 miss 分子组（spec 5.3.3-1）: triggered / not_triggered 分开统计
        report.first_miss_subgroups = {
            "triggered": [o.sample_id for o in reset if o.first_miss.triggered],
            "not_triggered": [o.sample_id for o in reset if not o.first_miss.triggered],
        }
        # comparison 仅在 baseline 之后写入（对照 reset 收益 vs 首 miss 成本）
        report.comparison = {
            "reset_aggregate": self._aggregate(reset, label="reset_group"),
            "first_miss_cost_mean_triggered_only": self._first_miss_mean(
                [o for o in reset if o.first_miss.triggered]
            ),
            "not_triggered_count": len(report.first_miss_subgroups["not_triggered"]),
        }
        return report

    @staticmethod
    def _aggregate(outcomes: list[SampleOutcome], *, label: str) -> dict:
        """组内聚合（可复现口径: 均值 + 样本数）."""
        ratios = [o.efficiency.ratio for o in outcomes]
        return {
            "label": label,
            "n": len(outcomes),
            "efficiency_ratio_mean": (
                round(sum(ratios) / len(ratios), 6) if ratios else None
            ),
            "objective_fidelity_pass_rate": (
                round(
                    sum(1 for o in outcomes if o.objective_fidelity_passed) / len(outcomes), 4
                )
                if outcomes and any(o.objective_fidelity_passed is not None for o in outcomes)
                else None
            ),
        }

    @staticmethod
    def _first_miss_mean(outcomes: list[SampleOutcome]) -> dict | None:
        """首 miss 成本均值（仅 triggered 子组；空组返回 None 不以 0 冒充）."""
        if not outcomes:
            return None
        return {
            "n": len(outcomes),
            "token_delta_mean": round(
                sum(o.first_miss.token_delta for o in outcomes) / len(outcomes), 1
            ),
            "latency_delta_ms_mean": round(
                sum(o.first_miss.latency_delta_ms for o in outcomes) / len(outcomes), 1
            ),
        }


__all__ = [
    "CognitiveOverheadMeter",
    "EfficiencyMetric",
    "FixtureRegistry",
    "FixtureSpec",
    "Sample",
    "RegistryLoadNote",
    "PreconditionState",
    "SemanticResetBenchmark",
    "BenchmarkReport",
    "SampleOutcome",
    "FirstMissCost",
    "CostEstimate",
]