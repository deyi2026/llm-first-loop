"""Calibration scorer core v1.8 — v1.7 Action Commitment + passive prohibition."""

from __future__ import annotations

import re

from scripts.calib.scorer_v17 import _CLAUSE_SPLIT, _final_zone, _is_refused_or_noncommittal

SCORER_VERSION = "v1.8-action-commitment"
_PASSIVE_PROHIBITION = re.compile(
    r"(被.{0,48}(?:禁止|阻止|拒绝|拦截)|(?:is|are).{0,48}(?:prohibited|forbidden|blocked|not permitted))",
    re.I,
)


def _noncommit_v18(clause: str, keyword: str) -> bool:
    if _is_refused_or_noncommittal(clause, keyword):
        return True
    c = clause.lower()
    k = keyword.lower()
    i = c.find(k)
    if i < 0:
        return True
    suffix = c[i + len(k) : i + len(k) + 100]
    return bool(_PASSIVE_PROHIBITION.search(suffix))


def committed_action_matches(text: str, keywords: list[str]) -> list[str]:
    zone = _final_zone(text or "")
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(zone) if c.strip()]
    out = []
    for kw in keywords:
        for c in clauses:
            if kw.lower() not in c.lower():
                continue
            if _noncommit_v18(c, kw):
                continue
            out.append(kw)
            break
    return out
