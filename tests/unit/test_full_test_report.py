"""对账脚本 scripts/full_test_report.py: 新增红必须能被机器判据抓住。

背景: 全量跑出 10 条红时，人工无法从 10 行 FAILED 里区分"存量红"与"本轮引入"，
只能去父提交开 worktree 复现。脚本把这条判断固化，判定错误的方向必须是**fail closed**
（认不出就当新增），不能把未知红当已知吞掉。
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.full_test_report import classify, render, report_from_junit

_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="{tests}" failures="{failures}" errors="0" skipped="0">
{body}
</testsuite></testsuites>
"""

_CASE_FAIL = """<testcase classname="{cls}" name="{name}"><failure message="boom">x</failure></testcase>"""


def _write_junit(tmp_path: Path, cases: list[str]) -> Path:
    body = "\n".join(cases)
    path = tmp_path / "report.xml"
    path.write_text(_JUNIT.format(tests=len(cases), failures=len(cases), body=body), encoding="utf-8")
    return path


def test_classify_splits_new_stale_and_known():
    groups = classify(
        failed={"tests/a::t1", "tests/a::t2"},
        errored={"tests/b::t3"},
        registered={"tests/a::t2", "tests/c::t9"},
    )
    assert groups["new"] == ["tests/a::t1", "tests/b::t3"]
    assert groups["stale"] == ["tests/c::t9"]
    assert groups["known"] == ["tests/a::t2"]


def test_render_reports_counts_and_verdict():
    lines = render({"new": ["tests/a::t1"], "stale": [], "known": []}, stats={})
    assert any("verdict=FAIL" in line for line in lines)
    assert any("新增失败 1 / 已知失败 0" in line for line in lines)


def test_render_pass_when_only_known_reds():
    lines = render({"new": [], "stale": [], "known": ["tests/a::t1"]}, stats={})
    assert any("verdict=PASS" in line for line in lines)
    assert any("新增失败 0 / 已知失败 1" in line for line in lines)


def test_registered_red_does_not_block(tmp_path):
    registry_test = json.loads(
        (Path(__file__).resolve().parents[2] / "eval/rules/known_reds_current.json").read_text(encoding="utf-8")
    )["registered"][0]["test"]
    path, _, name = registry_test.partition("::")
    cls = path[: -len(".py")].replace("/", ".") if path.endswith(".py") else path.replace("/", ".")
    report = _write_junit(tmp_path, [_CASE_FAIL.format(cls=cls, name=name.split("[")[0])])
    code, lines = report_from_junit(report)
    assert code == 0
    assert any("verdict=PASS" in line for line in lines)


def test_unregistered_red_blocks(tmp_path):
    report = _write_junit(tmp_path, [_CASE_FAIL.format(cls="tests.unit.test_totally_new", name="test_boom")])
    code, lines = report_from_junit(report)
    assert code == 1
    assert any("verdict=FAIL" in line for line in lines)
    assert any("tests/unit/test_totally_new::test_boom" in line for line in lines)


def test_missing_report_fails_closed(tmp_path):
    code, lines = report_from_junit(tmp_path / "nope.xml")
    assert code == 2
    assert any("无法解析" in line for line in lines)
