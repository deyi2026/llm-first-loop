"""CI 红数对账门禁：实测红项 vs 登记红项，超出登记即失败。

2026-10-23（P1 出口判据第③项「CI 门脚本可执行」）：
仓库此前**没有任何红数对账机制** —— CI 不使用 xfail/deselect 豁免，红数全靠人工比对
（docs/EVAL-PLAN-LFL-20261023.md §18.2 第 4 点 + §18.4）。后果实测：known-reds
文档登记的 4 项 HEAD 预存红与当时实测的 3 条红**编号与成因均不同**（已知红已迁移，
当前红是未登记的存量债），没有任何机器判据能发现"新增了一条红"。

本脚本提供该判据：
- 输入：pytest 报告（--junitxml 或文本输出）
- 基线：eval/rules/known_reds_current.json（当前**有效**登记红项；与
  docs/known-reds-20260909.md 的历史归因档案分工）
- 判定：
    * 未登记的新红 → FAIL（门禁阻断）
    * 登记红已消失 → WARN（过期登记项，建议清理；不阻断）
    * 登记红与实测完全一致 → PASS

用法：
    uv run --no-sync python eval/rules/red_reconciliation.py --report report.xml
    # 或直接跑测试并管道进来（文本输出）
    uv run --no-sync python -m pytest tests/ -q -m "not real_llm and not serial_signal" 2>&1 \
        | uv run --no-sync python eval/rules/red_reconciliation.py --stdin
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "eval" / "rules" / "known_reds_current.json"

# pytest 文本输出里的失败行：`FAILED tests/...::test_x - reason` / `ERROR tests/...`
_RE_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)")


def _norm(test_id: str) -> str:
    """归一化测试 id，使**登记基线**与**实测 junit** 两侧可比。

    保留参数化后缀是必要的：RED-02 正是参数化用例（[True-none-False]），
    去后缀会把不同参数实例合并成一条 → 掩盖真实差异。

    2026-10-23 修正（护栏实测发现）：原实现假设 junitxml 带 file="tests/a.py"，
    但**真实 pytest --junitxml 产出没有 file 属性**（实测：testcase 只有
    classname='tests.test_memory_phase3_rrf' / name='test_...'）→ 走 classname
    fallback 得到 'tests/test_memory_phase3_rrf::test_x'（**丢 .py 后缀**），
    而登记基线写的是 'tests/test_memory_phase3_rrf.py::test_x' → 两侧不匹配
    → **已登记红全部被误判成新红** → 门禁恒失败（误阻断，CI 永久红）。

    修法：两侧统一归一化到「点号化模块路径::name」——
      - 路径分隔符统一为 '/'
      - 模块末段的 '.py' 后缀去掉（'a/b.py' 与 'a/b' 视为同一模块）
      - classname 的点号转 '/'（'tests.unit.test_x' → 'tests/unit/test_x'）
    这样 file 属性有无都能得到同一形式。
    """
    tid = test_id.strip()
    if "::" in tid:
        path, _, rest = tid.partition("::")
    else:
        path, rest = "", tid
    path = path.replace("\\", "/")
    if path.endswith(".py"):
        path = path[:-3]
    # classname 形式（点号化）→ 斜杠化；已是斜杠的不动
    if path and "." in path and "/" not in path:
        path = path.replace(".", "/")
    return f"{path}::{rest}" if path else rest


def _norm_registry(test_id: str) -> str:
    """登记基线条目的归一化（与 _norm 同一规则）。"""
    return _norm(test_id)


def parse_junit(path: Path) -> tuple[set[str], set[str], dict]:
    """从 junit xml 解析失败/错误测试 id 与统计。"""
    tree = ET.parse(path)
    root = tree.getroot()
    failed: set[str] = set()
    errored: set[str] = set()
    stats = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for case in root.iter("testcase"):
        stats["tests"] += 1
        name = case.get("name") or ""
        cls = case.get("classname") or ""
        # pytest 的 junitxml 会写 file="tests/a.py"（含 .py 后缀的原始路径）——
        # 用它还原测试 id，才能与登记基线里的 "tests/a.py::test_x" 精确对齐。
        # classname 是点号化的模块名（'tests.unit.test_x'），**丢失 .py 后缀**，
        # 无法无损还原为文件路径 → 只能作 fallback。
        fpath = case.get("file") or ""
        if fpath and "::" not in name:
            tid = f"{fpath}::{name}"
        elif cls and "::" not in name:
            tid = f"{cls.replace('.', '/')}::{name}"
        else:
            tid = name
        for child in case:
            tag = child.tag
            if tag == "failure":
                failed.add(_norm(tid))
                stats["failures"] += 1
            elif tag == "error":
                errored.add(_norm(tid))
                stats["errors"] += 1
            elif tag == "skipped":
                stats["skipped"] += 1
    return failed, errored, stats


def parse_text(text: str) -> tuple[set[str], set[str], dict]:
    """从 pytest 文本输出解析失败/错误测试 id 与统计。"""
    failed: set[str] = set()
    errored: set[str] = set()
    stats = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for line in text.splitlines():
        m = _RE_FAILED.match(line.strip())
        if m:
            (failed if line.strip().startswith("FAILED") else errored).add(_norm(m.group(1)))
    # 统计行：'3 failed, 10039 passed, 134 skipped, 23 deselected in 737.02s'
    tail = text.strip().splitlines()[-1] if text.strip() else ""
    for key, field in (
        ("failed", "failures"),
        ("error", "errors"),
        ("skipped", "skipped"),
        ("passed", "tests"),
    ):
        m = re.search(rf"(\d+) {key}", tail)
        if m:
            stats[field] = int(m.group(1))
    return failed, errored, stats


def load_registry() -> tuple[set[str] | None, dict]:
    """读取登记基线。文件缺失 → 返回 (None, {})（由调用方决定退出码 2）。

    不在此处 raise SystemExit：退出码语义集中在 main，便于测试断言返回值。
    """
    if not REGISTRY.exists():
        return None, {}
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    reg = {_norm(item["test"]) for item in data.get("registered", [])}
    return reg, data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--report", help="pytest --junitxml 产出的 xml 路径")
    src.add_argument("--stdin", action="store_true", help="从 stdin 读 pytest 文本输出")
    ap.add_argument(
        "--allow-unregistered",
        action="store_true",
        help="只报告不阻断（用于观察；发布门禁不得使用此开关）",
    )
    args = ap.parse_args(argv)

    if args.stdin:
        text = sys.stdin.read()
        failed, errored, stats = parse_text(text)
    else:
        p = Path(args.report)
        if not p.exists():
            print(f"[FAIL] 报告文件不存在: {p}", file=sys.stderr)
            return 2
        failed, errored, stats = parse_junit(p)

    observed = failed | errored
    registered, data = load_registry()
    if registered is None:
        print(f"[FAIL] 登记红项文件不存在: {REGISTRY}", file=sys.stderr)
        return 2

    new_reds = sorted(observed - registered)
    stale = sorted(registered - observed)
    covered = sorted(observed & registered)

    print("═══ CI 红数对账 ═══")
    try:
        reg_label = str(REGISTRY.relative_to(ROOT))
    except ValueError:
        reg_label = str(REGISTRY)
    print(f"登记基线: {reg_label}  （{len(registered)} 条有效登记红）")
    print(f"实测红数: {len(observed)}  （failed {len(failed)} / error {len(errored)}）")
    print(f"登记命中: {len(covered)}")
    for t in covered:
        print(f"  [REGISTERED] {t}")
    if new_reds:
        print(f"\n未登记新红（{len(new_reds)} 条）→ 超出登记项 = 门禁失败:")
        for t in new_reds:
            print(f"  [NEW-RED]    {t}")
    if stale:
        print(f"\n过期登记项（{len(stale)} 条，实测已不红）→ 建议清理（不阻断）:")
        for t in stale:
            print(f"  [STALE]      {t}")
    if stats.get("tests"):
        print(f"\n统计: tests={stats['tests']} failures={stats['failures']} "
              f"errors={stats['errors']} skipped={stats['skipped']}")

    if new_reds:
        verdict = "FAIL"
    elif stale:
        verdict = "PASS（有过期登记项待清理）"
    else:
        verdict = "PASS"
    print(f"\n[GATE] 红数对账 = {verdict}")

    if new_reds and not args.allow_unregistered:
        print(
            "处置：新红必须先定性归因并登记到 eval/rules/known_reds_current.json，"
            "或修复后重跑；不得直接豁免。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
