"""A1 component-ablation generation runner. Semantic scoring is separate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from llm_loop.config import load_env_file  # noqa: E402
from scripts.calib import fixtures_a1 as f  # noqa: E402
from scripts.calib.runner_a1 import execute_run_a1  # noqa: E402

MATRIX = ROOT / "tests/fixtures/calib/a1_matrix_v1.json"
OUT = ROOT / "data/calib/runs_a1"


class Data:
    ORACLES = f.ORACLES_A1
    SOURCES = f.SOURCES_A1
    INITIAL_PACKETS = f.INITIAL_PACKETS_A1
    SOURCE_LIMIT = f.SOURCE_LIMIT_A1
    UNAVAILABLE_RESPONSE = f.UNAVAILABLE_RESPONSE_A1
    LIMIT_EXCEEDED_RESPONSE = f.LIMIT_EXCEEDED_RESPONSE_A1

    @staticmethod
    def lookup_source(seed, source):
        return f.lookup_source_a1(seed, source)


DATA = Data()


def rows():
    return json.loads(MATRIX.read_text(encoding="utf-8"))["rows"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["minimax", "deepseek"])
    ap.add_argument("--run")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--from-run")
    ap.add_argument("--count", type=int)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--execute-real", action="store_true")
    a = ap.parse_args(argv)
    load_env_file()
    OUT.mkdir(parents=True, exist_ok=True)
    rs = [r for r in rows() if not a.provider or r["provider"] == a.provider]
    if a.run:
        rs = [r for r in rs if r["run_id"] == a.run]
    elif a.from_run:
        idx = next((i for i, r in enumerate(rs) if r["run_id"] == a.from_run), None)
        if idx is None:
            raise SystemExit(f"from-run not found in selected block: {a.from_run}")
        rs = rs[idx:]
        if a.count is not None:
            rs = rs[: a.count]
    elif not a.all:
        raise SystemExit("use --all, --run, or --from-run")
    if not a.dry and not a.execute_real:
        raise SystemExit("real A1 blocked until frozen preregistration")
    for r in rs:
        print(
            f"[{r['run_id']}] {r['provider']} {r['seed']} {r['variant']} {'DRY' if a.dry else 'REAL'}",
            flush=True,
        )
        out_path = OUT / f"{r['run_id']}.json"
        if out_path.exists() and not a.dry:
            print(" -> SKIP existing raw artifact", flush=True)
            continue
        o = execute_run_a1(
            r["run_id"], r["seed"], r["variant"], dry=a.dry, provider=r["provider"], data=DATA
        )
        o["provider"] = r["provider"]
        o["matrix_block_seq"] = r["block_seq"]
        out_path.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            " ->",
            o["status"],
            "req",
            o["requested_count"],
            "lat",
            o["stats"]["latency_s"],
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
