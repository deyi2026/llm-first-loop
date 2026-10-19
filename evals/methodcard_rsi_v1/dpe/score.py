#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读回填后的 DPE 复核表，计算 S1 门槛与评分者一致性。

用法：
  python3 dpe/score.py dpe/review_pack.csv
  python3 dpe/score.py dpe/review_pack.csv dpe/review_pack.rater2.csv   # 算 kappa
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ITEMS = ("P1", "P2", "P3", "P4", "P5")
ARMS = ("no_card", "gold_card", "filler_card")


def read_sheet(p: Path) -> dict[str, dict]:
    rows = {}
    with p.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            bid = (r.get("blind_id") or "").strip()
            if not bid:
                continue
            vals = {}
            for k in ITEMS:
                v = r.get(k)
                vals[k] = int(str(v).strip()) if str(v).strip() in ("0", "1") else None
            rows[bid] = {**vals, "note": (r.get("note") or "").strip()}
    return rows


def kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sheets = [read_sheet(Path(p)) for p in sys.argv[1:]]
    key = json.loads((HERE / "key.json").read_text(encoding="utf-8"))
    bids = [b for b in key if b in sheets[0]]
    missing = [k for k in ITEMS if any(sheets[0][b][k] is None for b in bids)]
    if missing:
        print(f"[FAIL] 未填完：{missing}；先补全再评分")
        return 1

    # 一致性
    if len(sheets) >= 2:
        for k in ITEMS:
            xs = [sheets[0][b][k] for b in bids]
            ys = [sheets[1][b][k] for b in bids]
            agree = sum(1 for x, y in zip(xs, ys) if x == y) / len(bids)
            print(f"[kappa] {k}: kappa={kappa(xs, ys):.3f} agreement={agree:.3f}")

    # case_pass
    rec = {}
    for b in bids:
        r = sheets[0][b]
        cp = all(r[k] == 1 for k in ITEMS)
        rec[b] = {"instance_id": key[b]["instance_id"], "arm": key[b]["arm"],
                  "case_pass": cp, **{k: r[k] for k in ITEMS}}
    by_arm = {a: [v for v in rec.values() if v["arm"] == a] for a in ARMS}
    for a, rs in by_arm.items():
        print(f"[arm] {a}: n={len(rs)} case_pass={sum(v['case_pass'] for v in rs)}")
    for k in ITEMS:
        print(f"[item] {k}: " + " ".join(f"{a}={sum(v[k] for v in by_arm[a])}/{len(by_arm[a])}" for a in ARMS))

    # D 集合（从 S1 冻结口径与 v1.4 都算）
    idx = {(v["instance_id"], v["arm"]): v for v in rec.values()}
    ids = sorted({v["instance_id"] for v in rec.values()})
    for name, Dset in json.loads((HERE / "d_sets.json").read_text(encoding="utf-8")).items():
        D = [i for i in Dset if (i, "no_card") in idx]
        g1 = [i for i in D if idx[(i, "gold_card")]["case_pass"]]
        kinds = set()
        for i in D:
            for k in ITEMS:
                if idx[(i, "no_card")][k] == 0 and idx[(i, "gold_card")][k] == 1:
                    kinds.add(k)
        f1 = [i for i in ids if not idx[(i, "no_card")]["case_pass"] and idx[(i, "filler_card")]["case_pass"]]
        print(f"[{name}] n={len(D)} G1={len(g1)} G2={sorted(kinds)} ({len(kinds)}) "
              f"F1={len(f1)} -> gold={'PASS' if len(g1)>=2 and len(kinds)>=2 else 'FAIL'} filler={'PASS' if not f1 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
