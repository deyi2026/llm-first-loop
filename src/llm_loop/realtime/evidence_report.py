"""五类证据分开报告与阶段门禁（`T-GATE-5`）。

对应需求：`RTM-EVD-01/02/03/04/05/06`、`RTM-OBS-06/07/09`、`RTM-PRF-01/08`。

- 四类证据**分开**：模拟 / 真实设备 / 真实 Provider / 生产部署；
- 第五类分级：**服务级已实测 vs 浏览器链路已验收**（`RTM-EVD-06`）；
- 缺任一真实证据 → 列「**未验收**」；**禁止提前写 PASS**；
- 性能分离「已测 / 达标」，且**已测必须是浏览器链路口径**（`RTM-PRF-01`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from llm_loop.realtime.evidence_grading import EvidenceLevel


class EvidenceClass(StrEnum):
    """四类证据（分开报告，不互相冒充）。"""

    SIMULATED = "simulated"
    REAL_DEVICE = "real_device"
    REAL_PROVIDER = "real_provider"
    PRODUCTION = "production"


REAL_EVIDENCE_CLASSES: frozenset[EvidenceClass] = frozenset(
    {EvidenceClass.REAL_DEVICE, EvidenceClass.REAL_PROVIDER, EvidenceClass.PRODUCTION}
)


class AcceptanceStatus(StrEnum):
    ACCEPTED = "accepted"
    NOT_ACCEPTED = "not_accepted"  # 缺真实证据
    MEASURED_NOT_MET = "measured_not_met"  # 已测但未达标


@dataclass(frozen=True)
class EvidenceEntry:
    name: str
    evidence_class: EvidenceClass
    acceptance_level: EvidenceLevel
    measured: bool = False
    met: bool = False
    command: str = ""
    exit_code: int | None = None
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("evidence name is required")
        if not isinstance(self.evidence_class, EvidenceClass):
            raise TypeError("evidence_class must be EvidenceClass")
        if not isinstance(self.acceptance_level, EvidenceLevel):
            raise TypeError("acceptance_level must be EvidenceLevel")


@dataclass
class EvidenceReport:
    entries: list[EvidenceEntry] = field(default_factory=list)

    def add(self, entry: EvidenceEntry) -> EvidenceEntry:
        self.entries.append(entry)
        return entry

    def by_class(self, evidence_class: EvidenceClass) -> tuple[EvidenceEntry, ...]:
        return tuple(e for e in self.entries if e.evidence_class is evidence_class)

    def by_level(self, level: EvidenceLevel) -> tuple[EvidenceEntry, ...]:
        return tuple(e for e in self.entries if e.acceptance_level is level)

    def acceptance_status(self, name: str) -> AcceptanceStatus:
        """单条验收状态：缺真实证据 → 未验收；已测未达标 → `measured_not_met`。"""
        for entry in self.entries:
            if entry.name != name:
                continue
            if entry.acceptance_level is EvidenceLevel.BROWSER_LINK and not entry.measured:
                return AcceptanceStatus.NOT_ACCEPTED
            if entry.evidence_class is EvidenceClass.SIMULATED or not entry.measured:
                return AcceptanceStatus.NOT_ACCEPTED
            return AcceptanceStatus.ACCEPTED if entry.met else AcceptanceStatus.MEASURED_NOT_MET
        return AcceptanceStatus.NOT_ACCEPTED

    def missing_real_evidence(self) -> tuple[str, ...]:
        present = {e.evidence_class for e in self.entries if e.measured}
        return tuple(sorted(c.value for c in REAL_EVIDENCE_CLASSES if c not in present))

    def may_declare_pass(self) -> bool:
        """**禁止提前写 PASS**：需浏览器链路**真实**证据且达标。"""
        browser = [
            e
            for e in self.by_level(EvidenceLevel.BROWSER_LINK)
            if e.evidence_class is not EvidenceClass.SIMULATED
        ]
        return bool(browser) and all(e.measured and e.met for e in browser)

    def service_level_is_not_browser_acceptance(self) -> bool:
        """服务级样本不构成浏览器验收。"""
        return not any(
            e.acceptance_level is EvidenceLevel.BROWSER_LINK and e.measured
            for e in self.entries
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "classes": {c.value: len(self.by_class(c)) for c in EvidenceClass},
            "service_level": len(self.by_level(EvidenceLevel.SERVICE_LEVEL)),
            "browser_link": len(self.by_level(EvidenceLevel.BROWSER_LINK)),
            "missing_real_evidence": list(self.missing_real_evidence()),
            "may_declare_pass": self.may_declare_pass(),
        }
