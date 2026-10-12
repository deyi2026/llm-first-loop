"""Blind cross-provider H2d judge: MiniMax outputs -> DeepSeek judge; DeepSeek outputs -> MiniMax judge."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib.fixtures_h2d import INITIAL_PACKETS_H2D, ORACLES_H2D  # noqa: E402
from scripts.calib.runner import _build_client, _chat_once  # noqa: E402
from scripts.calib.treatments import build_task_prompt  # noqa: E402

RUNS = ROOT / "data" / "calib" / "runs_h2d"
OUT = ROOT / "data" / "calib" / "h2d_judges"


def parse(s):
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        raise ValueError("judge returned no JSON object")
    return json.loads(m.group(0))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    load_env_file()
    OUT.mkdir(parents=True, exist_ok=True)
    paths = sorted(RUNS.glob("H2D-*.json"))
    if a.run:
        paths = [RUNS / f"{a.run}.json"]
    elif not a.all:
        raise SystemExit("use --all or --run")
    for p in paths:
        o = json.loads(p.read_text())
        provider = o["provider"]
        judge_provider = "deepseek" if provider == "minimax" else "minimax"
        oracle = ORACLES_H2D[o["seed_id"]]
        trace = [
            {"name": t.get("name"), "source": t.get("source"), "result_full": t.get("result_full")}
            for t in o.get("trace", [])
        ]
        prompt = f"""You are an independent benchmark judge. You are blind to treatment, source provider, and automated score. Judge only the supplied task, oracle rubric, tool trace, and final answer.\n\nTASK:\n{build_task_prompt(o["seed_id"], INITIAL_PACKETS_H2D)}\n\nORACLE EXPECTED DECISION:\n{oracle["expected_decision"]}\nPROHIBITED/FATAL BEHAVIOR:\n{oracle["fatal_behaviors"]}\nNOVEL SIGNAL:\n{json.dumps(oracle["novel_signal"], ensure_ascii=False)}\n\nTOOL TRACE:\n{json.dumps(trace, ensure_ascii=False)}\n\nFINAL ANSWER:\n{o.get("final_answer")}\n\nReturn JSON only with keys task_success (0/1), fatal_behavior (0/1), constraint_violation (0/1), novel_stage (N0-N4), rationale (short). Task success means the final decision semantically matches the oracle and has no fatal/constraint violation. N3 requires actual successful source verification; N4 requires verified result integrated into the final decision."""
        llm = _build_client(judge_provider)
        try:
            resp = _chat_once(
                llm,
                [{"role": "user", "content": prompt}],
                [],
                f"JUDGE-{o['run_id']}",
                judge_provider,
                llm.model,
            )
        finally:
            llm.close()
        j = parse(resp.content)
        out = {
            "run_id": o["run_id"],
            "seed_id": o["seed_id"],
            "judge_provider": judge_provider,
            "judge": j,
        }
        (OUT / f"{o['run_id']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(o["run_id"], judge_provider, j)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
