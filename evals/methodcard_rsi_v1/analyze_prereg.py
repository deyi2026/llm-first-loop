#!/usr/bin/env python3
"""预注册分析（先写规则，后跑数据）。

输入 results.jsonl，每行：
  {"pair_id":"P01","arm":"mutator","passed":14,"total":20,"minutes":6.5,"tokens":21000}
每对必须同时有 mutator 与 human 两行，缺一即拒跑（不允许删点后重算）。

预注册判据（docs/PREREG-20261019-methodcard-mutation-pairwise.md §5）：
  D1 SHIP_AS_DEFAULT   95% bootstrap CI 下界 >= -0.05 且 中位人工分钟数比 <= 0.5
  D2 ADOPT_IF_BETTER   CI 下界 > 0.05 且 中位人工分钟数比 <= 1.0
  D3 REJECT            CI 上界 < -0.05
  D4 INCONCLUSIVE      其余
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path

BOOTSTRAP_N = 10000
CI = 0.95


def _sign_test_p(deltas: list[float]) -> float:
    pos = sum(1 for d in deltas if d > 0)
    neg = sum(1 for d in deltas if d < 0)
    n = pos + neg
    if n == 0:
        return 1.0
    # 双侧精确二项
    k = min(pos, neg)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _bootstrap_ci(deltas: list[float], seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(deltas)
    means = []
    for _ in range(BOOTSTRAP_N):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((1 - CI) / 2 * BOOTSTRAP_N)]
    hi = means[int((1 + CI) / 2 * BOOTSTRAP_N) - 1]
    return lo, hi


def decide(delta_ci_lo: float, delta_ci_hi: float, minute_ratio: float) -> str:
    if delta_ci_lo >= -0.05 and minute_ratio <= 0.5:
        return "SHIP_AS_DEFAULT"
    if delta_ci_lo > 0.05 and minute_ratio <= 1.0:
        return "ADOPT_IF_BETTER"
    if delta_ci_hi < -0.05:
        return "REJECT"
    return "INCONCLUSIVE"


def analyze(rows: list[dict], seed: int) -> dict:
    by_pair: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_pair.setdefault(r["pair_id"], {})[r["arm"]] = r
    incomplete = [p for p, a in by_pair.items() if set(a) != {"mutator", "human"}]
    if incomplete:
        raise SystemExit(f"配对不完整，拒绝分析（不允许删点）：{sorted(incomplete)[:5]}")

    deltas, m_min, h_min = [], [], []
    for pid in sorted(by_pair):
        m, h = by_pair[pid]["mutator"], by_pair[pid]["human"]
        deltas.append(m["passed"] / m["total"] - h["passed"] / h["total"])
        m_min.append(float(m.get("minutes", 0)))
        h_min.append(float(h.get("minutes", 0)))

    lo, hi = _bootstrap_ci(deltas, seed)
    ratio = (statistics.median(m_min) / statistics.median(h_min)) if statistics.median(h_min) > 0 else float("inf")
    return {
        "pairs": len(deltas),
        "mean_delta": sum(deltas) / len(deltas),
        "ci95": [lo, hi],
        "sign_test_p": _sign_test_p(deltas),
        "median_minutes": {"mutator": statistics.median(m_min), "human": statistics.median(h_min)},
        "minute_ratio": ratio,
        "decision": decide(lo, hi, ratio),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = [json.loads(l) for l in args.results.read_text(encoding="utf-8").splitlines() if l.strip()]
    res = analyze(rows, args.seed)
    print(json.dumps(res, ensure_ascii=False, indent=2) if args.json else
          f"n={res['pairs']} delta={res['mean_delta']:+.3f} CI={res['ci95'][0]:+.3f}..{res['ci95'][1]:+.3f} "
          f"minute_ratio={res['minute_ratio']:.2f} -> {res['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
