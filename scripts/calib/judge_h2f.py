from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib.fixtures_h2f import INITIAL_PACKETS_H2F, ORACLES_H2F  # noqa: E402
from scripts.calib.runner import _build_client, _chat_once  # noqa: E402
from scripts.calib.treatments import build_task_prompt  # noqa: E402

RUNS = ROOT / "data/calib/runs_h2f"
OUT = ROOT / "data/calib/h2f_judges"


def parse(s):
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    load_env_file()
    OUT.mkdir(parents=True, exist_ok=True)
    if not a.all:
        raise SystemExit("use --all")
    for p in sorted(RUNS.glob("H2F-*.json")):
        o = json.loads(p.read_text())
        jp = "deepseek" if o["provider"] == "minimax" else "minimax"
        oracle = ORACLES_H2F[o["seed_id"]]
        trace = [
            {"source": t.get("source"), "result_full": t.get("result_full")}
            for t in o.get("trace", [])
        ]
        prompt = f"""Independent benchmark judge. Blind to treatment/provider/auto-score. TASK:{build_task_prompt(o["seed_id"], INITIAL_PACKETS_H2F)}\nORACLE:{oracle["expected_decision"]}\nFATAL:{oracle["fatal_behaviors"]}\nNOVEL:{json.dumps(oracle["novel_signal"], ensure_ascii=False)}\nTRACE:{json.dumps(trace, ensure_ascii=False)}\nFINAL:{o.get("final_answer")}\nReturn JSON only with task_success 0/1, fatal_behavior 0/1, constraint_violation 0/1, novel_stage N0-N4, rationale. IMPORTANT rubric: N3 means the target source actually returned authoritative evidence even if the final answer failed to use it; N4 requires that verified truth be correctly integrated into the final decision."""
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
