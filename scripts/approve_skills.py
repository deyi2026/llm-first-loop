#!/usr/bin/env python3
"""技能完整性清单（基线）生成入口（v2，EVO-20261031-6b21e0f4）.

清单是什么:
  skills/.manifest.json 记录每个技能的**整个目录树**的 sha256（外加逐文件
  摘要）。它证明的是「磁盘上的技能与登记时一致」，即完整性基线；它**不**
  证明「内容被谁逐字读过」。两件事必须分开说，否则清单就成了伪造的审批
  痕迹。

为什么覆盖目录树而不是只覆盖 SKILL.md:
  SKILL.md 只是指向 scripts/、data/、sections/ 的索引，执行输入是那些
  文件（实测 skills/ui-ux-pro-max = 49 文件 / 3.33MB，SKILL.md 只是其中
  一个）。只哈希 SKILL.md 的门禁对「改了脚本、没改 SKILL.md」完全失明。

谁可以跑:
  人工跑是常规路径。AI 代跑也允许，但必须用 --approved-by 如实标注身份：
  不得把机器生成的基线写成人工审阅过的痕迹。人工复核后可重跑本脚本并
  写入具体标识。

诚实边界:
  清单与技能同在 AI 可写的工作区内，AI 可以同时改两者。本机制是
  「篡改可检测 + 加载需过基线」，不是防篡改强隔离（强隔离需把清单移出
  工作区或只读挂载）。真正的分界在推送环节：skills/ 的任何改动都会进入
  git diff，必须通过 review_admission 的独立审查才能推上去。

用法:
    python scripts/approve_skills.py [skills_dir] [--approved-by <标识>]

参数:
    skills_dir      技能目录（默认 <仓库根>/skills）
    --approved-by   本版基线的批准者标识（默认 baseline = 脚本按现状生成，
                    不代表内容已被人工逐字审阅）

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
        description="技能完整性清单（基线）生成入口（v2）"
    )
    parser.add_argument(
        "skills_dir",
        nargs="?",
        default=str(ROOT / "skills"),
        help="技能目录（默认 <仓库根>/skills）",
    )
    parser.add_argument(
        "--approved-by",
        default="baseline",
        help=(
            "本版基线的批准者标识。默认 baseline = 由脚本按磁盘现状生成，"
            "不代表内容已被人工逐字审阅；人工复核后请写入具体标识，"
            "不要把机器生成的基线记成人工审阅。"
        ),
    )
    args = parser.parse_args(argv)

    skills_dir = Path(args.skills_dir)
    if not skills_dir.is_dir():
        print(f"[失败] 技能目录不存在: {skills_dir}", file=sys.stderr)
        return 1

    manifest = build_manifest(skills_dir, approved_by=args.approved_by)
    try:
        path = write_manifest(skills_dir, manifest)
    except OSError as exc:
        print(f"[失败] 清单写入失败: {exc}", file=sys.stderr)
        return 1

    entries = manifest["skills"]
    vendored = sum(1 for e in entries.values() if e.get("source") == "vendored")
    print(f"[基线已写入] {path}")
    print(f"批准者标识: {args.approved_by}")
    print(f"共登记 {len(entries)} 个技能（vendored {vendored} 个）:")
    for name in sorted(entries):
        e = entries[name]
        files = len(e.get("files", {}))
        origin = e.get("source", "local")
        tag = f" [{origin}]" if origin == "vendored" else ""
        print(f"  - {name}{tag}: tree={e['tree_sha256'][:16]}… files={files}")
    print()
    print("提醒: 清单=完整性基线（内容与登记时一致），不等于内容已被逐字审阅。")
    print("     如需声明人工复核，请带 --approved-by <标识> 重跑。")
    print("诚实边界: 清单与技能同在 AI 可写目录内，本机制=可检测+需过基线，")
    print("非防篡改强隔离；skills/ 的改动仍须过 review_admission 独立审查才能推送。")
    print("加固开关: 设 LFL_SKILLS_REQUIRE_MANIFEST=1，未过基线的技能拒绝加载。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
