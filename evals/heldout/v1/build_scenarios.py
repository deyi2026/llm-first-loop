#!/usr/bin/env python3
"""held-out 清单 → run_ab.py 可消费的场景集（**机械转换**，不打印题面内容）。

为什么要有这个脚本：held-out 跑批器此前缺失（计划 §19.5 登记的缺口）。
本脚本只做格式转换，不做任何"看懂题目"的事，因此不构成对改进回路的污染：
  · 题面（statement.md）→ 场景 prompt（原样搬运，不改写、不摘要）
  · 判据（test_patch.json 的 verdict/expect）→ 场景 params
  · 工具名（仅 tool_used 类）→ 从题面/判据文本里**按已知工具名做正则提取**，
    提不出就置 null 并在转换清单里标出（不猜、不硬编）

用法::

    python3 evals/heldout/v1/build_scenarios.py            # 写出场景集 + 转换清单
    python3 evals/heldout/v1/build_scenarios.py --check    # 只自检（题面/判据齐不齐）

纪律：**转换清单与场景集都不打印题面正文**（只打印条数、sha256、工具名提取结果）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
TASKS = _HERE / "tasks"
MANIFEST = _HERE / "manifest.json"
OUT_SCENARIOS = _HERE / "scenarios_heldout_v1.json"
OUT_INDEX = _HERE / "conversion_index.json"

KNOWN_TOOLS = [
    "execute_command",
    "read_file",
    "search_files",
    "read_image",
    "read_evidence",
    "search_evidence",
    "read_attachment",
    "web_fetch",
    "web_search",
    "browser_perceive",
    "browser_operate",
    "send_feishu_message",
    "create_feishu_doc",
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _extract_tool(*texts: str) -> str | None:
    """从文本里按已知工具名提取（取最长匹配，避免 'read_file' 被 'read' 抢先）。"""
    blob = "\n".join(t or "" for t in texts)
    best: str | None = None
    for t in sorted(KNOWN_TOOLS, key=len, reverse=True):
        if re.search(r"(?<![\w])" + re.escape(t) + r"(?![\w])", blob):
            best = t
            break
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scenarios = []
    index = []
    missing = []
    for t in manifest["tasks"]:
        tid = t["task_id"]
        d = TASKS / tid
        stmt = d / "statement.md"
        tp = d / "test_patch.json"
        if not stmt.exists() or not tp.exists():
            missing.append(tid)
            continue
        patch = json.loads(tp.read_text(encoding="utf-8"))
        expect = patch.get("expect") or t.get("expect") or ""
        verdict = patch.get("verdict") or t.get("verdict") or ""
        statement = stmt.read_text(encoding="utf-8")
        params = {
            "rule": "HELDOUT",
            "expect": expect,
            "category": t.get("rule", ""),
        }
        tool = None
        if verdict == "tool_used":
            tool = _extract_tool(expect, statement)
            if tool:
                params["tool"] = tool
            else:
                # 判据只说"须实际用工具核验"、没点名工具 → 改挂 tool_used_any
                # （tool_used 对空 tool 一律 fail-closed → 会恒判失败）
                verdict = "tool_used_any"
                params.pop("tool", None)
        scenarios.append(
            {
                "id": tid,
                "name": t.get("title", tid),
                "samples": int(t.get("samples", 6)),
                "max_iterations": 12,
                "verdict": verdict,
                "params": params,
                "prompt": statement,
            }
        )
        index.append(
            {
                "task_id": tid,
                "verdict": verdict,
                "expect_sha256": hashlib.sha256(expect.encode("utf-8")).hexdigest(),
                "statement_sha256": _sha(stmt),
                "test_patch_sha256": _sha(tp),
                "tool_extracted": tool,
            }
        )

    print(f"任务 {len(manifest['tasks'])} 条；可转换 {len(scenarios)} 条")
    if missing:
        print(f"[WARN] {len(missing)} 条有问题：{missing[:5]}{'...' if len(missing) > 5 else ''}")
    if args.check:
        return 0 if not missing else 2

    OUT_SCENARIOS.write_text(
        json.dumps(
            {
                "source": "evals/heldout/v1/manifest.json",
                "note": "机械转换产物；题面原样搬运。转换清单见 conversion_index.json",
                "scenarios": scenarios,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    OUT_INDEX.write_text(
        json.dumps({"n": len(index), "items": index}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写出 {OUT_SCENARIOS.name} 与 {OUT_INDEX.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
