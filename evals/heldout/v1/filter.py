#!/usr/bin/env python3
"""held-out 污染过滤器（eval/rules/holdout.md §4 机制实现）.

用途：任何写入 method/experience/lesson/episode/memory/memory_extract 的操作前，
必须先调用 `assert_not_heldout(text, manifest)` 过滤，防止 held-out 题面/题解/
失败轨迹或 task_id 泄漏进改进语料。

自检：``python3 evals/heldout/v1/filter.py --selfcheck``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
MANIFEST_PATH = _HERE / "manifest.json"


def load_manifest(path: str | os.PathLike[str] = MANIFEST_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_not_heldout(text: str, manifest: dict | None = None) -> None | str:
    """返回 None 表示通过；返回字符串表示违规原因。"""
    man = manifest if manifest is not None else load_manifest()
    ex = man.get("exclusion", {})
    forbidden_ids = list(ex.get("forbidden_task_ids", []))
    forbidden_shas = set(ex.get("forbidden_statement_sha256", []))

    if not text:
        return None

    # 1) task_id 命中
    for tid in forbidden_ids:
        if tid and tid in text:
            return f"held-out task_id 泄漏: {tid}"

    # 2) 题面原文（规范化空白后）命中
    norm = " ".join(text.split())
    if norm and _sha256(norm) in forbidden_shas:
        return "held-out 题面原文泄漏"

    # 3) 逐条子串命中（题面全文包含）
    for t in man.get("tasks", []):
        stmt = _HERE / "tasks" / t["task_id"] / "statement.md"
        if not stmt.exists():
            continue
        body = stmt.read_text(encoding="utf-8")
        # 去掉标题行，只比对正文
        body = body.split("\n", 2)[-1].strip()
        if len(body) > 40 and body in text:
            return f"held-out 题面片段泄漏: {t['task_id']}"

    return None


def selfcheck() -> int:
    man = load_manifest()
    failures: list[str] = []

    # 1) 每个 task 目录三件套齐全，且 sha256 与 manifest 一致
    for t in man["tasks"]:
        d = _HERE / "tasks" / t["task_id"]
        for name, key in (
            ("statement.md", "statement_sha256"),
            ("test_patch.json", "test_patch_sha256"),
            ("solution.md", "solution_sha256"),
        ):
            p = d / name
            if not p.exists():
                failures.append(f"缺文件: {t['task_id']}/{name}")
                continue
            got = hashlib.sha256(p.read_bytes()).hexdigest()
            if got != t[key]:
                failures.append(f"sha256 不符: {t['task_id']}/{name}")

    # 2) 过滤器必须能抓到自己造的泄漏
    t0 = man["tasks"][0]
    if assert_not_heldout(f"引用了 {t0['task_id']} 的结果", man) is None:
        failures.append("过滤器未抓出 task_id 泄漏")
    stmt = (_HERE / "tasks" / t0["task_id"] / "statement.md").read_text(encoding="utf-8")
    if assert_not_heldout(stmt, man) is None:
        failures.append("过滤器未抓出题面原文泄漏")

    # 3) 正常文本必须放行
    if assert_not_heldout("今天我要修复一个解析器的空指针缺陷。", man) is not None:
        failures.append("过滤器误报正常文本")

    # 4) 题面规则与域内已覆盖规则不得重叠（避免 held-out 与训练集同题）
    scen = Path(__file__).resolve().parents[2] / "tests" / "eval_sets" / "scenarios_v2.json"
    if scen.exists():
        covered = set(json.load(open(scen, encoding="utf-8")).get("rules_covered", []))
        overlap = sorted(set(man.get("source_rule_pool", [])) & {f"RULE-AI-{c}" for c in covered})
        if overlap:
            failures.append(f"held-out 与域内场景规则重叠: {overlap}")

    print(f"selfcheck: {len(man['tasks'])} tasks, {len(failures)} failure(s)")
    for f in failures:
        print(f"  FAIL: {f}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="held-out 污染过滤器")
    ap.add_argument("--selfcheck", action="store_true", help="运行自检")
    ap.add_argument("--text", help="检查给定文本是否含 held-out 泄漏")
    args = ap.parse_args()
    if args.selfcheck:
        return selfcheck()
    if args.text is not None:
        reason = assert_not_heldout(args.text)
        if reason:
            print(f"BLOCKED: {reason}")
            return 2
        print("OK")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
