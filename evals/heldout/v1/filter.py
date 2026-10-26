#!/usr/bin/env python3
"""held-out 污染过滤器薄 CLI（eval/rules/holdout.md §4）.

匹配实现已收敛到 ``src/llm_loop/knowledge/heldout_guard.py``（与运行时写侧
fail-closed / 读侧 fail-open 同一防线：探针 = task_id 原样 + 题面正文
24 字/步长 4 重叠窗口子串命中，空白规范化后比对；任一 ≥32 字连续题面
引用必含一个网格窗口）。本文件只保留 CLI 壳，
不再维护第二份匹配实现，避免两套口径漂移。

弃用说明（``exclusion.forbidden_statement_sha256`` 读取已删除）：旧实现把
"规范化待检文本的 sha256"与 manifest 清单里的 sha256 直接比对，而清单里的
值是 ``statement.md`` **文件字节**的 sha256——文件含标题行且空白未折叠，
与"去标题行 + 空白规范化后的文本"哈希语义不可比，实际恒不命中（no-op）；
该清单本身也与 ``tasks[].statement_sha256`` 冗余。正文泄漏已由探针子串
匹配（statement_probe）以更强口径覆盖，故删除这条死代码路径。

用法（建议用仓库 venv 解释器；系统 python3 为 3.9 时无法导入部分依赖）：
- ``--selfcheck``：manifest/题面完整性 + 过滤器正/负/unavailable 用例自检
  （退出码 0/1）；
- ``--text TEXT``：命中 held-out 探针时退出码 2 并打印 BLOCKED（消息只含
  类别与 task_id，绝不回显待检文本）；guard unavailable 时 fail-open 放行
  （打印 UNAVAILABLE + reason，退出码 0）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# 薄 CLI 委托 src 实现：仓库根 = parents[3]（filter.py 位于 evals/heldout/v1/）。
# editable 安装的 .pth 已把 src 追加在 sys.path 末尾，优先级低于 PYTHONPATH
# 里的旧 release 快照——因此先移除既有条目再插到最前，确保委托的是本工作树实现。
_SRC = Path(__file__).resolve().parents[3] / "src"
if _SRC.is_dir():
    while str(_SRC) in sys.path:
        sys.path.remove(str(_SRC))
    sys.path.insert(0, str(_SRC))

from llm_loop.knowledge import heldout_guard  # noqa: E402 — sys.path 注入必须在 import 前

_HERE = Path(__file__).resolve().parent
MANIFEST_PATH = _HERE / "manifest.json"


def selfcheck() -> int:
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
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

    # 1b) 探针覆盖：每个 task 至少 1 个探针（task_id 原样或正文窗口）。
    #     探针派生复用 guard 本体 _probes（单一实现，CLI 不维护第二份口径）；
    #     正文规范化后 >144 字时，窗口数 >31，等距抽样到上限 16 后相邻起点
    #     间距可能 >8 字，"任一 ≥32 字连续引用必含一个网格窗口"的几何保证
    #     不再自动成立 → 显式提示需重跑召回测试（提示不改变退出码，只提示）。
    probe_map = heldout_guard._probes(man, MANIFEST_PATH.parent)
    for t in man["tasks"]:
        tid = str(t.get("task_id") or "")
        if not probe_map.get(tid):
            failures.append(f"探针缺失: {tid}（task_id 与正文探针均为空）")
        stmt = _HERE / "tasks" / tid / "statement.md"
        if not stmt.exists():
            continue  # 缺文件已在 1) 记为 FAIL，这里不重复读
        parts = stmt.read_text(encoding="utf-8").split("\n", 1)
        body = " ".join((parts[1] if len(parts) == 2 else parts[0]).split())
        if len(body) > 144:
            print(f"  HINT: {tid} 该题面超过探针等距抽样覆盖范围，需重跑召回测试（正文 {len(body)} 字）")

    t0 = man["tasks"][0]

    # 2) 正例：task_id 命中必须 blocked（reason 只含类别与 task_id）
    verdict = heldout_guard.check_text(f"引用了 {t0['task_id']} 的结果", manifest_path=MANIFEST_PATH)
    if verdict.get("status") != "blocked" or verdict.get("task_id") != t0["task_id"]:
        failures.append("过滤器未抓出 task_id 泄漏")

    # 3) 正例：题面正文片段（中段 60 字窗口）必须 blocked（statement_probe）
    raw = (_HERE / "tasks" / t0["task_id"] / "statement.md").read_text(encoding="utf-8")
    parts = raw.split("\n", 1)
    body = " ".join((parts[1] if len(parts) == 2 else parts[0]).split())
    if len(body) < 60:
        failures.append("题面正文短于 60 字，正文片段用例不成立")
    else:
        mid = len(body) // 2
        verdict = heldout_guard.check_text(body[mid : mid + 60], manifest_path=MANIFEST_PATH)
        if verdict.get("status") != "blocked":
            failures.append("过滤器未抓出题面正文片段泄漏")

    # 4) 负例：普通中文技术句必须放行
    verdict = heldout_guard.check_text(
        "今天我要修复一个解析器的空指针缺陷，先写回归测试再改实现。",
        manifest_path=MANIFEST_PATH,
    )
    if verdict.get("status") != "clean":
        failures.append("过滤器误报正常文本")

    # 5) unavailable：manifest 指向不存在路径 → fail-open（放行但如实标注）
    verdict = heldout_guard.check_text(
        "任意文本", manifest_path=_HERE / "ghost" / "manifest.json"
    )
    if verdict.get("status") != "unavailable":
        failures.append("manifest 缺失时未返回 unavailable")

    # 6) 题面规则与域内已覆盖规则不得重叠（避免 held-out 与训练集同题）
    scen = Path(__file__).resolve().parents[2] / "tests" / "eval_sets" / "scenarios_v2.json"
    if scen.exists():
        covered = set(json.loads(scen.read_text(encoding="utf-8")).get("rules_covered", []))
        overlap = sorted(set(man.get("source_rule_pool", [])) & {f"RULE-AI-{c}" for c in covered})
        if overlap:
            failures.append(f"held-out 与域内场景规则重叠: {overlap}")

    print(f"selfcheck: {len(man['tasks'])} tasks, {len(failures)} failure(s)")
    for f in failures:
        print(f"  FAIL: {f}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="held-out 污染过滤器（薄 CLI；实现见 src/llm_loop/knowledge/heldout_guard.py）"
    )
    ap.add_argument("--selfcheck", action="store_true", help="运行自检")
    ap.add_argument("--text", help="检查给定文本是否含 held-out 泄漏")
    args = ap.parse_args()
    if args.selfcheck:
        return selfcheck()
    if args.text is not None:
        verdict = heldout_guard.check_text(args.text, manifest_path=MANIFEST_PATH)
        if verdict.get("status") == "blocked":
            # 消息只含类别与 task_id，绝不回显待检文本
            print(f"BLOCKED: held-out 泄漏({verdict.get('reason')}): {verdict.get('task_id')}")
            return 2
        if verdict.get("status") == "unavailable":
            print(f"UNAVAILABLE(fail-open): {verdict.get('reason')}")
            return 0
        print("OK")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
