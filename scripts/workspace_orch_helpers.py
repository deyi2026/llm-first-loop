#!/usr/bin/env python3
"""编排脚本辅助原语（workspace_migration_orchestrate.sh 调用；无 jq 依赖）.

子命令（均设计为可静默失败、退出码 0、输出空串/占位——编排层自行判定）：
  json-field <file> <field>   读 JSON 文件顶层字段（缺文件/损坏/缺键 → 空）
  verify-diffs <verify.json>  解析 migrate_workspace.py verify 输出，
                              列出 pass=false 的检查名（逗号分隔；解析失败
                              → "(差异清单解析失败，见原文件)"）
"""
from __future__ import annotations

import json
import sys


def cmd_json_field(argv: list[str]) -> int:
    if len(argv) != 2:
        return 0
    try:
        with open(argv[0], encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 — 缺文件/损坏按空值处理
        return 0
    if not isinstance(data, dict):
        return 0
    value = data.get(argv[1], "")
    print("" if value is None else value)
    return 0


def cmd_verify_diffs(argv: list[str]) -> int:
    if len(argv) != 1:
        print("(差异清单解析失败，见原文件)")
        return 0
    try:
        with open(argv[0], encoding="utf-8") as fh:
            data = json.load(fh)
        checks = data.get("checks", {})
        bad = sorted(
            key for key, val in checks.items()
            if isinstance(val, dict) and not val.get("pass")
        )
        print(",".join(bad) if bad else "(未解析出失败项，见原文件)")
    except Exception:  # noqa: BLE001 — 解析失败输出占位，编排层引用原文件
        print("(差异清单解析失败，见原文件)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "json-field":
        return cmd_json_field(argv[1:])
    if len(argv) >= 1 and argv[0] == "verify-diffs":
        return cmd_verify_diffs(argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
