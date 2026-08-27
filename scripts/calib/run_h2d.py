"""H2d dual-anchor real holdout runner. Real requests require --execute-real."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib import fixtures_h2d as f  # noqa: E402
from scripts.calib.h2d_scorer import score_run_h2d  # noqa: E402
from scripts.calib.runner import execute_run  # noqa: E402

MATRIX = ROOT / "data" / "calib" / "h2d_matrix_v1.json"
OUT = ROOT / "data" / "calib" / "runs_h2d"


class Data:
    ORACLES = f.ORACLES_H2D
    SOURCES = f.SOURCES_H2D
    INITIAL_PACKETS = f.INITIAL_PACKETS_H2D
    SOURCE_LIMIT = f.SOURCE_LIMIT_H2D
    UNAVAILABLE_RESPONSE = f.UNAVAILABLE_RESPONSE_H2D
    LIMIT_EXCEEDED_RESPONSE = f.LIMIT_EXCEEDED_RESPONSE_H2D

    @staticmethod
    def lookup_source(seed_id, source):
        return f.lookup_source_h2d(seed_id, source)


DATA = Data()


def rows():
    return json.loads(MATRIX.read_text(encoding="utf-8"))["rows"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["minimax", "deepseek"])
    ap.add_argument("--run")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--execute-real", action="store_true")
    ap.add_argument("--regrade", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    load_env_file()
    a.out.mkdir(parents=True, exist_ok=True)
    selected = [r for r in rows() if not a.provider or r["provider"] == a.provider]
    if a.regrade:
        ss = []
        for r in selected:
            p = a.out / f"{r['run_id']}.json"
            if not p.exists():
                continue
            o = json.loads(p.read_text())
            o["score"] = score_run_h2d(o)
            p.write_text(json.dumps(o, ensure_ascii=False, indent=2))
            ss.append(o["score"])
        (a.out / f"report_{a.provider or 'all'}.json").write_text(
            json.dumps(
                {"generated": datetime.now(UTC).isoformat(), "count": len(ss), "runs": ss},
                ensure_ascii=False,
                indent=2,
            )
        )
        print("regraded", len(ss))
        return 0
    if a.run:
        selected = [r for r in selected if r["run_id"] == a.run]
        if not selected:
            raise SystemExit("unknown run")
    elif not a.all:
        raise SystemExit("use --all or --run")
    if not a.dry and not a.execute_real:
        raise SystemExit("real H2d blocked: use --execute-real")
    for r in selected:
        print(
            f"[{r['run_id']}] {r['provider']} {r['seed']} {r['variant']} {'DRY' if a.dry else 'REAL'}",
            flush=True,
        )
        o = execute_run(
            r["run_id"], r["seed"], r["variant"], dry=a.dry, provider=r["provider"], data=DATA
        )
        o["provider"] = r["provider"]
        o["score"] = score_run_h2d(o)
        (a.out / f"{r['run_id']}.json").write_text(json.dumps(o, ensure_ascii=False, indent=2))
        s = o["score"]
        print(
            " ->",
            o["status"],
            "task",
            s["task_success"],
            "fatal",
            s["fatal_behavior"],
            "novel",
            s["novel_stage"],
            "unnec",
            s["unnecessary_verification_count"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
