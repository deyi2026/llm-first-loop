"""H2h generation runner. No free-form semantic score is computed here."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib import fixtures_h2h as f  # noqa: E402
from scripts.calib.runner import execute_run  # noqa: E402

MATRIX = ROOT / "data/calib/h2h_matrix_v1.json"
OUT = ROOT / "data/calib/runs_h2h"


class Data:
    ORACLES = f.ORACLES_H2H
    SOURCES = f.SOURCES_H2H
    INITIAL_PACKETS = f.INITIAL_PACKETS_H2H
    SOURCE_LIMIT = f.SOURCE_LIMIT_H2H
    UNAVAILABLE_RESPONSE = f.UNAVAILABLE_RESPONSE_H2H
    LIMIT_EXCEEDED_RESPONSE = f.LIMIT_EXCEEDED_RESPONSE_H2H

    @staticmethod
    def lookup_source(seed, source):
        return f.lookup_source_h2h(seed, source)


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
    a = ap.parse_args(argv)
    load_env_file()
    OUT.mkdir(parents=True, exist_ok=True)
    rs = [r for r in rows() if not a.provider or r["provider"] == a.provider]
    if a.run:
        rs = [r for r in rs if r["run_id"] == a.run]
    elif not a.all:
        raise SystemExit("use --all or --run")
    if not a.dry and not a.execute_real:
        raise SystemExit("real H2h blocked")
    for r in rs:
        print(
            f"[{r['run_id']}] {r['provider']} {r['seed']} {r['variant']} {'DRY' if a.dry else 'REAL'}",
            flush=True,
        )
        o = execute_run(
            r["run_id"], r["seed"], r["variant"], dry=a.dry, provider=r["provider"], data=DATA
        )
        o["provider"] = r["provider"]
        o["matrix_block_seq"] = r["block_seq"]
        (OUT / f"{r['run_id']}.json").write_text(
            json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            " ->",
            o["status"],
            "requests",
            o["requested_count"],
            "latency",
            o["stats"]["latency_s"],
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
