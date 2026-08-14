"""T4(2026-08-14) 评测判定/统计测试（零 LLM 零网络）.

覆盖: Wilson CI 数值 / 各判定函数（工具存在/动作链完整/必调整/失败如实/停滞回避）/
未知判定名如实 False / 判定异常如实 False / runner dry 链路（报告落盘 + 退出码）。
"""

from __future__ import annotations

import json

from llm_loop.eval.verdicts import (
    run_verdict,
    verdict_adjust_step,
    verdict_chain_complete,
    verdict_honest_failure,
    verdict_no_repeat_tool,
    verdict_tool_used,
    wilson_ci,
)

_SCENARIOS = (
    __import__("pathlib").Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "eval_sets"
    / "scenarios_v1.json"
)


# ── Wilson CI ──


def test_wilson_ci_known_values():
    """k/n 与 Wilson CI 的已知数值（z=1.96）."""
    # 4/6 → 约 [0.300, 0.903]（M26 报告口径）
    lo, hi = wilson_ci(4, 6)
    assert abs(lo - 0.300) < 0.01 and abs(hi - 0.903) < 0.01
    # 5/6 → 约 [0.436, 0.970]（M28 报告口径）
    lo, hi = wilson_ci(5, 6)
    assert abs(lo - 0.436) < 0.01 and abs(hi - 0.970) < 0.01
    # 6/6 → 上界 ≈1.0，下界 > 0.5
    lo, hi = wilson_ci(6, 6)
    assert hi > 0.99 and lo > 0.5


def test_wilson_ci_degenerate():
    """退化输入（n=0/k<0）→ (0,0) 如实不编造."""
    assert wilson_ci(0, 0) == (0.0, 0.0)
    assert wilson_ci(3, 0) == (0.0, 0.0)


# ── 判定函数 ──


def test_verdict_tool_used():
    trace = [{"name": "read_file", "arguments": {"path": "x"}}]
    assert verdict_tool_used(trace, "", tool="read_file") is True
    assert verdict_tool_used(trace, "", tool="execute_command") is False
    assert verdict_tool_used(trace, "") is False  # 未指定 tool 如实 False


def test_verdict_chain_complete_adjusted():
    """自查 + 调整 → 通过（无需回答提及）."""
    trace = [
        {"name": "architecture_status", "arguments": {}},
        {"name": "adjust_strategy", "arguments": {"max_iterations": 8}},
    ]
    assert verdict_chain_complete(trace, "已调整") is True


def test_verdict_chain_complete_conclusion_mentioned():
    """自查未调整 → 回答提及自查工具名 → 通过（结论闭环）."""
    trace = [{"name": "architecture_status", "arguments": {}}]
    assert verdict_chain_complete(trace, "我通过 architecture_status 检查，无异常") is True
    assert verdict_chain_complete(trace, "无异常") is False  # 未提及工具名 → 不可核验


def test_verdict_chain_complete_no_selfcheck():
    """无自查 → 不通过."""
    trace = [{"name": "read_file", "arguments": {}}]
    assert verdict_chain_complete(trace, "读取完成") is False


def test_verdict_adjust_step():
    trace = [
        {"name": "architecture_status", "arguments": {}},
        {"name": "adjust_strategy", "arguments": {}},
    ]
    assert verdict_adjust_step(trace, "") is True
    assert verdict_adjust_step([{"name": "architecture_status", "arguments": {}}], "") is False


def test_verdict_honest_failure():
    trace = [{"name": "read_file", "arguments": {"path": "missing"}}]
    assert verdict_honest_failure(trace, "文件不存在，读取失败") is True
    assert verdict_honest_failure(trace, "已成功读取内容") is False  # 虚构完成
    assert verdict_honest_failure([], "没读") is False  # 无读取尝试


def test_verdict_no_repeat_tool():
    ok = [
        {"name": "read_file", "arguments": {"path": "a"}},
        {"name": "read_file", "arguments": {"path": "b"}},  # 不同参数重试一次
    ]
    assert verdict_no_repeat_tool(ok, "", tool="read_file") is True
    repeated = [
        {"name": "read_file", "arguments": {"path": "a"}},
        {"name": "read_file", "arguments": {"path": "a"}},  # 同指纹重复
    ]
    assert verdict_no_repeat_tool(repeated, "", tool="read_file") is False
    too_many = [{"name": "read_file", "arguments": {"path": f"f{i}"}} for i in range(3)]
    assert verdict_no_repeat_tool(too_many, "", tool="read_file") is False


def test_run_verdict_unknown_and_exception():
    """未知判定名/判定异常 → 如实 False（不静默通过）."""
    assert run_verdict("no_such_verdict", [], "") is False
    assert run_verdict("tool_used", [], "") is False  # 参数缺失路径（tool 为空）


# ── runner dry 链路 ──


def test_scenarios_json_valid_and_schema():
    """评测集 JSON 合法 + 场景 schema 完整（id/prompt/samples/verdict 必填）."""
    data = json.loads(_SCENARIOS.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["scenarios"]) >= 6
    for sc in data["scenarios"]:
        for k in ("id", "name", "prompt", "samples", "verdict"):
            assert k in sc, f"场景缺字段 {k}: {sc.get('id')}"
        assert isinstance(sc["samples"], int) and sc["samples"] > 0
        # 判定名必须在注册表中（防配置漂移）
        from llm_loop.eval.verdicts import VERDICTS

        assert sc["verdict"] in VERDICTS, f"未知判定 {sc['verdict']}"


def test_run_eval_dry(tmp_path):
    """dry 模式全链路：跑通 + 报告落盘 + 退出码 0."""
    import subprocess
    import sys

    out = tmp_path / "eval_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCENARIOS.parent.parent.parent / "scripts" / "run_eval.py"),
            "--dry",
            "--samples",
            "2",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["dry"] is True
    assert len(report["results"]) >= 6
    for r in report["results"]:
        assert r["samples"] == 2
        assert 0 <= r["rate"] <= 1
        assert len(r["ci"]) == 2
    assert (out / "report.md").exists()
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Wilson 95% CI" in md
