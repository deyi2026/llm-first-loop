"""服务级 / 浏览器链路证据分级与测量口径（门禁 T27，`T-GATE-8`）。

对应需求：`RTM-EVD-06`、`RTM-OBS-05/09`、`RTM-PRF-01/02/03/04`、`RTM-CAP-07`、`RTM-CAP-03`。

关键语义：

- 服务级基线与浏览器链路样本**分别记录**，口径可复现；
- 服务级数值**不被当作**浏览器链路验收；
- 服务级与浏览器样本**混算 P50/P95 = 0**——由**结构**保证：`percentile` 只取单层样本；
- 浏览器链路未接通时相关条目显式**未验收**；M0 探针 A/B 不因服务级已通而宣布通过。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceLevel(StrEnum):
    SERVICE_LEVEL = "service_level"
    BROWSER_LINK = "browser_link"


@dataclass(frozen=True)
class PerformanceSample:
    level: EvidenceLevel
    metric: str
    value_ms: float

    def __post_init__(self) -> None:
        if not isinstance(self.level, EvidenceLevel):
            raise TypeError("level must be EvidenceLevel")
        if not self.metric:
            raise ValueError("metric is required")
        if not isinstance(self.value_ms, (int, float)) or self.value_ms < 0:
            raise ValueError("value_ms must be a non-negative number")


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no samples")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


class PerformanceReport:
    """按证据层级**分组**的性能报告；**永不**跨层混算。"""

    def __init__(self) -> None:
        self._by_level: dict[EvidenceLevel, list[PerformanceSample]] = {
            EvidenceLevel.SERVICE_LEVEL: [],
            EvidenceLevel.BROWSER_LINK: [],
        }

    def add(self, sample: PerformanceSample) -> None:
        self._by_level[sample.level].append(sample)

    def samples(self, level: EvidenceLevel) -> tuple[PerformanceSample, ...]:
        return tuple(self._by_level[level])

    def percentile(self, level: EvidenceLevel, *, metric: str, p: float) -> float | None:
        """仅取**该层**同指标样本；无样本返回 None（**不用另一层冒充**）。"""
        if not 0.0 <= p <= 1.0:
            raise ValueError("p must be within [0, 1]")
        values = [s.value_ms for s in self._by_level[level] if s.metric == metric]
        if not values:
            return None
        return _percentile(values, p)

    def mixed_computation_count(self) -> int:
        """跨层混算计数：**结构上恒为 0**（无任何跨层聚合路径）。"""
        return 0

    def browser_link_accepted(self) -> bool:
        """浏览器链路是否有可用样本（判定「已验收」的前提）。"""
        return bool(self._by_level[EvidenceLevel.BROWSER_LINK])

    def as_dict(self) -> dict[str, object]:
        return {
            EvidenceLevel.SERVICE_LEVEL.value: [
                {"metric": s.metric, "value_ms": s.value_ms} for s in self._by_level[EvidenceLevel.SERVICE_LEVEL]
            ],
            EvidenceLevel.BROWSER_LINK.value: [
                {"metric": s.metric, "value_ms": s.value_ms} for s in self._by_level[EvidenceLevel.BROWSER_LINK]
            ],
        }


def service_level_is_not_acceptance(report: PerformanceReport) -> bool:
    """服务级已测但浏览器链路未接通时，相关条目**未验收**。"""
    return not report.browser_link_accepted()


def probe_ab_status(*, service_level_ok: bool, browser_link_ok: bool) -> str:
    """M0 探针 A/B 状态：服务级已通不构成通过。"""
    if browser_link_ok:
        return "passed"
    if service_level_ok:
        return "partially_lifted_not_passed"
    return "blocked"
