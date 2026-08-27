"""A2 semantic judging under frozen Measurement v2.1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib.fixtures_a2 import INITIAL_PACKETS_A2, ORACLES_A2  # noqa: E402
from scripts.calib.semantic_judge_v21 import derive_core_score, judge_case  # noqa: E402
from scripts.calib.treatments import build_task_prompt  # noqa: E402

RUNS = ROOT / "data/calib/runs_a2"
JDIR = ROOT / "data/calib/a2_judges"
MATRIX = ROOT / "data/calib/a2_matrix_v1.json"
REPORT = ROOT / "data/calib/a2_report.json"


def case_for(o):
    q = ORACLES_A2[o["seed_id"]]
    return {
        "task": build_task_prompt(o["seed_id"], INITIAL_PACKETS_A2),
        "oracle_expected_decision": q["expected_decision"],
        "prohibited_behavior": q["prohibited_behavior"],
        "novel_signal": q["novel_signal"],
        "trace": [
            {
                "round": t.get("round"),
                "source": t.get("source"),
                "result_full": t.get("result_full"),
            }
            for t in o.get("trace", [])
        ],
        "final_answer": o.get("final_answer"),
    }


def do_judge(o, provider, case):
    p = JDIR / f"{o['run_id']}-{provider}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))["judge"]
    j = judge_case(case, provider, f"A2-JUDGE-{provider}-{o['run_id']}")
    p.write_text(
        json.dumps(
            {"run_id": o["run_id"], "judge_provider": provider, "judge": j},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return j


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if not a.all:
        raise SystemExit("use --all")
    load_env_file()
    JDIR.mkdir(parents=True, exist_ok=True)
    mx = json.loads(MATRIX.read_text(encoding="utf-8"))
    pre = set(mx["secondary_review_runs"])
    rows = []
    for p in sorted(RUNS.glob("A2-*.json")):
        o = json.loads(p.read_text(encoding="utf-8"))
        case = case_for(o)
        primary = "deepseek" if o["provider"] == "minimax" else "minimax"
        pj = do_judge(o, primary, case)
        ps = derive_core_score(case, pj, o["status"])
        mandatory = (
            o["status"] != "COMPLETED"
            or ps["task_success"] == 0
            or ps["fatal_behavior"] == 1
            or ps["novel_stage"] != "N4"
        )
        need = o["run_id"] in pre or mandatory
        secondary = None
        ss = None
        agree = None
        abstain = False
        if need:
            secondary = o["provider"]
            sj = do_judge(o, secondary, case)
            ss = derive_core_score(case, sj, o["status"])
            agree = all(
                pj[k] == sj[k]
                for k in [
                    "decision_matches_oracle",
                    "commits_prohibited_action",
                    "verified_truth_integrated",
                ]
            ) and all(
                ps[k] == ss[k]
                for k in ["task_success", "fatal_behavior", "constraint_violation", "novel_stage"]
            )
            abstain = not agree
        row = {
            "run_id": o["run_id"],
            "seed_id": o["seed_id"],
            "generation_provider": o["provider"],
            "variant": o["variant"],
            "primary_judge": primary,
            "primary_semantic": pj,
            "primary_score": ps,
            "secondary_judge": secondary,
            "secondary_score": ss,
            "judge_agree": agree,
            "abstain": abstain,
            "final_score": None if abstain else ps,
            "mandatory_secondary": mandatory,
            "preselected_secondary": o["run_id"] in pre,
        }
        rows.append(row)
        print(
            o["run_id"],
            o["provider"],
            o["variant"],
            "task",
            ps["task_success"],
            "novel",
            ps["novel_stage"],
            "secondary",
            need,
            "agree",
            agree,
            flush=True,
        )
    report = {
        "count": len(rows),
        "abstain_count": sum(r["abstain"] for r in rows),
        "secondary_count": sum(r["secondary_judge"] is not None for r in rows),
        "secondary_agreement_count": sum(r["judge_agree"] is True for r in rows),
        "rows": rows,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ["count", "abstain_count", "secondary_count", "secondary_agreement_count"]
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
