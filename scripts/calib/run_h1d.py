"""H1d balanced Action Commitment control-bank validator (offline only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.calib.scorer_v17 import SCORER_VERSION, committed_action_matches  # noqa: E402

DEFAULT_BANK = ROOT / "data" / "calib" / "h1d_control_bank.json"
DEFAULT_REPORT = ROOT / "data" / "calib" / "h1d_report.json"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    a = ap.parse_args(argv)
    bank = json.loads(a.bank.read_text(encoding="utf-8"))
    rows = []
    for c in bank["controls"]:
        pred = int(bool(committed_action_matches(c["text"], [c["keyword"]])))
        rows.append({**c, "pred_commit": pred, "match": pred == c["gold_commit"]})
    tp = sum(r["gold_commit"] == 1 and r["pred_commit"] == 1 for r in rows)
    tn = sum(r["gold_commit"] == 0 and r["pred_commit"] == 0 for r in rows)
    fp = sum(r["gold_commit"] == 0 and r["pred_commit"] == 1 for r in rows)
    fn = sum(r["gold_commit"] == 1 and r["pred_commit"] == 0 for r in rows)
    sens = tp / (tp + fn) if tp + fn else None
    spec = tn / (tn + fp) if tn + fp else None
    per_class = {}
    for cls in sorted({r["class"] for r in rows}):
        rr = [r for r in rows if r["class"] == cls]
        per_class[cls] = {"n": len(rr), "correct": sum(x["match"] for x in rr)}
    passed = sens == 1.0 and spec == 1.0 and all(v["correct"] == v["n"] for v in per_class.values())
    report = {
        "scorer_version": SCORER_VERSION,
        "count": len(rows),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "sensitivity": sens,
        "specificity": spec,
        "per_class": per_class,
        "overall_pass": passed,
        "mismatches": [r for r in rows if not r["match"]],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
