"""C1H H2/H2b/H2c Calibration runner CLI（Unseen DeepSeek Real Holdout）。

用法:
    # dry-run 单个 run（零 LLM，验证管线完整）
    .venv/bin/python scripts/calib/run_calib_c1h.py --dry --run CAL-49
    .venv/bin/python scripts/calib/run_calib_c1h.py --dry --stage h2b --run CAL-73
    .venv/bin/python scripts/calib/run_calib_c1h.py --dry --stage h2c --run CAL-97

    # dry-run 全部 24 runs（零 LLM）
    .venv/bin/python scripts/calib/run_calib_c1h.py --dry --all
    .venv/bin/python scripts/calib/run_calib_c1h.py --dry --stage h2b --all
    .venv/bin/python scripts/calib/run_calib_c1h.py --dry --stage h2c --all

    # 真实请求单个 run（需 DEEPSEEK_API_KEY；需用户批准后才可执行）
    .venv/bin/python scripts/calib/run_calib_c1h.py --run CAL-49
    .venv/bin/python scripts/calib/run_calib_c1h.py --stage h2b --run CAL-73
    .venv/bin/python scripts/calib/run_calib_c1h.py --stage h2c --run CAL-97

    # 快照 resolved DeepSeek request parameters
    .venv/bin/python scripts/calib/run_calib_c1h.py --snapshot

冻结依据:
- H2: `docs/CALIBRATION-MATRIX-C1H.md`（CAL-49..CAL-72）
- H2b: `docs/CALIBRATION-MATRIX-C1H-H2B.md`（CAL-73..CAL-96）
- H2c: `docs/CALIBRATION-MATRIX-C1H-H2C.md`（CAL-97..CAL-120）
Scorer: `scripts/calib/h2_scorer.py`（v1.6-h2，H01-H24 规则；`scorer.py` v1.4 零改动）。
Reasoning-Field Policy: B（verbosity）——reasoning 写入 run 结果。
注意: 冻结阶段禁止真实请求；真实执行须用户批准且满足 FROZEN-C1H-v3。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.calib import (  # noqa: E402
    fixtures_h2,  # noqa: E402
    fixtures_h2b,  # noqa: E402
    fixtures_h2c,  # noqa: E402
)
from scripts.calib.h2_scorer import score_run_h2  # noqa: E402
from scripts.calib.runner import execute_run, snapshot_provider, write_run_result  # noqa: E402


class _H2Data:
    """数据层适配：把 fixtures_h2 暴露为 runner 期望的统一接口。"""

    ORACLES = fixtures_h2.ORACLES_H2
    SOURCES = fixtures_h2.SOURCES_H2
    INITIAL_PACKETS = fixtures_h2.INITIAL_PACKETS_H2
    SOURCE_LIMIT = fixtures_h2.SOURCE_LIMIT_H2
    UNAVAILABLE_RESPONSE = fixtures_h2.UNAVAILABLE_RESPONSE_H2
    LIMIT_EXCEEDED_RESPONSE = fixtures_h2.LIMIT_EXCEEDED_RESPONSE_H2

    @staticmethod
    def lookup_source(seed_id: str, source: str) -> str | None:
        return fixtures_h2.lookup_source_h2(seed_id, source)


class _H2BData:
    """数据层适配：把 fixtures_h2b 暴露为 runner 期望的统一接口。"""

    ORACLES = fixtures_h2b.ORACLES_H2B
    SOURCES = fixtures_h2b.SOURCES_H2B
    INITIAL_PACKETS = fixtures_h2b.INITIAL_PACKETS_H2B
    SOURCE_LIMIT = fixtures_h2b.SOURCE_LIMIT_H2B
    UNAVAILABLE_RESPONSE = fixtures_h2b.UNAVAILABLE_RESPONSE_H2B
    LIMIT_EXCEEDED_RESPONSE = fixtures_h2b.LIMIT_EXCEEDED_RESPONSE_H2B

    @staticmethod
    def lookup_source(seed_id: str, source: str) -> str | None:
        return fixtures_h2b.lookup_source_h2b(seed_id, source)


class _H2CData:
    """数据层适配：把 fixtures_h2c 暴露为 runner 期望的统一接口。"""

    ORACLES = fixtures_h2c.ORACLES_H2C
    SOURCES = fixtures_h2c.SOURCES_H2C
    INITIAL_PACKETS = fixtures_h2c.INITIAL_PACKETS_H2C
    SOURCE_LIMIT = fixtures_h2c.SOURCE_LIMIT_H2C
    UNAVAILABLE_RESPONSE = fixtures_h2c.UNAVAILABLE_RESPONSE_H2C
    LIMIT_EXCEEDED_RESPONSE = fixtures_h2c.LIMIT_EXCEEDED_RESPONSE_H2C

    @staticmethod
    def lookup_source(seed_id: str, source: str) -> str | None:
        return fixtures_h2c.lookup_source_h2c(seed_id, source)


H2_DATA = _H2Data()
H2B_DATA = _H2BData()
H2C_DATA = _H2CData()

# H2 冻结矩阵（CALIBRATION-MATRIX-C1H.md）：Seq → (run_id, seed, variant)
FROZEN_MATRIX_C1H: list[tuple[str, str, str]] = [
    ("CAL-49", "H01", "V2-Full"),
    ("CAL-50", "H01", "V1-Contract"),
    ("CAL-51", "H01", "V0-Baseline"),
    ("CAL-52", "H02", "V1-Contract"),
    ("CAL-53", "H02", "V0-Baseline"),
    ("CAL-54", "H02", "V2-Full"),
    ("CAL-55", "H03", "V0-Baseline"),
    ("CAL-56", "H03", "V2-Full"),
    ("CAL-57", "H03", "V1-Contract"),
    ("CAL-58", "H04", "V1-Contract"),
    ("CAL-59", "H04", "V2-Full"),
    ("CAL-60", "H04", "V0-Baseline"),
    ("CAL-61", "H05", "V0-Baseline"),
    ("CAL-62", "H05", "V2-Full"),
    ("CAL-63", "H05", "V1-Contract"),
    ("CAL-64", "H06", "V1-Contract"),
    ("CAL-65", "H06", "V2-Full"),
    ("CAL-66", "H06", "V0-Baseline"),
    ("CAL-67", "H07", "V0-Baseline"),
    ("CAL-68", "H07", "V1-Contract"),
    ("CAL-69", "H07", "V2-Full"),
    ("CAL-70", "H08", "V1-Contract"),
    ("CAL-71", "H08", "V2-Full"),
    ("CAL-72", "H08", "V0-Baseline"),
]

# H2b 冻结矩阵（CALIBRATION-MATRIX-C1H-H2B.md）：CAL-73..CAL-96，variant 顺序模式与 H2 一致
FROZEN_MATRIX_C1H_H2B: list[tuple[str, str, str]] = [
    ("CAL-73", "H09", "V2-Full"),
    ("CAL-74", "H09", "V1-Contract"),
    ("CAL-75", "H09", "V0-Baseline"),
    ("CAL-76", "H10", "V1-Contract"),
    ("CAL-77", "H10", "V0-Baseline"),
    ("CAL-78", "H10", "V2-Full"),
    ("CAL-79", "H11", "V0-Baseline"),
    ("CAL-80", "H11", "V2-Full"),
    ("CAL-81", "H11", "V1-Contract"),
    ("CAL-82", "H12", "V1-Contract"),
    ("CAL-83", "H12", "V2-Full"),
    ("CAL-84", "H12", "V0-Baseline"),
    ("CAL-85", "H13", "V0-Baseline"),
    ("CAL-86", "H13", "V2-Full"),
    ("CAL-87", "H13", "V1-Contract"),
    ("CAL-88", "H14", "V1-Contract"),
    ("CAL-89", "H14", "V2-Full"),
    ("CAL-90", "H14", "V0-Baseline"),
    ("CAL-91", "H15", "V0-Baseline"),
    ("CAL-92", "H15", "V1-Contract"),
    ("CAL-93", "H15", "V2-Full"),
    ("CAL-94", "H16", "V1-Contract"),
    ("CAL-95", "H16", "V2-Full"),
    ("CAL-96", "H16", "V0-Baseline"),
]

# H2c 冻结矩阵（CALIBRATION-MATRIX-C1H-H2C.md）：CAL-97..CAL-120
FROZEN_MATRIX_C1H_H2C: list[tuple[str, str, str]] = [
    ("CAL-97", "H17", "V2-Full"),
    ("CAL-98", "H17", "V1-Contract"),
    ("CAL-99", "H17", "V0-Baseline"),
    ("CAL-100", "H18", "V1-Contract"),
    ("CAL-101", "H18", "V0-Baseline"),
    ("CAL-102", "H18", "V2-Full"),
    ("CAL-103", "H19", "V0-Baseline"),
    ("CAL-104", "H19", "V2-Full"),
    ("CAL-105", "H19", "V1-Contract"),
    ("CAL-106", "H20", "V1-Contract"),
    ("CAL-107", "H20", "V2-Full"),
    ("CAL-108", "H20", "V0-Baseline"),
    ("CAL-109", "H21", "V0-Baseline"),
    ("CAL-110", "H21", "V2-Full"),
    ("CAL-111", "H21", "V1-Contract"),
    ("CAL-112", "H22", "V1-Contract"),
    ("CAL-113", "H22", "V2-Full"),
    ("CAL-114", "H22", "V0-Baseline"),
    ("CAL-115", "H23", "V0-Baseline"),
    ("CAL-116", "H23", "V1-Contract"),
    ("CAL-117", "H23", "V2-Full"),
    ("CAL-118", "H24", "V1-Contract"),
    ("CAL-119", "H24", "V2-Full"),
    ("CAL-120", "H24", "V0-Baseline"),
]

PROVIDER = "deepseek"
SCORER_VERSION = "v1.6-h2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="C1H H2/H2b/H2c calibration runner (frozen matrix, DeepSeek)"
    )
    parser.add_argument(
        "--stage",
        type=str,
        default="h2",
        choices=["h2", "h2b", "h2c"],
        help="h2=H01-H08(dev data) / h2b=H09-H16(holdout round 2) / h2c=H17-H24(holdout round 3)",
    )
    parser.add_argument("--run", type=str, default=None, help="run_id，如 CAL-49 / CAL-73 / CAL-97")
    parser.add_argument(
        "--from", dest="from_run", type=str, default=None, help="从该 run 起（含）执行后续全部"
    )
    parser.add_argument("--all", action="store_true", help="按冻结矩阵顺序执行全部 24 runs")
    parser.add_argument(
        "--dry", action="store_true", help="dry 模式：FakeCalibLLM(H2/H2b/H2c)，零 LLM 零网络"
    )
    parser.add_argument(
        "--dry-mode", type=str, default="pass", choices=["pass", "fail"], help="dry 模式脚本"
    )
    parser.add_argument(
        "--snapshot", action="store_true", help="快照 resolved DeepSeek request parameters"
    )
    parser.add_argument(
        "--regrade", action="store_true", help="仅用当前 H2/H2b/H2c scorer 重评分已有 run 结果"
    )
    parser.add_argument("--out", type=Path, default=None, help="输出目录（默认按 stage）")
    args = parser.parse_args(argv)

    if args.stage == "h2":
        data = H2_DATA
        matrix = FROZEN_MATRIX_C1H
        matrix_version = "CALIBRATION-MATRIX-C1H"
        default_out = _PROJECT_ROOT / "data" / "calib" / "runs_c1h"
    elif args.stage == "h2b":
        data = H2B_DATA
        matrix = FROZEN_MATRIX_C1H_H2B
        matrix_version = "CALIBRATION-MATRIX-C1H-H2B"
        default_out = _PROJECT_ROOT / "data" / "calib" / "runs_c1h_h2b"
    else:
        data = H2C_DATA
        matrix = FROZEN_MATRIX_C1H_H2C
        matrix_version = "CALIBRATION-MATRIX-C1H-H2C"
        default_out = _PROJECT_ROOT / "data" / "calib" / "runs_c1h_h2c"
    matrix_by_run = {run_id: (seed, variant) for run_id, seed, variant in matrix}
    out = args.out or default_out

    from llm_loop.config import load_env_file

    load_env_file()
    out.mkdir(parents=True, exist_ok=True)

    if args.snapshot:
        snap = snapshot_provider(out, provider=PROVIDER)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        print(f"provider snapshot -> {out / 'provider_snapshot.json'}")
        return 0

    if args.regrade:
        summary = []
        for run_id, _, _ in matrix:
            path = out / f"{run_id}.json"
            if not path.exists():
                continue
            result = json.loads(path.read_text(encoding="utf-8"))
            result["score"] = score_run_h2(result)
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
            "stage": args.stage,
            "count": len(summary),
            "matrix_version": matrix_version,
            "scorer_version": SCORER_VERSION,
            "reasoning_policy": "B",
            "runs": summary,
        }
        report_path = out / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report -> {report_path}")
        return 0

    if args.all:
        targets = matrix
    elif args.from_run:
        if args.from_run not in matrix_by_run:
            print(f"未知 run_id: {args.from_run}", file=sys.stderr)
            return 2
        run_ids = [r for r, _, _ in matrix]
        targets = matrix[run_ids.index(args.from_run) :]
    elif args.run:
        if args.run not in matrix_by_run:
            print(f"未知 run_id: {args.run}", file=sys.stderr)
            return 2
        seed, variant = matrix_by_run[args.run]
        targets = [(args.run, seed, variant)]
    else:
        print("必须指定 --run <id> 或 --all", file=sys.stderr)
        return 2

    summary = []
    for run_id, seed_id, variant in targets:
        print(
            f"[{run_id}] seed={seed_id} variant={variant} {'dry' if args.dry else 'real'} ...",
            flush=True,
        )
        result = execute_run(
            run_id,
            seed_id,
            variant,
            dry=args.dry,
            dry_mode=args.dry_mode,
            provider=PROVIDER,
            data=data,
        )
        score = score_run_h2(result)
        result["score"] = score
        write_run_result(run_id, result, out)
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
        "stage": args.stage,
        "count": len(summary),
        "matrix_version": matrix_version,
        "scorer_version": SCORER_VERSION,
        "reasoning_policy": "B",
        "runs": summary,
    }
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
