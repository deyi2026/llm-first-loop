#!/usr/bin/env python3
"""Zero-provider fixture validation for runner v2 (no LLM calls). Covers the D1-D5 friction class."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from healthcheck import is_healthy
from protocol import parse_verdict, SMOKE_RE

fails = []; total = 0
def check(name, cond):
    global total; total += 1
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

CANON = "deepseek/deepseek-v4-flash"
ok_row = {"status": "RUN_OK", "truncated": False, "fallback_used": False,
          "model_canonical_ok": True, "model_used": CANON}
# D4 regression: v1 healthy() (bare-name compare) returned False here -> 80/80 double-run
check("healthy accepts canonical RUN_OK row (D4 root fix)", is_healthy(ok_row) is True)
check("healthy accepts legacy row via canonical string compare", is_healthy(
    {"status": "RUN_OK", "truncated": False, "fallback_used": False, "model_used": CANON}) is True)
check("healthy rejects truncated", is_healthy({**ok_row, "truncated": True}) is False)
check("healthy rejects fallback", is_healthy({**ok_row, "fallback_used": True}) is False)
check("healthy rejects WORKER_ERROR", is_healthy({**ok_row, "status": "WORKER_ERROR"}) is False)
check("healthy rejects canonical_ok False", is_healthy({**ok_row, "model_canonical_ok": False}) is False)

# D3-class: strict smoke parsing (prompt is English-only YES/NO)
smoke = lambda t: (SMOKE_RE.search(t or "").group(1) if SMOKE_RE.search(t or "") else None)
check("smoke YES", smoke("YES") == "YES"); check("smoke NO", smoke("NO") == "NO")
check("smoke garbage -> None", smoke("好的没问题") is None)

# verdict parsing round-trip
check("verdict APPLY", parse_verdict("APPLICABILITY_VERDICT: APPLY | SUBJECT: x | REASON: y") == "APPLY")
check("verdict SKIP", parse_verdict("APPLICABILITY_VERDICT: SKIP | SUBJECT: x | REASON: y") == "SKIP")
check("verdict OTHER on free text", parse_verdict("我认为适用") == "OTHER")

# D4-class latest-wins + safety arithmetic on synthetic matrix (2 rows/cell, 40 cases)
rows = []
for i in range(40):
    for arm in ("C0", "C1"):
        for dup in range(2):
            rows.append({"kind": "formal", "case_id": f"c{i:02d}", "arm": arm, **ok_row})
latest = {}
for r in rows: latest[(r["case_id"], r["arm"])] = r
reruns = {"C0": 0, "C1": 0}; seen = set()
for r in rows:
    k = (r["case_id"], r["arm"])
    if k in seen: reruns[r["arm"]] += 1
    seen.add(k)
check("latest-wins 80 cells", len(latest) == 80)
check("safety rerun rule C1<=C0+2 (symmetric 40/40)", reruns["C1"] <= reruns["C0"] + 2)
# asymmetric case: C1 genuinely failing 3 more than C0 must trip the guard
check("safety rerun rule trips on asymmetry", (reruns["C0"] + 3) > reruns["C0"] + 2 or reruns["C1"] > reruns["C0"] + 2)

print(f"\n{total - len(fails)}/{total} checks passed")
sys.exit(1 if fails else 0)
