"""C1 Calibration runner CLI（DeepSeek cross-style calibration）。

用法:
    # dry-run 单个 run（零 LLM，验证管线完整）
    .venv/bin/python scripts/calib/run_calib_c1.py --dry --run CAL-31

    # dry-run 全部 18 runs（零 LLM）
    .venv/bin/python scripts/calib/run_calib_c1.py --dry --all

    # 真实请求单个 run（需 DEEPSEEK_API_KEY）
    .venv/bin/python scripts/calib/run_calib_c1.py --run CAL-31

    # before CAL-31：快照 resolved DeepSeek request parameters
    .venv/bin/python scripts/calib/run_calib_c1.py --snapshot

冻结依据: `docs/CALIBRATION-MATRIX-C1.md`（18-run 顺序，严格按 Seq 执行）。
Reasoning-Field Policy: B（verbosity）——reasoning 写入 run 结果，scorer v1.2 读取。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.calib.runner import execute_run, snapshot_provider, write_run_result
from scripts.calib.scorer import score_run

# 冻结矩阵（CALIBRATION-MATRIX-C1.md）：Seq → (run_id, seed, variant)
FROZEN_MATRIX_C1: list[tuple[str, str, str]] = [
    ("CAL-31", "T01", "V2-Full"),
    ("CAL-32", "T01", "V1-Contract"),
    ("CAL-33", "T01", "V0-Baseline"),
    ("CAL-34", "T02", "V1-Contract"),
    ("CAL-35", "T02", "V0-Baseline"),
    ("CAL-36", "T02", "V2-Full"),
    ("CAL-37", "T03", "V0-Baseline"),
    ("CAL-38", "T03", "V2-Full"),
    ("CAL-39", "T03", "V1-Contract"),
    ("CAL-40", "T04", "V1-Contract"),
    ("CAL-41", "T04", "V2-Full"),
    ("CAL-42", "T04", "V0-Baseline"),
    ("CAL-43", "T05", "V1-Contract"),
    ("CAL-44", "T05", "V2-Full"),
    ("CAL-45", "T05", "V0-Baseline"),
    ("CAL-46", "T06", "V0-Baseline"),
    ("CAL-47", "T06", "V1-Contract"),
    ("CAL-48", "T06", "V2-Full"),
]

MATRIX_BY_RUN = {run_id: (seed, variant) for run_id, seed, variant in FROZEN_MATRIX_C1}

PROVIDER = "deepseek"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C1 Calibration runner (frozen matrix, DeepSeek)")
    parser.add_argument("--run", type=str, default=None, help="run_id，如 CAL-31")
    parser.add_argument("--from", dest="from_run", type=str, default=None, help="从该 run 起（含）执行后续全部")
    parser.add_argument("--all", action="store_true", help="按冻结矩阵顺序执行全部 18 runs")
    parser.add_argument("--dry", action="store_true", help="dry 模式：FakeCalibLLM，零 LLM 零网络")
    parser.add_argument("--dry-mode", type=str, default="pass", choices=["pass", "fail"], help="dry 模式脚本")
    parser.add_argument("--snapshot", action="store_true", help="快照 resolved DeepSeek request parameters")
    parser.add_argument("--regrade", action="store_true", help="仅用当前 scorer 重评分已有 run 结果（不重发请求）")
    parser.add_argument("--out", type=Path, default=_PROJECT_ROOT / "data" / "calib" / "runs_c1", help="输出目录")
    args = parser.parse_args(argv)

    from llm_loop.config import load_env_file

    load_env_file()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.snapshot:
        snap = snapshot_provider(args.out, provider=PROVIDER)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        print(f"provider snapshot -> {args.out / 'provider_snapshot.json'}")
        return 0

    if args.regrade:
        summary = []
        for run_id, _, _ in FROZEN_MATRIX_C1:
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
                f"novel={s['novel_stage']} fatal={s['fatal_behavior']} constraint={s['constraint_violation']} "
                f"reasoning_chars={s['reasoning_chars']} reflection={s['reasoning_reflection_count']}"
            )
        report = {
            "generated": datetime.now(UTC).isoformat(),
            "dry": False,
            "mode": "regrade",
            "count": len(summary),
            "matrix_version": "CALIBRATION-MATRIX-C1",
            "scorer_version": "v1.4",
            "reasoning_policy": "B",
            "runs": summary,
        }
        report_path = args.out / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report -> {report_path}")
        return 0

    if args.all:
        targets = FROZEN_MATRIX_C1
    elif args.from_run:
        if args.from_run not in MATRIX_BY_RUN:
            print(f"未知 run_id: {args.from_run}", file=sys.stderr)
            return 2
        run_ids = [r for r, _, _ in FROZEN_MATRIX_C1]
        targets = FROZEN_MATRIX_C1[run_ids.index(args.from_run):]
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
            run_id, seed_id, variant, dry=args.dry, dry_mode=args.dry_mode, provider=PROVIDER
        )
        score = score_run(result)
        result["score"] = score
        write_run_result(run_id, result, args.out)
        summary.append(score)
        print(
            f"  -> status={result['status']} task_success={score['task_success']} "
            f"novel={score['novel_stage']} fatal={score['fatal_behavior']} "
            f"req={score['verification_sources_requested']} reasoning_chars={score['reasoning_chars']}"
        )

    report = {
        "generated": datetime.now(UTC).isoformat(),
        "dry": args.dry,
        "dry_mode": args.dry_mode if args.dry else None,
        "count": len(summary),
        "matrix_version": "CALIBRATION-MATRIX-C1",
        "scorer_version": "v1.4",
        "reasoning_policy": "B",
        "runs": summary,
    }
    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())