#!/usr/bin/env python3
"""v2 描述性汇总：原卡（M0）/ A 臂 / B 臂 三方对比 + 协议计数。

不出 D1–D4 裁决（PREREG-b 偏离 #8 已声明）。只做机械汇总。
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_harness as H  # noqa: E402
import grade_holdout as G  # noqa: E402


def load(p: Path) -> dict:
    return H.load_calls(p)


def main() -> int:
    cases, _ = G.load_cases()
    byid = {c["id"]: c for c in cases}
    mc = load(H.OUT / "manipcheck" / "calls.jsonl")
    rn = load(H.OUT / "run" / "calls.jsonl")

    rows = {}
    for k, r in mc.items():
        if r.get("cond") != "orig_card":
            continue
        g = H._grade_batch(r, byid)
        rows.setdefault(r["pair_id"], {})["orig"] = (g["checks_pass"], g["checks_total"],
                                                     g["q_pass"], g["q_total"])
    for k, r in rn.items():
        if r.get("phase") != "solve":
            continue
        g = H._grade_batch(r, byid)
        rows.setdefault(r["pair_id"], {})[r["arm"]] = (g["checks_pass"], g["checks_total"],
                                                       g["q_pass"], g["q_total"])

    out = {"pairs": {}, "summary": {}}
    dAB, dAorig, dBorig = [], [], []
    for pid in sorted(rows):
        v = rows[pid]
        rec = {}
        for cond in ("orig", "mutator", "human_equivalent"):
            if cond in v:
                cp, ct, qp, qt = v[cond]
                rec[cond] = {"checks": f"{cp}/{ct}", "rate": round(cp / ct, 3),
                             "q": f"{qp}/{qt}"}
        if "mutator" in v and "human_equivalent" in v:
            dAB.append(v["mutator"][0] / v["mutator"][1] - v["human_equivalent"][0] / v["human_equivalent"][1])
            rec["dA_minus_B"] = round(dAB[-1], 3)
        if "orig" in v and "mutator" in v:
            dAorig.append(v["mutator"][0] / v["mutator"][1] - v["orig"][0] / v["orig"][1])
            rec["dA_minus_orig"] = round(dAorig[-1], 3)
        if "orig" in v and "human_equivalent" in v:
            dBorig.append(v["human_equivalent"][0] / v["human_equivalent"][1] - v["orig"][0] / v["orig"][1])
            rec["dB_minus_orig"] = round(dBorig[-1], 3)
        out["pairs"][pid] = rec

    def ci(xs):
        if len(xs) < 2:
            return [None, None]
        mu = statistics.fmean(xs)
        sd = statistics.stdev(xs)
        half = 1.96 * sd / (len(xs) ** 0.5)
        return [round(mu - half, 3), round(mu + half, 3)]

    out["summary"] = {
        "n_pairs_AB": len(dAB),
        "dA_minus_B": {"mean": round(statistics.fmean(dAB), 3) if dAB else None, "ci95": ci(dAB)},
        "dA_minus_orig": {"mean": round(statistics.fmean(dAorig), 3) if dAorig else None, "ci95": ci(dAorig)},
        "dB_minus_orig": {"mean": round(statistics.fmean(dBorig), 3) if dBorig else None, "ci95": ci(dBorig)},
    }
    rw = [r for r in rn.values() if r.get("phase") == "rewrite" and r.get("ok")]
    out["protocol"] = {
        "rewrites_ok": len(rw),
        "rewrites_no_change": sum(1 for r in rw if r.get("no_change")),
        "arm_a_violations": sum(len(r.get("violations") or []) for r in rw),
        "arm_a_pairs_with_violation": sum(1 for r in rw if r.get("violations")),
        "frontmatter_changed": sum(1 for r in rw if r.get("frontmatter_changed")),
        "chars_orig_vs_A": None,
    }
    (H.OUT / "descriptive.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
