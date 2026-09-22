#!/usr/bin/env python3
"""rule_presence 只读离线盘点器（M1~M4 + InventoryReport）。

形态声明（spec §4.1.2 / design I6 / tasks 5.1）：
- **离线**：不进入 run 决策路径，不被 loop/engine 引用。
- **只读**：不写任何被测对象（prompt/SoT/lite/工具契约/run 证据）；盘点前后哈希不变（AC-17）。
- **fail-open**：任一观测失败只降低确定性标注，不抛断整体盘点，不改变模型可见行为。
- **确定性**：同输入同输出（`inventory` 的 `generated_at` 可注入以复现）。
- **非 CI 硬门**：不接入 CI / 不作为 build/test 阻塞项（用户裁定 #4）。

用法：
    .venv/bin/python scripts/rule_presence_audit.py            # 人类可读
    .venv/bin/python scripts/rule_presence_audit.py --json     # 机器可读
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SOT = _ROOT / "docs" / "ai_rules.md"
_LITE = _ROOT / "docs" / "ai_rules.lite.md"
_PROMPT_PY = _ROOT / "src" / "llm_loop" / "core" / "prompt.py"
_DEFAULT_LEDGER = _ROOT / "data" / "audit" / "injection_ledger.jsonl"

_RULE_RE = re.compile(r"RULE-AI-\d{2}")

# M1 规则要素级口令：用于扫描 provider-view 是否承载"规则要素"（非规则正文）。
_RULE_ELEMENT_TOKENS: tuple[str, ...] = (
    "直接回答",
    "单条状态",
    "调整策略",
    "按需检索",
    "按需水合",
    "完成裁决",
    "RULE-AI",
    "已验证经验/方法",
)

# A-G2：11 类运维主题关键词（不应出现在 universal prompt）。
_OPS_TOPIC_TOKENS: tuple[str, ...] = (
    "部署",
    "端口",
    "回滚",
    "凭据",
    "密钥",
    "隧道",
    "重启",
    "环境变量",
    "pytest",
    "docker",
    "nginx",
)

# A-G3：方法层①~⑥ 关键词（已迁 skill，不应出现在 universal prompt）。
_METHOD_TOKENS: tuple[str, ...] = (
    "显式状态追踪",
    "前置自问",
    "假设先行",
    "增量推理",
    "结论固化",
    "工具轮思考链",
)

# A-G1：必读/训诫类口令（不应出现在 universal prompt）。
_MANDATE_TOKENS: tuple[str, ...] = ("必读", "必须", "禁止", "严禁")

# scope 分区：SoT 正文规则之外的登记项。
_EXTRA_SCOPES: tuple[tuple[str, str], ...] = (
    ("RULE-AI-00 附则①~⑥", "附则（方法层总则，随 RULE-AI-00 生效）"),
    ("RULE-AI-06 子规则1~6", "子规则（架构演进/自评执行细则）"),
    ("方法层①~⑥", "方法层（已迁 skills/long-task-research/SKILL.md，按需加载）"),
)

_UNSET = object()


@dataclass(frozen=True)
class ObservationEvidence:
    method: str
    query_token: str
    hits: int
    hit_context: str
    evidence_complete: bool


@dataclass(frozen=True)
class RulePresenceRecord:
    rule_ref: str
    rule_scope: str
    primary_carrier: str
    other_carriers: tuple[str, ...]
    state: str
    observation_method: str
    measured_value: str
    determinacy: str


@dataclass(frozen=True)
class GapEntry:
    gap_id: str
    category: str
    records: tuple[str, ...]
    hypothesis: str
    carrier_decision: str
    actionable: bool


@dataclass(frozen=True)
class InventoryReport:
    generated_at: str
    base_prompt_hash: str
    lite_version: str
    records: tuple[RulePresenceRecord, ...]
    gaps: tuple[GapEntry, ...]
    uncovered: tuple[str, ...]
    evidence: tuple[ObservationEvidence, ...] = field(default=())


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_base_prompt() -> str | None:
    try:
        from llm_loop.core.prompt import _BASE_PROMPT

        return _BASE_PROMPT
    except Exception:
        return None


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _lite_version() -> str:
    text = _read_text(_LITE)
    if text is None:
        return "无法判定"
    m = re.search(r"version\s*[=:]\s*(\d+)", text)
    return m.group(1) if m else "无法判定"


def provider_view_scan(base_prompt: object = _UNSET) -> list[ObservationEvidence]:
    """M1：对 provider-view（universal prompt）做规则要素级口令扫描（只读）。"""
    if base_prompt is _UNSET:
        base_prompt = _load_base_prompt()
    if base_prompt is None:
        return [
            ObservationEvidence("M1", tok, -1, "provider-view 不可读", False)
            for tok in _RULE_ELEMENT_TOKENS
        ]
    out: list[ObservationEvidence] = []
    for tok in _RULE_ELEMENT_TOKENS:
        idx = base_prompt.find(tok)
        ctx = base_prompt[max(0, idx - 12): idx + len(tok) + 12] if idx >= 0 else ""
        out.append(ObservationEvidence("M1", tok, base_prompt.count(tok), ctx, True))
    return out


def hydration_kind_counts(ledger_path: Path | str | None = None) -> dict[str, int]:
    """M2：按既有 `record_kind` 字段聚合 hydration 行（只读；`rule` 单列）。"""
    path = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER
    counts: dict[str, int] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {"__unavailable__": -1}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("kind", "")) != "hydration":
            continue
        rk = str(row.get("record_kind", "") or "?")
        counts[rk] = counts.get(rk, 0) + 1
    return counts


def carrier_alignment_matrix(base_prompt: object = _UNSET) -> list[dict]:
    """M3：SoT 条款 ↔ provider-view 命中的机械对齐矩阵（只读）。"""
    sot = _read_text(_SOT)
    if sot is None:
        return []
    if base_prompt is _UNSET:
        base_prompt = _load_base_prompt()
    rows: list[dict] = []
    for ref in sorted(set(_RULE_RE.findall(sot)), key=lambda r: int(r.split("-")[-1])):
        hits = base_prompt.count(ref) if base_prompt is not None else -1
        rows.append({"rule_ref": ref, "base_prompt_hits": hits})
    return rows


def slimming_gate_status(base_prompt: object = _UNSET) -> dict[str, str]:
    """M4：A-G1~A-G4 契约瘦身口径的静态快照（只读；权威断言以 pytest 为准）。"""
    if base_prompt is _UNSET:
        base_prompt = _load_base_prompt()
    if base_prompt is None:
        return {k: "无法判定" for k in ("A-G1", "A-G2", "A-G3", "A-G4")}
    src = _read_text(_PROMPT_PY) or ""
    g1 = "green" if not any(t in base_prompt for t in _MANDATE_TOKENS) else "red"
    g2 = "green" if not any(t in base_prompt for t in _OPS_TOPIC_TOKENS) else "red"
    g3 = "green" if not any(t in base_prompt for t in _METHOD_TOKENS) else "red"
    g4 = "green" if (
        "SYSTEM_PROMPT_EXTRA" not in src and "LFL_SYSTEM_EXTRA_BUNDLE" not in src
    ) else "red"
    return {"A-G1": g1, "A-G2": g2, "A-G3": g3, "A-G4": g4}


def inventory(
    *,
    base_prompt: object = _UNSET,
    ledger_path: Path | str | None = None,
    generated_at: str | None = None,
) -> InventoryReport:
    """汇总 `InventoryReport`（只读；`base_prompt=None` 显式触发"无法判定"）。"""
    if base_prompt is _UNSET:
        base_prompt = _load_base_prompt()
    available = base_prompt is not None

    sot = _read_text(_SOT)
    refs = (
        sorted(set(_RULE_RE.findall(sot)), key=lambda r: int(r.split("-")[-1]))
        if sot
        else []
    )

    records: list[RulePresenceRecord] = []
    uncovered: list[str] = []
    if not refs:
        uncovered.append("docs/ai_rules.md 不可读：SoT 规则集无法枚举")

    for ref in refs:
        if not available:
            records.append(
                RulePresenceRecord(
                    ref, "SoT 正文规则", "无法判定", (), "无法判定", "M1", "provider-view 不可读", "无法判定"
                )
            )
            continue
        hits = base_prompt.count(ref)
        if hits > 0:
            rec = RulePresenceRecord(
                ref, "SoT 正文规则", "universal prompt", (), "在prompt", "M1", f"hits={hits}", "在场"
            )
        else:
            rec = RulePresenceRecord(
                ref,
                "SoT 正文规则",
                "工具契约/按需水合（待人工登记）",
                (),
                "在库未注入",
                "M1",
                "provider-view hits=0",
                "在场",
            )
        records.append(rec)

    for name, scope in _EXTRA_SCOPES:
        state = "无法判定" if not available else "仅按需水合"
        carrier = "无法判定" if not available else "skills/long-task-research/SKILL.md"
        records.append(
            RulePresenceRecord(
                name, scope, carrier, (), state, "M1", "非正文条款，按 scope 登记", "在场" if available else "无法判定"
            )
        )

    gaps = (
        GapEntry(
            "G1",
            "终止性/收口决策点语义缺失",
            ("RULE-AI-03", "RULE-AI-11", "RULE-AI-20"),
            "决策点当轮契约未承载'可调整策略/直接回答/等待态可停止'，模型在停滞时无终止语义线索 → 重复/不收口。",
            "convergence_decide schema（description + compact_description）",
            True,
        ),
        GapEntry(
            "G2",
            "规则可发现性缺触发时机",
            ("RULE-AI-18", "RULE-AI-22", "RULE-AI-24"),
            "水合通道存在但契约未说明'何时该查'，模型不知此刻应转向取规则 → 事实不足时继续空转。",
            "search_records 契约（完整 + compact，每轮在场）",
            True,
        ),
        GapEntry(
            "G3",
            "收口出口在工具契约层缺席",
            ("RULE-AI-01", "RULE-AI-20"),
            "收口只能以'不调用任何工具'表达，程序不可观测、审计不可锚定，R2 事实无挂载点。",
            "convergence_decide decision=conclude（自陈，非完成裁决）",
            True,
        ),
    )

    evidence: list[ObservationEvidence] = list(provider_view_scan(base_prompt))
    if not available:
        evidence.append(ObservationEvidence("M2", "injection_ledger", -1, "provider-view 不可读，跳过计数", False))

    return InventoryReport(
        generated_at=generated_at or datetime.datetime.now().isoformat(timespec="seconds"),
        base_prompt_hash=_hash(str(base_prompt)) if available else "无法判定",
        lite_version=_lite_version(),
        records=tuple(records),
        gaps=gaps,
        uncovered=tuple(uncovered),
        evidence=tuple(evidence),
    )


def _report_to_dict(report: InventoryReport) -> dict:
    return {
        "generated_at": report.generated_at,
        "base_prompt_hash": report.base_prompt_hash,
        "lite_version": report.lite_version,
        "records": [asdict(r) for r in report.records],
        "gaps": [asdict(g) for g in report.gaps],
        "uncovered": list(report.uncovered),
        "evidence": [asdict(e) for e in report.evidence],
        "hydration_kind_counts": hydration_kind_counts(),
        "slimming_gate_status": slimming_gate_status(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()
    report = inventory()
    if args.json:
        print(json.dumps(_report_to_dict(report), ensure_ascii=False, indent=2))
        return 0
    print(f"base_prompt_hash={report.base_prompt_hash} lite_version={report.lite_version}")
    print(f"records={len(report.records)} gaps={len(report.gaps)} uncovered={len(report.uncovered)}")
    print(f"hydration_kind_counts={hydration_kind_counts()}")
    print(f"slimming_gate_status={slimming_gate_status()}")
    for rec in report.records:
        print(f"  {rec.rule_ref:<28} {rec.state:<10} {rec.determinacy:<6} {rec.primary_carrier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())