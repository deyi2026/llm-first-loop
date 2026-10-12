from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.calib.scorer_v18 import SCORER_VERSION, committed_action_matches  # noqa: E402

BANK = ROOT / "data/calib/h1e_control_bank.json"
REPORT = ROOT / "data/calib/h1e_report.json"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=Path, default=BANK)
    ap.add_argument("--out", type=Path, default=REPORT)
    a = ap.parse_args(argv)
    b = json.loads(a.bank.read_text())
    rows = []
    for c in b["controls"]:
        pred = int(bool(committed_action_matches(c["text"], [c["keyword"]])))
        rows.append({**c, "pred": pred, "match": pred == c["gold_commit"]})
    tp = sum(r["gold_commit"] == 1 and r["pred"] == 1 for r in rows)
    tn = sum(r["gold_commit"] == 0 and r["pred"] == 0 for r in rows)
    fp = sum(r["gold_commit"] == 0 and r["pred"] == 1 for r in rows)
    fn = sum(r["gold_commit"] == 1 and r["pred"] == 0 for r in rows)
    per = {}
    for cls in sorted({r["class"] for r in rows}):
        rr = [r for r in rows if r["class"] == cls]
        per[cls] = {"n": len(rr), "correct": sum(x["match"] for x in rr)}
    sens = tp / (tp + fn)
    spec = tn / (tn + fp)
    ok = sens == 1 and spec == 1 and all(v["n"] == v["correct"] for v in per.values())
    rep = {
        "scorer_version": SCORER_VERSION,
        "count": len(rows),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "sensitivity": sens,
        "specificity": spec,
        "per_class": per,
        "overall_pass": ok,
        "mismatches": [r for r in rows if not r["match"]],
    }
    a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
