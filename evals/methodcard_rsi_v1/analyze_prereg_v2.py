#!/usr/bin/env python3
"""v2（agent 执行）裁决器：只读 report.json，按 PREREG-...b §4 判 D1–D4。

配对不齐 → 拒跑（退出 3），不删点。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analyze_prereg import _bootstrap_ci, _sign_test_p  # noqa: E402

EXPECTED_PAIRS = 23
SEED = 20261019


def decide(lo: float, hi: float, token_ratio: float) -> str:
    if lo >= -0.05 and token_ratio <= 1.00:
        return "D1_SHIP_L1_AGENT_DEFAULT"
    if lo > 0.05 and token_ratio <= 1.10:
        return "D2_ADOPT_IF_BETTER"
    if hi < -0.05:
        return "D3_REJECT"
    return "D4_INCONCLUSIVE"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, default=HERE / "results_v2" / "run" / "report.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rep = json.loads(args.report.read_text(encoding="utf-8"))
    by_pair: dict[str, dict] = {}
    for r in rep["rows"]:
        by_pair.setdefault(r["pair_id"], {})[r["arm"]] = r
    complete = {p: v for p, v in by_pair.items()
                if "mutator" in v and "human_equivalent" in v}
    if len(complete) != EXPECTED_PAIRS:
        print(f"[REFUSE] 配对完整 {len(complete)}/{EXPECTED_PAIRS}；缺对 {sorted(set(by_pair)-set(complete))}",
              file=sys.stderr)
        return 3

    d_checks, d_q = [], []
    for p in sorted(complete):
        a, b = complete[p]["mutator"], complete[p]["human_equivalent"]
        d_checks.append(a["passed"] / a["total"] - b["passed"] / b["total"])
        d_q.append(a["question_passed"] / a["question_total"]
                   - b["question_passed"] / b["question_total"])

    lo, hi = _bootstrap_ci(d_checks, SEED)
    alo, ahi = _bootstrap_ci(d_q, SEED)
    rw_a = [complete[p]["mutator"]["rewrite_tokens"] for p in complete
            if complete[p]["mutator"].get("rewrite_tokens")]
    rw_b = [complete[p]["human_equivalent"]["rewrite_tokens"] for p in complete
            if complete[p]["human_equivalent"].get("rewrite_tokens")]
    token_ratio = (statistics.median(rw_a) / statistics.median(rw_b)) if rw_a and rw_b else float("nan")
    verdict = decide(lo, hi, token_ratio)
    viol = sum(complete[p]["mutator"].get("violations") or 0 for p in complete)
    fm = sum(1 for p in complete if complete[p]["mutator"].get("frontmatter_changed"))

    out = {
        "pairs": len(complete), "seed": SEED,
        "primary_check_delta": {"mean": round(statistics.fmean(d_checks), 4),
                                "ci95": [round(lo, 4), round(hi, 4)],
                                "sign_test_p": round(_sign_test_p(d_checks), 4),
                                "n_pos": sum(1 for d in d_checks if d > 0),
                                "n_neg": sum(1 for d in d_checks if d < 0),
                                "n_zero": sum(1 for d in d_checks if d == 0)},
        "secondary_question_delta": {"mean": round(statistics.fmean(d_q), 4),
                                     "ci95": [round(alo, 4), round(ahi, 4)],
                                     "sign_test_p": round(_sign_test_p(d_q), 4)},
        "cost": {"median_rewrite_tokens_A": statistics.median(rw_a) if rw_a else None,
                 "median_rewrite_tokens_B": statistics.median(rw_b) if rw_b else None,
                 "token_ratio_A_over_B": round(token_ratio, 4)},
        "protocol": {"arm_a_violations_total": viol, "arm_a_frontmatter_changed": fm},
        "verdict": verdict,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"pairs={out['pairs']}  verdict={verdict}")
        p = out["primary_check_delta"]
        print(f"  主端点 check Δ={p['mean']:+.3f}  CI95=[{p['ci95'][0]:+.3f},{p['ci95'][1]:+.3f}]"
              f"  符号检验 p={p['sign_test_p']}  (+{p['n_pos']}/-{p['n_neg']}/0:{p['n_zero']})")
        s = out["secondary_question_delta"]
        print(f"  次端点 题级 Δ={s['mean']:+.3f}  CI95=[{s['ci95'][0]:+.3f},{s['ci95'][1]:+.3f}]"
              f"  p={s['sign_test_p']}")
        c = out["cost"]
        print(f"  改写 token 中位 A={c['median_rewrite_tokens_A']:.0f} B={c['median_rewrite_tokens_B']:.0f}"
              f"  比={c['token_ratio_A_over_B']}")
        print(f"  协议 violation={viol}  frontmatter 变更={fm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
