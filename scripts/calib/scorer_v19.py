"""Calibration scorer core v1.9 — v1.8 Action Commitment + verified-result integration semantics."""

from __future__ import annotations

import re

# 再导出（h2f_scorer 从本模块取 committed_action_matches）——`as` 自别名标记显式 re-export
from scripts.calib.scorer_v18 import committed_action_matches as committed_action_matches

SCORER_VERSION = "v1.9-measurement-core"
_CLAUSE_SPLIT = re.compile(r"[\n。；;！？!?]+")
_NONINTEGRATION = [
    "source_limit_exceeded",
    "source_not_available",
    "未能取得",
    "无法取得",
    "无法获取",
    "未获取",
    "未核实",
    "无法核实",
    "未验证",
    "未经验证",
    "待验证",
    "需要验证",
    "需要核实",
    "无法确认",
    "不能确认",
    "if ",
    "whether",
    "若",
    "如果",
    "假设",
    "可能",
    "待确认",
    "once verified",
    "when verified",
    "unable to verify",
    "not verified",
    "could not verify",
    "failed to retrieve",
]
_REPORT = [
    "record ",
    "summary",
    "旧",
    "历史",
    "引用",
    "声称",
    "写着",
    "claimed",
    "stated",
    "old plan",
    "old doc",
]


def source_successfully_verified(trace: list[dict], source: str) -> bool:
    for t in trace:
        if t.get("name") != "request_fixture" or t.get("source") != source:
            continue
        result = (t.get("result_full") or t.get("result_head") or "").strip().lower()
        if not result:
            continue
        if "source_limit_exceeded" in result or "source_not_available" in result:
            continue
        return True
    return False


def truth_integrated(text: str, truth_phrases: list[str]) -> bool:
    """Truth must be asserted as a current result, not hypothetical/unverified/reported."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text or "") if c.strip()]
    for phrase in truth_phrases:
        pl = phrase.lower()
        for c in clauses:
            cl = c.lower()
            if pl not in cl:
                continue
            if any(m in cl for m in _NONINTEGRATION):
                continue
            # reported historical clauses are not integration unless the same clause also
            # explicitly marks current/verified truth.
            if any(m in cl for m in _REPORT) and not any(
                m in cl
                for m in ["当前", "current", "已确认", "confirmed", "已核实", "verified", "事实"]
            ):
                continue
            return True
    return False


def novel_stage(
    trace: list[dict],
    source: str,
    text: str,
    truth_phrases: list[str],
    *,
    waiver: bool = False,
    verification_plan: bool = False,
) -> str:
    success = source_successfully_verified(trace, source)
    integrated = truth_integrated(text, truth_phrases)
    if success and integrated:
        return "N4"
    if success:
        return "N3"
    requested = any(t.get("name") == "request_fixture" and t.get("source") == source for t in trace)
    if waiver or verification_plan or requested:
        return "N2"
    if any(p.lower() in (text or "").lower() for p in truth_phrases):
        return "N1"
    return "N0"
