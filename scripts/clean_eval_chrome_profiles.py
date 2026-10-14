#!/usr/bin/env python3
"""清理 evals 运行残留的 Chrome profile 目录（2026-10-14 落地）.

背景: browser_smc 系 eval 每个 run 会物化一个独立 chrome-profile/
（evals/*/results/<批次>/<NN-task-rN-variant>/chrome-profile），单个几十~几百 MB，
几十个 run 可累计数 GB（实测 83 个 profile 约 7.9GB）。run 的结论数据
（worker-result.json / data/ / results.jsonl）与 profile 同级，删 profile 不影响结论。

清理目标:
1. evals/ 下所有名为 chrome-profile 的目录（默认）
2. data/browser_mount_test/ 下 chrome-profile* 测试目录（需 --include-mount-test）

硬性保护（不因任何参数改变）:
- data/runtime/ 下任何路径一律不碰（活跃 provider 的 profile 所在）
- 符号链接一律跳过
- 目标路径仍被进程引用（pgrep 命中命令行）一律跳过，pgrep 不可用时 fail-safe 跳过

用法:
  python scripts/clean_eval_chrome_profiles.py                # dry-run 预览（默认）
  python scripts/clean_eval_chrome_profiles.py --apply        # 真正删除
  python scripts/clean_eval_chrome_profiles.py --apply --min-age-hours 2
                                                              # 再排除 2 小时内活跃的 run
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_ROOT = REPO_ROOT / "evals"
MOUNT_TEST_ROOT = REPO_ROOT / "data" / "browser_mount_test"
RUNTIME_DIR = REPO_ROOT / "data" / "runtime"


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n}B"


def dir_size(p: Path) -> int:
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def is_protected(resolved: Path) -> bool:
    """data/runtime 下的一切受保护（纵深防御第三层）。"""
    try:
        resolved.relative_to(RUNTIME_DIR)
        return True
    except ValueError:
        return False


def in_use_by_process(resolved: Path) -> tuple[bool, str]:
    """pgrep 检查路径是否出现在任何进程命令行中。

    返回 (busy, 原因)。pgrep 缺失或异常退出码时 fail-safe 视为占用。
    """
    pgrep = shutil.which("pgrep")
    if pgrep is None:
        return True, "pgrep 不可用, fail-safe"
    try:
        proc = subprocess.run(
            [pgrep, "-f", re.escape(str(resolved))],
            capture_output=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True, "pgrep 执行失败, fail-safe"
    if proc.returncode == 0:
        return True, "有进程正在引用该路径"
    if proc.returncode == 1:
        return False, ""
    return True, f"pgrep 异常退出码 {proc.returncode}, fail-safe"


def collect_targets() -> tuple[list[Path], list[Path]]:
    """返回 (evals 目标, mount_test 目标)。"""
    evals_targets: list[Path] = []
    if EVALS_ROOT.is_dir():
        for p in sorted(EVALS_ROOT.rglob("chrome-profile")):
            if p.is_dir() and not p.is_symlink():
                evals_targets.append(p)
    mount_targets: list[Path] = []
    if MOUNT_TEST_ROOT.is_dir():
        for p in sorted(MOUNT_TEST_ROOT.glob("chrome-profile*")):
            if p.is_dir() and not p.is_symlink():
                mount_targets.append(p)
    return evals_targets, mount_targets


def filter_deletable(targets: list[Path], min_age_hours: float) -> tuple[list[Path], int]:
    """逐个过保护检查，返回 (可删列表, 跳过计数)。"""
    doomed: list[Path] = []
    skipped = 0
    for t in targets:
        resolved = t.resolve()
        if is_protected(resolved):
            print(f"[protect] 跳过（data/runtime 保护）: {t}")
            skipped += 1
            continue
        try:
            age_h = (time.time() - t.stat().st_mtime) / 3600
        except OSError:
            print(f"[stat-fail] 跳过（无法读取元信息）: {t}")
            skipped += 1
            continue
        if min_age_hours > 0 and age_h < min_age_hours:
            print(f"[age] 跳过（{age_h:.1f}h < {min_age_hours}h）: {t}")
            skipped += 1
            continue
        busy, why = in_use_by_process(resolved)
        if busy:
            print(f"[busy] 跳过（{why}）: {t}")
            skipped += 1
            continue
        doomed.append(t)
    return doomed, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 evals 残留的 Chrome profile（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正删除（默认仅预览）")
    parser.add_argument("--include-mount-test", action="store_true",
                        help="额外清理 data/browser_mount_test/ 下 chrome-profile* 测试目录")
    parser.add_argument("--min-age-hours", type=float, default=0.0,
                        help="跳过 mtime 距今小于该小时数的目录（防止误删进行中的 run）")
    args = parser.parse_args()

    if not EVALS_ROOT.is_dir():
        print(f"[error] 找不到 {EVALS_ROOT}", file=sys.stderr)
        return 1

    evals_targets, mount_targets = collect_targets()
    targets = evals_targets + (mount_targets if args.include_mount_test else [])
    if args.include_mount_test:
        print(f"[scope] evals: {len(evals_targets)} 个候选; browser_mount_test: {len(mount_targets)} 个候选")
    else:
        print(f"[scope] evals: {len(evals_targets)} 个候选（未含 browser_mount_test, 需 --include-mount-test）")

    doomed, skipped = filter_deletable(targets, args.min_age_hours)
    total = sum(dir_size(t) for t in doomed)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] 待删除 {len(doomed)} 个, 合计 {human_size(total)}; 检查后跳过 {skipped} 个")
    for t in doomed:
        print(f"  - {t.relative_to(REPO_ROOT)}  ({human_size(dir_size(t))})")

    if not args.apply:
        print("\n[dry-run] 未删除任何内容。确认无误后加 --apply 执行。")
        return 0

    deleted, failed = 0, 0
    freed = 0
    for t in doomed:
        size = dir_size(t)
        try:
            shutil.rmtree(t)
            deleted += 1
            freed += size
            print(f"[deleted] {t.relative_to(REPO_ROOT)}")
        except OSError as exc:
            failed += 1
            print(f"[failed] {t.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
    print(f"\n[done] 已删除 {deleted} 个, 释放 {human_size(freed)}; 失败 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
