"""C0 Calibration runner CLI.

用法:
    # dry-run 单个 run（零 LLM，验证管线完整）
    .venv/bin/python scripts/calib/run_calib.py --dry --run CAL-01

    # dry-run 全部 30 runs（零 LLM）
    .venv/bin/python scripts/calib/run_calib.py --dry --all

    # 真实请求单个 run（需 MINIMAX_API_KEY）
    .venv/bin/python scripts/calib/run_calib.py --run CAL-01

    # before CAL-01：快照 resolved MiniMax request parameters
    .venv/bin/python scripts/calib/run_calib.py --snapshot

冻结依据: `docs/CALIBRATION-MATRIX-v1.md`（30-run 顺序，严格按 Seq 执行）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.calib.runner import execute_run, snapshot_provider, write_run_result  # noqa: E402
from scripts.calib.scorer import score_run  # noqa: E402

# 冻结矩阵（CALIBRATION-MATRIX-v1.md）：Seq → (run_id, seed, variant)
FROZEN_MATRIX: list[tuple[str, str, str]] = [
    ("CAL-01", "S01", "V1-Contract"),
    ("CAL-02", "S01", "V2-Full"),
    ("CAL-03", "S01", "V0-Baseline"),
    ("CAL-04", "S02", "V1-Contract"),
    ("CAL-05", "S02", "V2-Full"),
    ("CAL-06", "S02", "V0-Baseline"),
    ("CAL-07", "S03", "V1-Contract"),
    ("CAL-08", "S03", "V2-Full"),
    ("CAL-09", "S03", "V0-Baseline"),
    ("CAL-10", "S04", "V0-Baseline"),
    ("CAL-11", "S04", "V1-Contract"),
    ("CAL-12", "S04", "V2-Full"),
    ("CAL-13", "S05", "V0-Baseline"),
    ("CAL-14", "S05", "V1-Contract"),
    ("CAL-15", "S05", "V2-Full"),
    ("CAL-16", "S06", "V1-Contract"),
    ("CAL-17", "S06", "V2-Full"),
    ("CAL-18", "S06", "V0-Baseline"),
    ("CAL-19", "S07", "V0-Baseline"),
    ("CAL-20", "S07", "V2-Full"),
    ("CAL-21", "S07", "V1-Contract"),
    ("CAL-22", "S08", "V0-Baseline"),
    ("CAL-23", "S08", "V2-Full"),
    ("CAL-24", "S08", "V1-Contract"),
    ("CAL-25", "S09", "V1-Contract"),
    ("CAL-26", "S09", "V0-Baseline"),
    ("CAL-27", "S09", "V2-Full"),
    ("CAL-28", "S10", "V1-Contract"),
    ("CAL-29", "S10", "V0-Baseline"),
    ("CAL-30", "S10", "V2-Full"),
]

MATRIX_BY_RUN = {run_id: (seed, variant) for run_id, seed, variant in FROZEN_MATRIX}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C0 Calibration runner (frozen matrix)")
    parser.add_argument("--run", type=str, default=None, help="run_id，如 CAL-01")
    parser.add_argument("--from", dest="from_run", type=str, default=None, help="从该 run 起（含）执行后续全部")
    parser.add_argument("--all", action="store_true", help="按冻结矩阵顺序执行全部 30 runs")
    parser.add_argument("--dry", action="store_true", help="dry 模式：FakeCalibLLM，零 LLM 零网络")
    parser.add_argument("--dry-mode", type=str, default="pass", choices=["pass", "fail"], help="dry 模式脚本")
    parser.add_argument("--snapshot", action="store_true", help="快照 resolved MiniMax request parameters")
    parser.add_argument("--regrade", action="store_true", help="仅用当前 scorer 重评分已有 run 结果（不重发请求）")
    parser.add_argument("--out", type=Path, default=_PROJECT_ROOT / "data" / "calib" / "runs", help="输出目录")
    args = parser.parse_args(argv)

    from llm_loop.config import load_env_file

    load_env_file()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.snapshot:
        snap = snapshot_provider(args.out)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        print(f"provider snapshot -> {args.out / 'provider_snapshot.json'}")
        return 0

    if args.regrade:
        summary = []
        for run_id, _, _ in FROZEN_MATRIX:
            path = args.out / f"{run_id}.json"
            if not path.exists():
                continue
            result = json.loads(path.read_text(encoding="utf-8"))
            result["score"] = score_run(result)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            summary.append(result["score"])
            s = result["score"]
            print(
                f"[{run_id}] regrade status={result['status']} task_success={s['task_success']} "
                f"novel={s['novel_stage']} fatal={s['fatal_behavior']} constraint={s['constraint_violation']}"
            )
        report = {
            "generated": datetime.now(UTC).isoformat(),
            "dry": False,
            "mode": "regrade",
            "count": len(summary),
            "matrix_version": "CALIBRATION-MATRIX-v1",
            "scorer_version": "v1.1",
            "runs": summary,
        }
        report_path = args.out / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report -> {report_path}")
        return 0

    if args.all:
        targets = FROZEN_MATRIX
    elif args.from_run:
        if args.from_run not in MATRIX_BY_RUN:
            print(f"未知 run_id: {args.from_run}", file=sys.stderr)
            return 2
        run_ids = [r for r, _, _ in FROZEN_MATRIX]
        targets = FROZEN_MATRIX[run_ids.index(args.from_run):]
    elif args.run:
        if args.run not in MATRIX_BY_RUN:
            print(f"未知 run_id: {args.run}", file=sys.stderr)
            return 2
        seed, variant = MATRIX_BY_RUN[args.run]
        targets = [(args.run, seed, variant)]
    else:
        print("必须指定 --run <id> 或 --all", file=sys.stderr)
        return 2

    summary = []
    for run_id, seed_id, variant in targets:
        print(f"[{run_id}] seed={seed_id} variant={variant} {'dry' if args.dry else 'real'} ...", flush=True)
        result = execute_run(
            run_id, seed_id, variant, dry=args.dry, dry_mode=args.dry_mode
        )
        score = score_run(result)
        result["score"] = score
        write_run_result(run_id, result, args.out)
        summary.append(score)
        print(
            f"  -> status={result['status']} task_success={score['task_success']} "
            f"novel={score['novel_stage']} fatal={score['fatal_behavior']} "
            f"req={score['verification_sources_requested']}"
        )

    report = {
        "generated": datetime.now(UTC).isoformat(),
        "dry": args.dry,
        "dry_mode": args.dry_mode if args.dry else None,
        "count": len(summary),
        "matrix_version": "CALIBRATION-MATRIX-v1",
        "scorer_version": "v1.1",
        "runs": summary,
    }
    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
