#!/usr/bin/env python3
"""技能完整性清单人工审批入口（P1-5/S2-4，docs/安全审查与修复建议书-2026-10-25.md）.

由人工运行（勿交给 AI 代跑——AI 同时可写技能与清单，代跑等于自批）：
扫描 skills/ 目录，逐技能对 SKILL.md 计算 sha256，写入 skills/.manifest.json。
此后: 未改动技能 integrity=ok；被篡改 → modified；新增未登记 → unlisted；
LFL_SKILLS_REQUIRE_MANIFEST=1 时后三者拒绝加载（skill_load 返回审批指引）。

诚实边界: 清单与技能同在 AI 可写的工作区内，AI 可同时改两者——本机制是
"篡改可检测 + 加载需审批"，不是防篡改强隔离（强隔离需移出工作区/只读挂载，
见建议书 P1-5/P2）。

用法:
    python scripts/approve_skills.py [skills_dir]

参数:
    skills_dir  技能目录（默认 <仓库根>/skills）

退出码: 0=清单已写入; 1=失败（目录不存在/写入失败）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 镜像仓库约定: pytest pythonpath=["src"] 测本仓代码；裸解释器的 PYTHONPATH
# 可能指向 .releases 快照。无条件把本仓 src 置于 sys.path 最前，保证生成
# 清单用的是本仓 loader 语义（镜像跑镜像）。
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.skills.loader import build_manifest, write_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="技能完整性清单人工审批入口（P1-5/S2-4）"
    )
    parser.add_argument(
        "skills_dir",
        nargs="?",
        default=str(ROOT / "skills"),
        help="技能目录（默认 <仓库根>/skills）",
    )
    args = parser.parse_args(argv)

    skills_dir = Path(args.skills_dir)
    if not skills_dir.is_dir():
        print(f"[失败] 技能目录不存在: {skills_dir}", file=sys.stderr)
        return 1

    manifest = build_manifest(skills_dir)
    try:
        path = write_manifest(skills_dir, manifest)
    except OSError as exc:
        print(f"[失败] 清单写入失败: {exc}", file=sys.stderr)
        return 1

    entries = manifest["skills"]
    print(f"[审批完成] 清单已写入 {path}")
    print(f"共登记 {len(entries)} 个技能:")
    for name in sorted(entries):
        print(f"  - {name}: sha256={entries[name]['sha256'][:16]}…")
    print()
    print("提醒: 请人工逐个 review 上述技能正文后，本次审批才视为有效。")
    print("诚实边界: 清单与技能同在 AI 可写目录内，本机制=可检测+需审批，")
    print("非防篡改强隔离（建议书 P1-5/P2: 强隔离需移出工作区/只读挂载）。")
    print("可选加固: 设 LFL_SKILLS_REQUIRE_MANIFEST=1，未过审技能一律拒绝加载。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
