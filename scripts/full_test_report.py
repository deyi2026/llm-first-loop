#!/usr/bin/env python3
"""把「哪些红是本轮新增」从人工比对变成机器判据。

问题（2026-11-02 全量回归实测）：``pytest tests -q`` 报 ``10 failed``，其中没有一条
是本轮改动引入的，但输出里只有 10 行 FAILED —— 没有任何机器判据区分"存量红"与
"我引入的红"，只能去父提交开 worktree 逐条复现（人工约 20 分钟，且容易漏）。

本脚本把该判断固化，复用既有登记基线 ``eval/rules/known_reds_current.json`` 与
``eval/rules/red_reconciliation.py`` 的归一化逻辑（不另立第二份真值）：

  python scripts/full_test_report.py -- .venv/bin/python -m pytest tests -q
  python scripts/full_test_report.py --report /tmp/report.xml     # 只对账，不重跑

判定：
  * 实测红 − 登记红 非空 → 新增红 → 阻断（退出码 1）
  * 登记红已转绿 → 过期登记 → 只告警（不阻断，但要清理）
  * 基线缺失 / junit 无法解析 → 退出码 2（fail closed，不假装通过）
  * pytest 自身崩溃（collection error 等，退出码 ≥2）→ 沿用该退出码
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.rules.red_reconciliation import load_registry, parse_junit  # noqa: E402


def classify(failed: set[str], errored: set[str], registered: set[str]) -> dict[str, list[str]]:
    """实测红 vs 登记红：返回 new / stale / known 三组（都按名字排序，便于 diff）。"""
    observed = set(failed) | set(errored)
    return {
        "new": sorted(observed - registered),
        "stale": sorted(registered - observed),
        "known": sorted(observed & registered),
    }


def render(groups: dict[str, list[str]], *, stats: dict, pytest_exit: int | None = None) -> list[str]:
    observed = len(groups["new"]) + len(groups["known"])
    lines = [
        f"[known-reds] 实测红 {observed} / 登记红 {len(groups['known']) + len(groups['stale'])}"
        f" / 新增 {len(groups['new'])} / 过期登记 {len(groups['stale'])}",
        f"[known-reds] tests={stats.get('tests', 0)} failures={stats.get('failures', 0)}"
        f" errors={stats.get('errors', 0)} skipped={stats.get('skipped', 0)}",
    ]
    if groups["new"]:
        lines.append("[新增红 · 阻断] 下列失败未登记（先确认是否本轮引入，再决定修还是登记）：")
        lines.extend(f"  - {nodeid}" for nodeid in groups["new"])
    if groups["stale"]:
        lines.append("[过期登记 · 仅告警] 下列登记红本次未复现（跑子集时属正常；全量仍缺才是真转绿）：")
        lines.extend(f"  - {nodeid}" for nodeid in groups["stale"])
    if groups["known"]:
        lines.append("[登记红 · 不阻断] 与基线一致：")
        lines.extend(f"  - {nodeid}" for nodeid in groups["known"])
    if pytest_exit is not None:
        lines.append(f"[known-reds] pytest exit={pytest_exit}")
    verdict = "FAIL" if groups["new"] else "PASS"
    lines.append(
        f"[known-reds] verdict={verdict} 新增失败 {len(groups['new'])} / 已知失败 {len(groups['known'])}"
    )
    return lines


def report_from_junit(path: Path) -> tuple[int, list[str]]:
    """对账一个 junit 报告；返回 (退出码, 输出行)。"""
    registered, _meta = load_registry()
    if registered is None:
        return 2, ["[known-reds] 无法读取登记基线 eval/rules/known_reds_current.json（fail closed）"]
    try:
        failed, errored, stats = parse_junit(path)
    except Exception as exc:  # noqa: BLE001 - junit 损坏/缺文件都应 fail closed
        return 2, [f"[known-reds] 无法解析 junit 报告 {path}: {exc}"]
    groups = classify(failed, errored, registered)
    return (1 if groups["new"] else 0), render(groups, stats=stats)


def run_pytest(argv: list[str]) -> tuple[int, Path, tempfile.TemporaryDirectory | None]:
    """跑 pytest 并把 junit 写到临时文件；调用方已给 --junitxml 时沿用它。"""
    has_junit = any(arg.startswith("--junitxml") for arg in argv)
    if has_junit:
        for arg in argv:
            if arg.startswith("--junitxml="):
                return -1, Path(arg.split("=", 1)[1]), None
        raise SystemExit("[known-reds] --junitxml 需要写成 --junitxml=PATH 形式才能对账")
    holder = tempfile.TemporaryDirectory(prefix="lfl-full-test-")
    report = Path(holder.name) / "report.xml"
    completed = subprocess.run([*argv, f"--junitxml={report}"], check=False)
    return completed.returncode, report, holder


def main(argv: list[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--report", help="已有 junit 报告路径（只对账，不跑测试）")
    known, unknown = parser.parse_known_args(args_in)
    if known.report:
        code, lines = report_from_junit(Path(known.report))
        print("\n".join(lines))
        return code

    cmd = unknown[1:] if unknown and unknown[0] == "--" else unknown
    if not cmd:
        parser.error("需要给出要执行的测试命令，例如: -- .venv/bin/python -m pytest tests -q")
    code, report, holder = run_pytest(cmd)
    exit_code, lines = report_from_junit(report)
    print("\n".join(lines))
    if holder is not None:
        holder.cleanup()
    if code >= 2:  # pytest 自身崩溃（collection error / 中断）：如实传播，不伪装成"只有登记红"
        return code
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
