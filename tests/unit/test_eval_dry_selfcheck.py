"""P2-5(2026-08-15) eval dry 注入可见性自检测试（零 LLM 零网络）.

覆盖:
- _dry_injection_selfcheck 对真实 ArchitectureStatusProvider + 快照生产路径通过
- evaluate(dry=True) 路径开头调用 selfcheck（mock 验证 + 管道跑通）
- 注入不可见时如实抛 RuntimeError（防 dry 假绿）
- wilson_ci 退化语义与实现一致（docstring 漂移修复的回归锚点）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）

_SCENARIOS = Path(__file__).resolve().parents[2] / "tests" / "eval_sets" / "scenarios_v1.json"


def test_dry_injection_selfcheck_passes():
    """真实 StatusTracker + architecture_status 快照生产路径: 注入的 FAILURE 可见."""
    # 不抛即通过（内部断言 FAILURE=2 + exception_log=1 均可见）
    run_eval._dry_injection_selfcheck()


def test_dry_injection_selfcheck_raises_when_invisible(monkeypatch):
    """注入不可见（此处以 _apply_setup 失效模拟注入链路断裂）→ 如实抛 RuntimeError."""
    monkeypatch.setattr(run_eval, "_apply_setup", lambda engine, setup: None)
    with pytest.raises(RuntimeError, match="自检失败"):
        run_eval._dry_injection_selfcheck()


def test_dry_injection_selfcheck_uses_same_injection_calls(monkeypatch):
    """注入调用与 run_one_sample 完全一致（复用 _apply_setup，inject_failures=2+exception）."""
    captured: list[dict] = []
    orig = run_eval._apply_setup

    def _spy(engine, setup: dict | None) -> None:
        captured.append(dict(setup or {}))
        return orig(engine, setup)

    monkeypatch.setattr(run_eval, "_apply_setup", _spy)
    run_eval._dry_injection_selfcheck()  # 原注入逻辑照常执行 → 不抛即通过

    assert captured == [{"inject_failures": 2, "inject_exception": True}]


def test_dry_evaluate_runs_selfcheck(tmp_path):
    """dry evaluate 路径开头调用 selfcheck（mock 验证被调用）且管道跑通."""
    scenarios = json.loads(_SCENARIOS.read_text(encoding="utf-8"))
    with mock.patch.object(run_eval, "_dry_injection_selfcheck") as sc:
        out = run_eval.evaluate(scenarios, dry=True, samples_override=2, workdir=tmp_path)

    sc.assert_called_once_with()
    assert out["dry"] is True
    assert len(out["results"]) >= 6
    for r in out["results"]:
        assert r["samples"] == 2
        assert 0 <= r["rate"] <= 1
        assert len(r["ci"]) == 2


def test_wilson_ci_degenerate_semantics_match_impl():
    """P2-5: wilson_ci 退化语义与实现一致（docstring 漂移修复的回归锚点）.

    - n<=0 / k<0 → (0.0, 0.0)（样本不足/非法输入不编造区间）
    - k=0 且 n>0 → 正常计算真实区间（k=0, n=3 → (0.0, 0.562]）
    """
    from llm_loop.eval.verdicts import wilson_ci

    assert wilson_ci(0, 0) == (0.0, 0.0)
    assert wilson_ci(3, 0) == (0.0, 0.0)
    assert wilson_ci(-1, 3) == (0.0, 0.0)

    lo, hi = wilson_ci(0, 3)
    assert lo == 0.0
    assert abs(hi - 0.562) < 0.01
