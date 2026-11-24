"""追溯矩阵机检（A3 自检，元测试）——矩阵自身的守卫，不入矩阵、不计入覆盖函数数。

守三条不变量，每条都对应一次真实事故：
1. ctp/tests 下每个测试函数都必须在 trace.csv 具名——概括性的「等」会制造隐藏孤儿
   （2026-11-24 自查：31 个函数曾因此未具名，六轮审查未发现）；
2. trace.md / coverage-summary.md 声明的函数计数（总数与逐文件）必须等于 AST 实测
   （计数漂移曾连续被独立审查判为 P1 / P2）；
3. 矩阵里 file.py:NN 形式的证据行号必须正是该测试函数的 def 行（行号曾因插行整体偏移）。
"""

from __future__ import annotations

import ast
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "ctp" / "tests"
TRACE_CSV = ROOT / "docs" / "trace" / "trace.csv"
DOCS = (ROOT / "docs" / "trace" / "trace.md", ROOT / "docs" / "trace" / "coverage-summary.md")
META = "test_trace_matrix"  # 本文件：元测试，不属规范条目覆盖
NAME = re.compile(r"test_[a-z0-9_]+")
EVIDENCE = re.compile(r"ctp/tests/(test_[a-z0-9_]+)\.py:(\d+)")


def _defs() -> dict[str, dict[str, int]]:
    """{文件 stem: {测试函数名: def 行号}}，AST 实测。"""
    out: dict[str, dict[str, int]] = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out[path.stem] = {
            node.name: node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }
    return out


def test_every_test_function_is_named_in_trace_csv():
    named = set(NAME.findall(TRACE_CSV.read_text(encoding="utf-8")))
    orphans = [
        (stem, name)
        for stem, functions in _defs().items()
        if stem != META
        for name in functions
        if name not in named
    ]
    assert not orphans, f"孤儿测试（未在 trace.csv 具名）：{orphans}"


def test_declared_function_counts_match_ast():
    counts = {stem: len(functions) for stem, functions in _defs().items() if stem != META}
    total = sum(counts.values())
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        assert f"{total} 个测试函数" in text, f"{doc.name} 未声明实测总数 {total}"
        for stem, count in counts.items():
            assert f"{stem.removeprefix('test_')} {count}" in text, f"{doc.name} 未声明 {stem} {count}（实测）"


def test_evidence_line_numbers_point_at_def_lines():
    defs = _defs()
    problems = []
    with TRACE_CSV.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name_match = NAME.search(row["test_id"])
            if not name_match:
                continue
            name = name_match.group(0)
            evidence_match = EVIDENCE.search(row["evidence_path"])
            if not evidence_match:
                problems.append((row["spec_entry"], name, "evidence lacks file:line"))
                continue
            stem, cited = evidence_match.group(1), int(evidence_match.group(2))
            actual = defs.get(stem, {}).get(name)
            if actual is None:
                problems.append((row["spec_entry"], name, f"no such test in {stem}"))
            elif actual != cited:
                problems.append((row["spec_entry"], name, f"cited {cited}, def at {actual}"))
    assert not problems, problems
