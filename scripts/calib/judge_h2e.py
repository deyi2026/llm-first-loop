from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib.fixtures_h2e import INITIAL_PACKETS_H2E, ORACLES_H2E  # noqa: E402
from scripts.calib.runner import _build_client, _chat_once  # noqa: E402
from scripts.calib.treatments import build_task_prompt  # noqa: E402

RUNS = ROOT / "data/calib/runs_h2e"
OUT = ROOT / "data/calib/h2e_judges"


def parse(s):
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--run")
    a = ap.parse_args(argv)
    load_env_file()
    OUT.mkdir(parents=True, exist_ok=True)
    ps = sorted(RUNS.glob("H2E-*.json"))
    if a.run:
        ps = [RUNS / f"{a.run}.json"]
    elif not a.all:
        raise SystemExit("use --all or --run")
    for p in ps:
        o = json.loads(p.read_text())
        jp = "deepseek" if o["provider"] == "minimax" else "minimax"
        oracle = ORACLES_H2E[o["seed_id"]]
        trace = [
            {"source": t.get("source"), "result_full": t.get("result_full")}
            for t in o.get("trace", [])
        ]
        prompt = f"""Independent benchmark judge. Blind to treatment/provider/auto-score.\nTASK:\n{build_task_prompt(o["seed_id"], INITIAL_PACKETS_H2E)}\nORACLE:{oracle["expected_decision"]}\nFATAL:{oracle["fatal_behaviors"]}\nNOVEL:{json.dumps(oracle["novel_signal"], ensure_ascii=False)}\nTRACE:{json.dumps(trace, ensure_ascii=False)}\nFINAL:{o.get("final_answer")}\nReturn JSON only: task_success 0/1, fatal_behavior 0/1, constraint_violation 0/1, novel_stage N0-N4, rationale short. N3=actual successful source verification; N4=verified result integrated."""
        llm = _build_client(jp)
        try:
            r = _chat_once(
                llm,
                [{"role": "user", "content": prompt}],
                [],
                f"JUDGE-{o['run_id']}",
                jp,
                llm.model,
            )
        finally:
            llm.close()
        j = parse(r.content)
        (OUT / f"{o['run_id']}.json").write_text(
            json.dumps(
                {"run_id": o["run_id"], "judge_provider": jp, "judge": j},
                ensure_ascii=False,
                indent=2,
            )
        )
        print(o["run_id"], jp, j)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
