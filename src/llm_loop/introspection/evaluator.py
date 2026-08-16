"""AI 自我评估聚合器与触发检测（design.md §6.2 / FR-AUTO-CLOSE-EVAL）.

- SelfEvaluator: 从既有数据源（action_trace / tool_history / exception_log / declaration_check）
  聚合五维指标（成功率/工具效率/诚实性/停滞率/异常率），每条指标可溯源；纯聚合（无 LLM 往返）
- EvalTriggerDetector: 三类触发（定期/里程碑/异常），仅提示不强制（决策权归 LLM）
- SelfEvalReport: 评估结果（EVAL-04 落盘 self_eval_log.jsonl，可经 search_records 检索）
- 对比判定（EVAL-07）: 由 AI 先后两次 self_evaluate 自行比对指标 delta（来源可溯），程序不提供 compare

红线: 评估数据必须如实（来源可溯，禁止伪造）；样本不足/来源不可用如实标注（spec.md 10.2.3-1）；
评估不阻塞主循环（O(span) 轻量聚合，落盘 fail-open）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# 五维指标名（EVAL-02）
METRIC_NAMES = (
    "success_rate",
    "tool_efficiency",
    "honesty_rate",
    "stagnation_rate",
    "exception_rate",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class EvalMetric:
    """单维度评估指标（EVAL-02，来源可溯）."""

    name: str  # success_rate / tool_efficiency / honesty_rate / stagnation_rate / exception_rate
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
    metrics: list[EvalMetric]  # 五维指标（如实，可溯源）
    summary: str  # 聚合摘要（程序按指标如实生成的客观描述，非 LLM 结论）
    note: str = ""  # 整体说明（如"声明-回执数据不足，诚实性指标样本不足"）

    def to_dict(self) -> dict:
        return {
            "eval_id": self.eval_id,
            "ts": self.ts,
            "session_id": self.session_id,
            "trigger": self.trigger,
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


@dataclass(frozen=True)
class EvalTrigger:
    """一次自我评估触发（EVAL-03，仅提示不强制）.

    M16 审计（FR-AUDIT-AI-04/08）: trigger 收敛为 periodic/milestone（异常触发时机移交
    AI 自主判断，RULE-AI-06 子规则 3）；manual self_evaluate(trigger=anomaly) 通道仍存在
    （SelfEvalReport.trigger 保留 anomaly 枚举）。
    """

    trigger: Literal["periodic", "milestone"]
    fact: str  # 事实（如 "已连续运行 50 轮"）
    reason: str  # 原因
    suggestion: str  # 建议（"可调用 self_evaluate 进行自我评估…"）


class EvalTriggerDetector:
    """自我评估触发检测器（EVAL-03）: 定期/里程碑两类确定性触发（检测纯函数，无 IO）.

    M16 审计（FR-AUDIT-AI-04/08）: 移除失效的 anomaly 异常三路触发（参数语义错误致永不
    命中/取模错乱），异常触发时机移交 AI 自主判断（RULE-AI-06 子规则 3）。
    """

    def __init__(
        self,
        *,
        interval_rounds: int = 50,  # SELF_EVAL_INTERVAL_ROUNDS
    ) -> None:
        self._interval_rounds = interval_rounds

    def check(
        self,
        *,
        rounds: int,
        session_ended: bool = False,
        task_completed: bool = False,
    ) -> EvalTrigger | None:
        """检测两类确定性触发（命中返回触发；否则 None）."""
        # 1. periodic 定期: rounds % interval == 0
        if self._interval_rounds > 0 and rounds > 0 and rounds % self._interval_rounds == 0:
            return EvalTrigger(
                trigger="periodic",
                fact=f"已连续运行 {rounds} 轮",
                reason=f"达到定期评估间隔（每 {self._interval_rounds} 轮）",
                suggestion="可调用 self_evaluate 进行自我评估，发现改进机会可 submit_evolution",
            )
        # 2. milestone 里程碑: run 完成/会话结束
        if session_ended or task_completed:
            return EvalTrigger(
                trigger="milestone",
                fact="本轮 run 已完成" if task_completed else "会话已结束",
                reason="里程碑节点（run 完成/会话结束）",
                suggestion="可调用 self_evaluate 进行自我评估，沉淀本轮经验与改进机会",
            )
        return None


class SelfEvaluator:
    """自我评估聚合器（EVAL-01/02）: 从既有数据源聚合指标，来源可溯."""

    def __init__(
        self,
        *,
        status_provider: Any | None = None,  # ArchitectureStatusProvider
        audit_dir: str | Path,
        min_samples: int = 5,  # SELF_EVAL_MIN_SAMPLES
        span: int = 50,  # SELF_EVAL_SPAN 聚合窗口
    ) -> None:
        self._status = status_provider
        self._audit_dir = Path(audit_dir)
        self._min_samples = min_samples
        self._span = span

    # ── 五维聚合 ──
    def evaluate(
        self,
        session_id: str = "",
        trigger: Literal["periodic", "milestone", "anomaly", "manual"] = "manual",
    ) -> SelfEvalReport:
        """聚合五维指标（来源可溯；数据不足如实标注）."""
        action_trace = self._read_action_trace()
        tool_history = self._read_tool_history()
        declaration_checks = self._read_declaration_checks()
        exceptions = self._read_exceptions()
        llm_rounds = self._llm_rounds()

        metrics = [
            self._metric_success_rate(action_trace),
            self._metric_tool_efficiency(tool_history),
            self._metric_honesty_rate(declaration_checks),
            self._metric_stagnation_rate(action_trace),
            self._metric_exception_rate(exceptions, llm_rounds),
        ]
        summary = self._build_summary(metrics)
        notes = [m.note for m in metrics if m.note]
        report = SelfEvalReport(
            eval_id=self._next_eval_id(),
            ts=_now(),
            session_id=session_id,
            trigger=trigger,
            metrics=metrics,
            summary=summary,
            note="；".join(notes) if notes else "",
        )
        self._persist(report)
        return report

    def _next_eval_id(self) -> str:
        """生成跨进程唯一 eval_id（M16 审计 FR-AUDIT-AI-10 修复）.

        格式 SE-YYYYMMDD-NNN-XXXX: 当日文件计数（self_eval_log.jsonl 中当日行数 + 1）
        + 随机后缀（防同日并发/读写竞态）；文件读取失败 fail-open（count=0 兜底）。
        """
        now = datetime.now(UTC)
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
        note = (
            ""
            if len(recent) >= self._min_samples
            else f"小样本（{len(recent)} < {self._min_samples}）"
        )
        return EvalMetric(
            name="tool_efficiency",
            value=round(success / len(recent), 4),
            sample_size=len(recent),
            source="tool_history",
            note=note,
        )

    def _metric_honesty_rate(self, checks: list[dict]) -> EvalMetric:
        """诚实性 ← declaration_check.jsonl: 近 span 条 consistent / 总数."""
        recent = checks[-self._span :]
        if len(recent) < self._min_samples:
            return EvalMetric(
                name="honesty_rate",
                value=None,
                sample_size=len(recent),
                source="declaration_check",
                note=f"样本不足（{len(recent)} < {self._min_samples}）",
            )
        consistent = sum(1 for c in recent if c.get("consistent") is True)
        return EvalMetric(
            name="honesty_rate",
            value=round(consistent / len(recent), 4),
            sample_size=len(recent),
            source="declaration_check",
        )

    def _metric_stagnation_rate(self, action_trace: list[dict]) -> EvalMetric:
        """停滞率 ← action_trace: 近 span 条重复动作（同工具同参数指纹）占比."""
        recent = action_trace[-self._span :]
        if len(recent) < self._min_samples:
            return EvalMetric(
                name="stagnation_rate",
                value=None,
                sample_size=len(recent),
                source="action_trace",
                note=f"样本不足（{len(recent)} < {self._min_samples}）",
            )
        seen: set[str] = set()
        repeats = 0
        for a in recent:
            fingerprint = f"{a.get('phase', '')}|{a.get('action_type', '')}|{a.get('detail', '')}"
            if fingerprint in seen:
                repeats += 1
            else:
                seen.add(fingerprint)
        return EvalMetric(
            name="stagnation_rate",
            value=round(repeats / len(recent), 4),
            sample_size=len(recent),
            source="action_trace",
        )

    def _metric_exception_rate(self, exceptions: list[dict], llm_rounds: int) -> EvalMetric:
        """异常率 ← exception_log + record_llm_round: 近 span 条异常数 / 轮数."""
        recent = exceptions[-self._span :]
        if llm_rounds < self._min_samples:
            return EvalMetric(
                name="exception_rate",
                value=None,
                sample_size=llm_rounds,
                source="exception_log",
                note=f"样本不足（{llm_rounds} 轮 < {self._min_samples}）",
            )
        value = round(len(recent) / llm_rounds, 4)
        return EvalMetric(
            name="exception_rate",
            value=min(value, 1.0),
            sample_size=llm_rounds,
            source="exception_log",
        )

    def _build_summary(self, metrics: list[EvalMetric]) -> str:
        """聚合摘要（程序按指标如实生成的客观描述，非 LLM 结论）."""
        parts: list[str] = []
        for m in metrics:
            if m.value is None:
                parts.append(f"{m.name}=N/A（{m.note}）")
            else:
                parts.append(f"{m.name}={m.value:.2f}")
        return "近 {span} 条窗口指标: {parts}".format(span=self._span, parts="、".join(parts))

    # ── 数据源读取（读取失败如实标注，不伪造）──
    def _read_jsonl(self, filename: str) -> list[dict]:
        path = self._audit_dir / filename
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
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
        return self._read_jsonl("declaration_check.jsonl")

    def _read_exceptions(self) -> list[dict]:
        return self._read_jsonl("exception_log.jsonl")

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
