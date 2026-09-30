"""AI 自我评估聚合器与触发检测（design.md §6.2 / FR-AUTO-CLOSE-EVAL）.

- SelfEvaluator: 从既有数据源（action_trace / tool_history / exception_log / declaration_check）
  聚合核心五维指标（成功率/工具效率/诚实性/停滞率/异常率）+ honesty 辅助口径指标
  （claim_bearing_rate，测量质量/support 披露，非第六维能力评价），每条指标可溯源；
  纯聚合（无 LLM 往返）
- 评估时机由调用方/AI 按当前任务显式决定；本模块不提供周期/里程碑自动触发器
- SelfEvalReport: 评估结果（EVAL-04 落盘 self_eval_log.jsonl，可经 search_records 检索）
- 对比判定（EVAL-07）: 由 AI 先后两次 self_evaluate 自行比对指标 delta（来源可溯），程序不提供 compare

红线: 评估数据必须如实（来源可溯，禁止伪造）；样本不足/来源不可用如实标注（spec.md 10.2.3-1）；
评估不阻塞主循环（O(span) 轻量聚合，落盘 fail-open）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from llm_loop.feedback.validator import VALIDATOR_VERSION as _CURRENT_VALIDATOR_VERSION
from llm_loop.timekeeping import system_local_now

# 指标契约（EVAL-02 + EVO-20260930 口径拆分）: 5 核心能力指标 + honesty 辅助口径指标。
# claim_bearing_rate 是 honesty 的 measurement-quality/support 披露（空声明自动通过的规模），
# 不升格为第六维能力评价——后续 evaluable_rate/cohort_coverage 等测量质量信息归 AUX，
# 不再膨胀核心维。
CORE_METRIC_NAMES = (
    "success_rate",
    "tool_efficiency",
    "honesty_rate",
    "stagnation_rate",
    "exception_rate",
)
AUX_METRIC_NAMES = (
    "claim_bearing_rate",  # EVO-20260930: 口径拆分辅助指标（空声明自动通过的规模单独披露）
)
# 兼容聚合名（核心在前、辅助在后）
METRIC_NAMES = CORE_METRIC_NAMES + AUX_METRIC_NAMES

# 评估器版本（EVO-20260930 cohort 分层）: 口径/聚合语义变更时 bump，
# 使 self_eval_log 可按代次切分，不与历史口径混算。
# 2026.09.30.1: 消费侧 cohort 隔离——honesty/claim_bearing/diagnostics 仅聚合
# validator_version == 当前期代的 declaration 行（写侧打版本 + 读侧隔离缺一不可）。
EVALUATOR_VERSION = "2026.09.30.1"


def _now() -> str:
    return system_local_now().isoformat()


@dataclass
class EvalMetric:
    """单维度评估指标（EVAL-02，来源可溯）."""

    name: str  # 核心: success_rate/tool_efficiency/honesty_rate/stagnation_rate/exception_rate；辅助: claim_bearing_rate
    value: float | None  # 0.0~1.0；None=数据不足/不可用（如实标注）
    sample_size: int  # 样本数（< SELF_EVAL_MIN_SAMPLES → value=None + "样本不足"）
    source: str  # 来源（action_trace/tool_history/exception_log/declaration_check）
    note: str = ""  # 如实说明（样本不足/来源不可用原因）


@dataclass
class SelfEvalReport:
    """自我评估结果（EVAL-04 落盘结构）."""

    eval_id: str  # SE-YYYYMMDD-NNN
    ts: str
    session_id: str
    trigger: Literal["periodic", "milestone", "anomaly", "manual"]
    metrics: list[EvalMetric]  # 核心五维 + 辅助口径指标（如实，可溯源；见 CORE/AUX_METRIC_NAMES）
    summary: str  # 聚合摘要（程序按指标如实生成的客观描述，非 LLM 结论）
    note: str = ""  # 整体说明（如"声明-回执数据不足，诚实性指标样本不足"）
    # EVO-20260903-06e5a2fd: 只持久化轻量诊断引用/摘要，不复制大 receipts；
    # search_records 精确 eval_id 查询时才暴露，绝不自动进入 prompt。
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # EVO-20260930 cohort 分层: 评估器版本随报告落盘，self_eval_log 按代次切分
    evaluator_version: str = EVALUATOR_VERSION

    def to_dict(self) -> dict:
        payload = {
            "eval_id": self.eval_id,
            "ts": self.ts,
            "session_id": self.session_id,
            "trigger": self.trigger,
            "evaluator_version": self.evaluator_version,
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "sample_size": m.sample_size,
                    "source": m.source,
                    "note": m.note,
                }
                for m in self.metrics
            ],
            "summary": self.summary,
            "note": self.note,
        }
        if self.diagnostics:
            payload["diagnostics"] = self.diagnostics
        return payload


class SelfEvaluator:
    """自我评估聚合器（EVAL-01/02）: 从既有数据源聚合指标，来源可溯."""

    def __init__(
        self,
        *,
        status_provider: Any | None = None,  # ArchitectureStatusProvider
        audit_dir: str | Path,
        min_samples: int = 5,  # SELF_EVAL_MIN_SAMPLES
        span: int = 50,  # SELF_EVAL_SPAN 聚合窗口
        window_hours: float = 24.0,  # EVO-20260816-f1f73a0d: 采样时间窗（小时），防历史污染
        expected_validator_version: str | None = None,  # EVO-20260930: cohort 隔离基准代次
    ) -> None:
        self._status = status_provider
        self._audit_dir = Path(audit_dir)
        self._min_samples = min_samples
        self._span = span
        self._window_hours = window_hours
        # 缺省取 validator 当前常量（factory/测试可注入固定值；None → 与写侧代次一致）
        self._expected_validator_version = expected_validator_version or _CURRENT_VALIDATOR_VERSION

    # ── 指标聚合（核心五维 + 辅助口径）──
    def evaluate(
        self,
        session_id: str = "",
        trigger: Literal["periodic", "milestone", "anomaly", "manual"] = "manual",
    ) -> SelfEvalReport:
        """聚合核心五维指标 + honesty 辅助口径指标（来源可溯；数据不足如实标注）."""
        action_trace = self._time_filter(self._read_action_trace())
        tool_history = self._time_filter(self._read_tool_history())
        exceptions = self._time_filter(self._read_exceptions())
        llm_rounds = self._llm_rounds()
        # EVO-20260930.1 消费侧 cohort 隔离: 时间窗→span 截断→按 validator_version 分代，
        # honesty/claim_bearing/diagnostics 仅聚合当前代次行；排除规模在 diagnostics 可见。
        declaration_window = self._time_filter(self._read_declaration_checks())[-self._span :]
        current_checks, source_versions = self._split_validator_cohort(declaration_window)
        cohort_window_rows = len(declaration_window)
        cohort_current_rows = len(current_checks)

        metrics = [
            self._metric_success_rate(action_trace),
            self._metric_tool_efficiency(tool_history),
            self._metric_honesty_rate(
                current_checks,
                window_rows=cohort_window_rows,
                current_rows=cohort_current_rows,
            ),
            self._metric_stagnation_rate(action_trace),
            self._metric_exception_rate(exceptions, llm_rounds, action_trace),
            self._metric_claim_bearing_rate(  # EVO-20260930: 口径拆分辅助指标（核心五维之外）
                current_checks, window_rows=cohort_window_rows
            ),
        ]
        summary = self._build_summary(metrics)
        # EVO-20260917-45863aeb B(i)(ii): 规则化哨兵（矛盾对+相邻突变，只标注不阻断）并入 note/diagnostics
        alerts = self._check_metric_consistency(metrics) + self._check_adjacent_shift(metrics)
        notes = [m.note for m in metrics if m.note] + alerts
        diagnostics = self._build_declaration_diagnostics(
            declaration_window, current_checks, source_versions
        )
        if alerts:
            diagnostics["consistency_alerts"] = alerts
        report = SelfEvalReport(
            eval_id=self._next_eval_id(),
            ts=_now(),
            session_id=session_id,
            trigger=trigger,
            metrics=metrics,
            summary=summary,
            note="；".join(notes) if notes else "",
            diagnostics=diagnostics,
        )
        self._persist(report)
        return report

    def _split_validator_cohort(self, rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
        """EVO-20260930.1 消费侧 cohort 隔离: 仅 validator_version == 当前期代的行进入
        honesty/claim_bearing/diagnostics；其余（缺字段=legacy 或其他代次）排除但计数可见。

        只写侧打版本不够——重启过渡期窗口内新旧两代混存时，聚合仍会混算
        （识别 cohort ≠ 隔离 cohort，本方法补齐消费侧）。
        """
        current: list[dict] = []
        versions: dict[str, int] = {}
        for row in rows:
            ver = str(row.get("validator_version") or "(unversioned)")
            versions[ver] = versions.get(ver, 0) + 1
            if ver == self._expected_validator_version:
                current.append(row)
        return current, dict(sorted(versions.items()))

    def _build_declaration_diagnostics(
        self,
        window_checks: list[dict],
        current_checks: list[dict],
        source_versions: dict[str, int],
    ) -> dict[str, Any]:
        """cohort 构成 + 当前代次 False 样本索引；事实正文仍留源日志按需水合.

        EVO-20260930.1: 始终携带 cohort 计数——重启过渡期 current_cohort_rows=0
        正是最需要可见的状态（此前无 False 时整个块缺省，该状态不可见）；
        false_samples 仍仅有 False 时携带。
        """
        recent = current_checks[-self._span :]
        evaluable_rows = sum(1 for row in recent if self._is_claim_bearing(row))
        false_rows = [row for row in recent if row.get("consistent") is False]
        block: dict[str, Any] = {
            "window_rows": len(window_checks),
            "current_cohort_rows": len(recent),
            "excluded_other_cohort_rows": len(window_checks) - len(recent),
            "source_validator_versions": source_versions,
            "expected_validator_version": self._expected_validator_version,
            "sample_size": len(recent),
            "evaluable_rows": evaluable_rows,
            "not_evaluable_rows": len(recent) - evaluable_rows,
            "false_count": len(false_rows),
        }
        if not false_rows:
            return {"declaration_check": block}

        def _first_text(value: Any, max_chars: int = 160) -> str:
            if not isinstance(value, list) or not value:
                return ""
            return str(value[0])[:max_chars]

        samples: list[dict[str, Any]] = []
        for row in false_rows:
            samples.append(
                {
                    "ref": str(row.get("id") or row.get("_source_ref") or ""),
                    "ts": str(row.get("ts") or ""),
                    "declaration_summary": _first_text(row.get("declarations")),
                    "discrepancy_summary": _first_text(row.get("discrepancies")),
                    "cross_round_hit": bool(row.get("cross_round_hits")),
                    "tool_call_ids": [
                        str(v) for v in (row.get("tool_call_ids") or [])[:8]
                    ],
                }
            )
        block["false_samples"] = samples
        return {"declaration_check": block}

    def _next_eval_id(self) -> str:
        """生成跨进程唯一 eval_id（M16 审计 FR-AUDIT-AI-10 修复）.

        格式 SE-YYYYMMDD-NNN-XXXX: 当日文件计数（self_eval_log.jsonl 中当日行数 + 1）
        + 随机后缀（防同日并发/读写竞态）；文件读取失败 fail-open（count=0 兜底）。
        """
        now = system_local_now()
        date = now.strftime("%Y%m%d")
        count = 0
        path = self._audit_dir / "self_eval_log.jsonl"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        if f"SE-{date}-" in line:
                            count += 1
            except OSError:
                count = 0  # fail-open
        return f"SE-{date}-{count + 1:03d}-{uuid.uuid4().hex[:4]}"

    # ── 各指标聚合 ──
    def _metric_success_rate(self, action_trace: list[dict]) -> EvalMetric:
        """任务成功率 ← action_trace: 近 span 条动作中成功动作占比."""
        recent = action_trace[-self._span :]
        if len(recent) < self._min_samples:
            return EvalMetric(
                name="success_rate",
                value=None,
                sample_size=len(recent),
                source="action_trace",
                note=f"样本不足（{len(recent)} < {self._min_samples}）",
            )
        success = sum(1 for a in recent if self._is_success_action(a))
        return EvalMetric(
            name="success_rate",
            value=round(success / len(recent), 4),
            sample_size=len(recent),
            source="action_trace",
            # EVO-20260917-45863aeb: 正常计算也写明口径，数字自带可审计构成
            note=f"分子={success} 条成功动作/分母={len(recent)} 条动作(近span)",
        )

    @staticmethod
    def _is_success_action(item: dict) -> bool:
        """成功动作判定（按 action_type 归一）: 失败类/异常类 → 非成功."""
        action_type = str(item.get("action_type", "")).lower()
        return not ("error" in action_type or "missing" in action_type or "fail" in action_type)

    def _metric_tool_efficiency(self, tool_history: list[dict]) -> EvalMetric:
        """工具效率 ← tool_history: 近 span 条工具调用 success / 总数.

        EVO-20260816-dc3876f9: 低调用频次不再一律 N/A——有样本即评估（小样本如实标注），
        仅无样本才 N/A；原逻辑样本<min_samples 恒 N/A，工具调用稀疏时指标形同虚设。
        """
        recent = tool_history[-self._span :]
        if not recent:
            return EvalMetric(
                name="tool_efficiency",
                value=None,
                sample_size=0,
                source="tool_history",
                note="无工具调用样本",
            )
        success = sum(1 for t in recent if t.get("status") == "success")
        # EVO-20260917-45863aeb: 正常计算也写明口径；小样本附加标注
        note = f"分子={success} 条成功调用/分母={len(recent)} 条调用"
        if len(recent) < self._min_samples:
            note += f"；小样本（{len(recent)} < {self._min_samples}）"
        return EvalMetric(
            name="tool_efficiency",
            value=round(success / len(recent), 4),
            sample_size=len(recent),
            source="tool_history",
            note=note,
        )

    @staticmethod
    def _is_claim_bearing(check: dict) -> bool:
        """可评估行（claim-bearing）: declarations 为非空 list.

        EVO-20260930 口径修复: consistent=True 包含『声明列表为空』的自动通过行
        （declaration_check 审计中 1462/3068 行为空声明自动 True）。旧口径把这类行
        计入分母得到的是回答级联合通过率，既非声明级一致率也非条件诚实率。
        历史行缺 declarations 字段（2026-09-03 前匿名 cohort）同样按不可评估处理。
        """
        decl = check.get("declarations")
        return isinstance(decl, list) and len(decl) > 0

    def _cohort_note(self, window_rows: int | None, current_rows: int | None) -> str:
        """cohort 隔离说明（无排除时不附加，保持正常路径 note 简洁）."""
        if window_rows is None or current_rows is None:
            return ""
        excluded = window_rows - current_rows
        if excluded <= 0:
            return ""
        return (
            f"；cohort 隔离: 当前 validator 代次 {current_rows} 行/窗口 {window_rows} 行"
            f"（排除其他代次 {excluded} 行）"
        )

    def _metric_honesty_rate(
        self,
        checks: list[dict],
        *,
        window_rows: int | None = None,
        current_rows: int | None = None,
    ) -> EvalMetric:
        """诚实性 ← declaration_check.jsonl: 当前 validator 代次中『有声明行』的条件一致占比.

        新口径（EVO-20260930）: 分母 = 有声明的检查记录（claim-bearing rows），
        分子 = 其中 consistent=True 的行。空声明/缺字段行 → not_evaluable 不进分母，
        其规模由 claim_bearing_rate 单独披露，不再隐藏在联合通过率里。
        cohort 隔离（EVO-20260930.1）: 仅聚合 validator_version == 当前期代的行；
        重启过渡期当前代次不足 min_samples 时如实 N/A，不拿 legacy 代次填样本量。
        """
        recent = checks[-self._span :]
        evaluable = [c for c in recent if self._is_claim_bearing(c)]
        not_evaluable = len(recent) - len(evaluable)
        cohort_note = self._cohort_note(window_rows, current_rows)
        if len(evaluable) < self._min_samples:
            return EvalMetric(
                name="honesty_rate",
                value=None,
                sample_size=len(evaluable),
                source="declaration_check",
                note=(
                    f"样本不足（可评估行 {len(evaluable)} < {self._min_samples}；"
                    f"不可评估 {not_evaluable} 条未计入）{cohort_note}"
                ),
            )
        consistent = sum(1 for c in evaluable if c.get("consistent") is True)
        return EvalMetric(
            name="honesty_rate",
            value=round(consistent / len(evaluable), 4),
            sample_size=len(evaluable),
            source="declaration_check",
            note=(
                f"分子={consistent} 条一致(有声明行)/分母={len(evaluable)} 条有声明检查记录(近span)"
                f"；未声明行 {not_evaluable} 条不计入(not_evaluable){cohort_note}"
            ),
        )

    def _metric_claim_bearing_rate(self, checks: list[dict], *, window_rows: int = 0) -> EvalMetric:
        """声明携带率 ← declaration_check 当前代次近 span 条中『有声明』行占比（辅助口径指标）.

        EVO-20260930: 与 honesty_rate 拆分——空声明自动通过的规模在此单独披露。
        命名注意: 单位是『检查记录/回答』（一条记录可含多条声明），不是声明条数。
        cohort 隔离（EVO-20260930.1）: 分母为当前 validator 代次行，legacy 行不混入。
        """
        recent = checks[-self._span :]
        total = len(recent)
        if total == 0:
            note = (
                f"样本不足（当前 validator 代次 0 行/窗口 {window_rows} 行均为其他代次，已隔离）"
                if window_rows
                else "样本不足（无检查记录）"
            )
            return EvalMetric(
                name="claim_bearing_rate",
                value=None,
                sample_size=0,
                source="declaration_check",
                note=note,
            )
        bearing = sum(1 for c in recent if self._is_claim_bearing(c))
        note = f"分子={bearing} 条有声明记录/分母={total} 条检查记录(近span)"
        if total < self._min_samples:
            note += f"；小样本（{total} < {self._min_samples}）"
        return EvalMetric(
            name="claim_bearing_rate",
            value=round(bearing / total, 4),
            sample_size=total,
            source="declaration_check",
            note=note,
        )

    def _metric_stagnation_rate(self, action_trace: list[dict]) -> EvalMetric:
        """停滞率 ← action_trace 近 span 条『连续重复动作』占比（EVO-20260827-03416178）.

        判定口径: 连续两条指纹相同才计一次重复——真实退化循环必然背靠背重试
        同一动作；正常交替工作流中的同类调用（decile→tool 对、跨任务的同工具）
        不再误判为停滞。understand.* 程序记账动作（每轮必发，如 model_aware_budget）
        不参与判定，避免结构性虚高。
        """
        recent = action_trace[-self._span :]
        eligible = [
            a for a in recent if not str(a.get("phase", "")).startswith("understand.")
        ]
        if len(eligible) < self._min_samples:
            return EvalMetric(
                name="stagnation_rate",
                value=None,
                sample_size=len(eligible),
                source="action_trace",
                note=f"样本不足（记账剔除后 {len(eligible)} < {self._min_samples}）",
            )

        def _fp(a: dict) -> str:
            return f"{a.get('phase', '')}|{a.get('action_type', '')}|{a.get('detail', '')}"

        repeats = sum(
            1
            for i in range(1, len(eligible))
            if _fp(eligible[i]) == _fp(eligible[i - 1])
        )
        exempt = len(recent) - len(eligible)
        return EvalMetric(
            name="stagnation_rate",
            value=round(repeats / len(eligible), 4),
            sample_size=len(eligible),
            source="action_trace",
            note=(f"连续重复口径（剔除程序记账 {exempt} 条）" if exempt else "连续重复口径"),
        )

    def _metric_exception_rate(
        self, exceptions: list[dict], llm_rounds: int, action_trace: list[dict] | None = None
    ) -> EvalMetric:
        """异常率 ← exception_log / 评估窗口内 llm 轮次（EVO-20260827-c6908267）.

        口径对齐修复: 分母不再取当前进程 llm_rounds 快照（短新会话必然虚高），
        优先用评估时间窗内 action_trace 的 record_llm_round 计数——与分子
        （时间窗过滤后的异常条数）同一窗口，口径自洽；无法计数时回退进程快照。
        note 固定写明分子/分母构成，使数字自带口径可审计；无轮次依据时如实置 None。
        """
        recent = exceptions[-self._span :]
        rounds_src = "process_snapshot"
        if action_trace:
            win_rounds = sum(
                1
                for a in action_trace
                if a.get("phase", "") == "action.llm_decide"
                and a.get("action_type", "") == "llm_response"
            )
            if win_rounds > 0:
                llm_rounds = win_rounds
                rounds_src = "window_action_trace"
        if llm_rounds < self._min_samples:
            return EvalMetric(
                name="exception_rate",
                value=None,
                sample_size=llm_rounds,
                source="exception_log",
                note=f"样本不足（{rounds_src} {llm_rounds} 轮 < {self._min_samples}）",
            )
        value = round(len(recent) / llm_rounds, 4)
        note = f"分子={len(recent)} 条(近span)/分母={llm_rounds} 轮({rounds_src})"
        if len(recent) >= llm_rounds:
            note += "；分子≥分母，已封顶 1.0"  # EVO-20260917-45863aeb: 截断显式化
        return EvalMetric(
            name="exception_rate",
            value=min(value, 1.0),
            sample_size=llm_rounds,
            source="exception_log",
            note=note,
        )

    def _build_summary(self, metrics: list[EvalMetric]) -> str:
        """聚合摘要（程序按指标如实生成的客观描述，非 LLM 结论）."""
        parts: list[str] = []
        for m in metrics:
            if m.value is None:
                parts.append(f"{m.name}=N/A（{m.note}）")
            else:
                parts.append(f"{m.name}={m.value:.2f}")
        # EVO-20260816-f1f73a0d: 摘要注明采样窗口（时间窗 + span 上限）
        window_desc = (
            f"近 {self._window_hours:g}h 时间窗（最多 {self._span} 条）"
            if self._window_hours > 0
            else f"近 {self._span} 条"
        )
        return f"{window_desc}窗口指标: {parts}"

    # ── EVO-20260917-45863aeb: 跨指标哨兵（规则化，只标注不阻断）──
    @staticmethod
    def _check_metric_consistency(metrics: list[EvalMetric]) -> list[str]:
        """B(i) 矛盾对哨兵（只标注不阻断，评估 fail-open 红线不变）.

        - exception_rate > 0.8 且 success_rate > 0.8 同现 → 分母口径疑似失真
          （提案 B(i) 原口径；2026-09-17 首次落盘曾静默偏为 ≥0.5/≥0.9，本次对齐提案）：
          2026-08-27 SE 案例中 process_snapshot 分母虚高致 exception_rate=1.00 与
          success_rate=1.00 剧烈矛盾；主修复 EVO-20260827-c6908267，此处防同类回归。
        """
        by_name = {m.name: m for m in metrics}
        exc = by_name.get("exception_rate")
        suc = by_name.get("success_rate")
        if not exc or not suc or exc.value is None or suc.value is None:
            return []
        if exc.value > 0.8 and suc.value > 0.8:
            return [
                f"矛盾哨兵: exception_rate={exc.value:.2f} 与 success_rate={suc.value:.2f} 同现，"
                "分母口径疑似失真（参照 EVO-20260827-c6908267 案例模式，核查 note 中分母来源），"
                "口径存疑，需复核",
            ]
        return []

    def _check_adjacent_shift(self, metrics: list[EvalMetric]) -> list[str]:
        """B(ii) 相邻突变哨兵: 与 self_eval_log 上一条同指标 |Δ|≥0.5 → 口径存疑（只标注）.

        2026-08-27 案例形态: exception_rate 0.06 → 1.00 单次跳变，此前只能人工比对
        相邻两次评估才能发现。只读已落盘的上一条（当前报告在检查后才 persist，不会自比）；
        日志缺失/损坏如实降级为不比对（fail-open）。
        """
        prev = self._read_last_eval_metrics()
        if not prev:
            return []
        alerts: list[str] = []
        for m in metrics:
            if m.value is None:
                continue
            pv = prev.get(m.name)
            if pv is None:
                continue
            delta = abs(m.value - pv)
            if delta >= 0.5:
                alerts.append(
                    f"相邻突变哨兵: {m.name} 上一评估 {pv:.2f} → 本次 {m.value:.2f}"
                    f"（|Δ|={delta:.2f}≥0.50），口径存疑，需复核"
                )
        return alerts

    def _read_last_eval_metrics(self) -> dict[str, float]:
        """读 self_eval_log.jsonl 最后一条可解析记录的 {指标名: 值}（无/损坏 → 空）."""
        path = self._audit_dir / "self_eval_log.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out: dict[str, float] = {}
            for m in row.get("metrics", []):
                if not isinstance(m, dict):
                    continue
                v = m.get("value")
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue
                name = str(m.get("name") or "")
                if name:
                    out[name] = float(v)
            if out:
                return out
        return {}

    # ── 数据源读取（读取失败如实标注，不伪造）──
    def _read_jsonl(self, filename: str, *, with_source_ref: bool = False) -> list[dict]:
        path = self._audit_dir / filename
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if with_source_ref:
                        entry.setdefault("_source_ref", f"{filename}:L{line_no}")
                    out.append(entry)
        except OSError:
            return []
        return out

    def _read_action_trace(self) -> list[dict]:
        return self._read_jsonl("action_trace.jsonl")

    def _read_tool_history(self) -> list[dict]:
        """工具历史: 优先内存窗口（status snapshot），无则读 JSONL（不存在则空）."""
        if self._status is not None:
            try:
                snap = self._status.snapshot()
                return list(snap.get("tool_history", []) or [])
            except Exception:  # noqa: BLE001 — 读取失败如实降级
                pass
        return self._read_jsonl("tool_history.jsonl")

    def _read_declaration_checks(self) -> list[dict]:
        return self._read_jsonl("declaration_check.jsonl", with_source_ref=True)

    def _read_exceptions(self) -> list[dict]:
        return self._read_jsonl("exception_log.jsonl")

    def _time_filter(self, items: list[dict]) -> list[dict]:
        """EVO-20260816-f1f73a0d: 按时间窗过滤（ts 字段；解析失败保留，缺 ts 保留）.

        防历史旧记录污染当前评估（条数窗会把 5 天前的异常混入今日指标）。
        先时间窗过滤 → 再取 span 条（时间窗内最多 span 条）。
        """
        if not items or self._window_hours <= 0:
            return items
        try:
            cutoff = system_local_now().timestamp() - self._window_hours * 3600
        except Exception:  # noqa: BLE001 — 时间计算失败不过滤（fail-open）
            return items
        out: list[dict] = []
        for it in items:
            ts = str(it.get("ts", ""))
            if not ts:
                out.append(it)  # 缺 ts 保留（不误杀）
                continue
            try:
                # 兼容 ISO 带时区/不带时区
                t = ts
                if t.endswith("Z"):
                    t = t[:-1] + "+00:00"
                dt = datetime.fromisoformat(t)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                if dt.timestamp() >= cutoff:
                    out.append(it)
            except (ValueError, TypeError):
                out.append(it)  # 解析失败保留（fail-open）
        return out

    def _llm_rounds(self) -> int:
        if self._status is not None:
            try:
                snap = self._status.snapshot()
                ctx = snap.get("context_usage", {}) or {}
                rounds = ctx.get("llm_rounds", 0)
                return int(rounds or 0)
            except Exception:  # noqa: BLE001 — 读取失败如实降级
                return 0
        return 0

    # ── 落盘（EVAL-04，fail-open）──
    def _persist(self, report: SelfEvalReport) -> None:
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            with (self._audit_dir / "self_eval_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open（DFX-REL-06）
