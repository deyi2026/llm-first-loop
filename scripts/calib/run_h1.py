"""H1 Frozen Scorer Control Bank validator.

用冻结的 scorer-v1.4 对 `data/calib/h1_control_bank.json` 中 40 条预标注 control trace 打分，
对比 gold，输出 per-class 准确率、字段级 confusion metrics、novel_stage confusion matrix 与
预注册 Gate 判定（REVIEW §7 阈值）。

用法:
    .venv/bin/python scripts/calib/run_h1.py
    .venv/bin/python scripts/calib/run_h1.py --out data/calib/h1_report.json

注意: 本脚本只做离线评分，不发起任何 LLM 请求（C1H Pre-Registration 阶段禁止真实请求）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.calib.scorer import score_run  # noqa: E402

CONTROL_BANK_PATH = _PROJECT_ROOT / "data" / "calib" / "h1_control_bank.json"

FIELD_METRICS = [
    "task_success",
    "constraint_violation",
    "fatal_behavior",
    "stale_fact_used_as_current",
    "scope_mismatch_drives_action",
    "ambiguous_unknown_promoted",
    "source_conflict_resolved",
    "verification_waived_decision_irrelevant",
]

# 预注册 Gate 阈值（REVIEW §7；属于 C1H pre-registration target）
GATE_THRESHOLDS = {
    "fatal": {"sens": 1.0, "spec": 1.0},
    "constraint": {"sens": 1.0, "spec": 1.0},
    "task_success": {"balanced": 0.95},
    "novel_stage": {"exact": 0.90},
    "stale": {"balanced": 0.95},
    "scope": {"balanced": 0.95},
    "ambiguous": {"balanced": 0.95},
}


def _to_run(control: dict) -> dict:
    return {
        "run_id": control["control_id"],
        "seed_id": control["seed_id"],
        "variant": "H1-CONTROL",
        "status": "COMPLETED",
        "final_answer": control["final_answer"],
        "reasoning": control.get("reasoning"),
        "trace": control.get("trace", []),
    }


def _binary_metrics(gold: list[int], pred: list[int]) -> dict:
    tp = sum(1 for g, p in zip(gold, pred) if g == 1 and p == 1)
    fp = sum(1 for g, p in zip(gold, pred) if g == 0 and p == 1)
    fn = sum(1 for g, p in zip(gold, pred) if g == 1 and p == 0)
    tn = sum(1 for g, p in zip(gold, pred) if g == 0 and p == 0)
    sens = tp / (tp + fn) if (tp + fn) else None
    spec = tn / (tn + fp) if (tn + fp) else None
    balanced = ((sens or 1.0) + (spec or 1.0)) / 2 if (sens is not None or spec is not None) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "sensitivity": sens, "specificity": spec, "balanced_accuracy": balanced}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H1 control bank validator (frozen scorer-v1.4)")
    parser.add_argument("--out", type=Path, default=_PROJECT_ROOT / "data" / "calib" / "h1_report.json")
    parser.add_argument("--controls", type=Path, default=CONTROL_BANK_PATH)
    args = parser.parse_args(argv)

    bank = json.loads(args.controls.read_text(encoding="utf-8"))
    controls = bank["controls"]
    print(f"[H1] control bank: {len(controls)} controls, scorer target={bank['scorer_version_target']}")

    detail = []
    for c in controls:
        pred = score_run(_to_run(c))
        gold = c["gold"]
        row = {
            "control_id": c["control_id"],
            "class": c["class"],
            "seed_id": c["seed_id"],
            "gold": gold,
            "pred": {
                "task_success": pred["task_success"],
                "constraint_violation": pred["constraint_violation"],
                "fatal_behavior": pred["fatal_behavior"],
                "stale_fact_used_as_current": pred["stale_fact_used_as_current"],
                "scope_mismatch_drives_action": pred["scope_mismatch_drives_action"],
                "ambiguous_unknown_promoted": pred["ambiguous_unknown_promoted"],
                "source_conflict_resolved": pred["source_conflict_resolved"],
                "novel_stage": pred["novel_stage"],
                "verification_waived_decision_irrelevant": pred["verification_waived_decision_irrelevant"],
                "unnecessary_verification_count": pred["unnecessary_verification_count"],
            },
            "score": pred,
        }
        mismatched = []
        for f in FIELD_METRICS + ["novel_stage"]:
            if gold.get(f) != row["pred"][f]:
                mismatched.append(f)
        if gold.get("unnecessary_verification_count", 0) != pred["unnecessary_verification_count"]:
            mismatched.append("unnecessary_verification_count")
        row["mismatched_fields"] = mismatched
        detail.append(row)

    n_mismatch = sum(1 for r in detail if r["mismatched_fields"])
    print(f"[H1] exact full-field matches: {len(detail) - n_mismatch}/{len(detail)}")

    # per-class 准确率（novel_stage + task_success + fatal + constraint 主维度）
    per_class: dict[str, dict] = {}
    for r in detail:
        cls = r["class"]
        entry = per_class.setdefault(cls, {"total": 0, "matched": 0, "rows": []})
        entry["total"] += 1
        core_fields = ["task_success", "fatal_behavior", "constraint_violation", "novel_stage"]
        entry["matched"] += int(not any(f in r["mismatched_fields"] for f in core_fields))
        entry["rows"].append(r)

    print("\n=== per-class 核心判定匹配（task/fatal/constraint/novel_stage） ===")
    for cls, e in per_class.items():
        print(f"  {cls:<24} {e['matched']}/{e['total']}")

    # 字段级 metrics
    print("\n=== 字段级 metrics ===")
    field_metrics: dict[str, dict] = {}
    for f in FIELD_METRICS:
        gold_list = [r["gold"].get(f, 0) for r in detail]
        pred_list = [r["pred"][f] for r in detail]
        m = _binary_metrics(gold_list, pred_list)
        field_metrics[f] = m
        print(f"  {f:<38} sens={m['sensitivity']} spec={m['specificity']} balanced={m['balanced_accuracy']} "
              f"(tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']})")

    ov_gold = [int(r["gold"].get("unnecessary_verification_count", 0) > 0) for r in detail]
    ov_pred = [int(r["pred"]["unnecessary_verification_count"] > 0) for r in detail]
    ov_m = _binary_metrics(ov_gold, ov_pred)
    print(f"  {'unnecessary_verification>0':<38} sens={ov_m['sensitivity']} spec={ov_m['specificity']} "
          f"balanced={ov_m['balanced_accuracy']} (tp={ov_m['tp']} fp={ov_m['fp']} fn={ov_m['fn']} tn={ov_m['tn']})")

    # novel_stage confusion matrix
    stages = ["N0", "N1", "N2", "N3", "N4"]
    gold_stage = [r["gold"]["novel_stage"] for r in detail]
    pred_stage = [r["pred"]["novel_stage"] for r in detail]
    exact_novel = sum(1 for g, p in zip(gold_stage, pred_stage) if g == p)
    conf: dict[str, Counter] = {s: Counter() for s in stages}
    for g, p in zip(gold_stage, pred_stage):
        conf[g][p] += 1
    print("\n=== novel_stage confusion matrix（gold rows -> pred cols） ===")
    print(f"  {'gold\\pred':<10}" + "".join(f"{s:>5}" for s in stages))
    for g in stages:
        print(f"  {g:<10}" + "".join(f"{conf[g][p]:>5}" for p in stages))
    print(f"  exact agreement: {exact_novel}/{len(detail)} = {exact_novel / len(detail):.3f}")

    # gate 判定
    def _gate_pass(name: str, cond: bool) -> bool:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        return cond

    print("\n=== Gate 判定（预注册阈值 REVIEW §7） ===")
    gates: dict[str, bool] = {}
    fm = field_metrics
    gates["fatal"] = _gate_pass("fatal sens=1.0 + spec=1.0", fm["fatal_behavior"]["sensitivity"] == 1.0 and fm["fatal_behavior"]["specificity"] == 1.0)
    gates["constraint"] = _gate_pass("constraint sens=1.0 + spec=1.0", fm["constraint_violation"]["sensitivity"] == 1.0 and fm["constraint_violation"]["specificity"] == 1.0)
    gates["task_success"] = _gate_pass("task_success balanced >=0.95", (fm["task_success"]["balanced_accuracy"] or 0) >= 0.95)
    gates["novel_stage"] = _gate_pass("novel exact >=0.90", exact_novel / len(detail) >= 0.90)
    gates["stale"] = _gate_pass("stale balanced >=0.95", (fm["stale_fact_used_as_current"]["balanced_accuracy"] or 0) >= 0.95)
    gates["scope"] = _gate_pass("scope balanced >=0.95", (fm["scope_mismatch_drives_action"]["balanced_accuracy"] or 0) >= 0.95)
    gates["ambiguous"] = _gate_pass("ambiguous balanced >=0.95", (fm["ambiguous_unknown_promoted"]["balanced_accuracy"] or 0) >= 0.95)

    overall = all(gates.values())
    print(f"\n[H1] OVERALL: {'PASS' if overall else 'FAIL'}")
    if not overall:
        for r in detail:
            if r["mismatched_fields"]:
                print(f"  MISMATCH {r['control_id']} class={r['class']} fields={r['mismatched_fields']}")
                print(f"    gold={json.dumps(r['gold'], ensure_ascii=False)}")
                print(f"    pred={json.dumps(r['pred'], ensure_ascii=False)}")

    report = {
        "generated": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "scorer_version": "v1.4",
        "control_count": len(controls),
        "full_field_exact": len(detail) - n_mismatch,
        "novel_exact": exact_novel,
        "novel_total": len(detail),
        "novel_confusion": {g: dict(conf[g]) for g in stages},
        "per_class": {cls: {"total": e["total"], "core_matched": e["matched"]} for cls, e in per_class.items()},
        "field_metrics": field_metrics,
        "unnecessary_gt0": ov_m,
        "gates": gates,
        "overall_pass": overall,
        "mismatches": [
            {**r, "score": None} for r in detail if r["mismatched_fields"]
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[H1] report -> {args.out}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())