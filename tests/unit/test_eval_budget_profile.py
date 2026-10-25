"""预算对齐回归测试（零 LLM 零网络）.

背景（预算对齐）: scripts/run_eval.py 此前把评测基准轮数硬编码 10，与产品默认
（Settings.max_iterations / LLM_MAX_ITERATIONS，缺省 500）脱节 → "预算不足截断"
与"能力失败"在报告里无法区分，Δpass@1 也不能直接迁移到产品预算结论。

本次对齐的两个正交开关:
- --budget-profile {product,pinned10}（默认 product）只决定**基准预算**:
  product=产品默认；pinned10=10 复现历史跑批行为
- --ignore-scenario-pins（默认关）只决定**是否忽略场景 pin**
  （held-out A 级口径: --budget-profile product --ignore-scenario-pins）

覆盖（委派验收清单）:
- 默认 = 产品预算（env 与字段默认两条解析路径）
- pinned10 生效
- pin honored 路径 / pin ignored 路径（解析层 + runner 实际收到值两层）
- budget 块字段齐全（恰好六键）
- main() --dry 端到端: report.json budget 块 + report.md 预算行 +
  偏离产品默认时 Δpass@1 声明在场 / 对齐时缺席
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）

_BUDGET_KEYS = {
    "product_default",
    "base",
    "profile",
    "scenario_pins",
    "pins_honored",
    "effective_by_scenario",
}


def _scenarios(pins: list) -> dict:
    """构造场景集（pins 元素 None = 该场景不写 max_iterations）."""
    scs = []
    for i, pin in enumerate(pins):
        sc = {
            "id": f"sc_{i}",
            "name": f"场景{i}",
            "verdict": "chain_complete",
            "prompt": "p",
            "samples": 1,
            "params": {},
        }
        if pin is not None:
            sc["max_iterations"] = pin
        scs.append(sc)
    return {"name": "budget-test", "version": "v0", "baseline_ref": "", "scenarios": scs}


def _fake_runner(calls: list):
    """记录 max_iterations 实参的假 runner（与既有 checkpoint 测试同套路）."""

    def _run(prompt, workdir, key, setup=None, max_iterations=None):
        calls.append(max_iterations)
        return {
            "trace": [{"name": "read_file", "arguments": {}}],
            "answer": "答案",
            "model_used": "fake-model",
            "rounds": 1,
            "truncated": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }

    return _run


# ── 产品默认预算解析 ────────────────────────────────────────────


def test_product_default_from_env(monkeypatch):
    """LLM_MAX_ITERATIONS 显式设置 → 产品默认取该值（与 from_env 同口径）."""
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "777")
    assert run_eval._product_default_max_iterations() == 777


def test_product_default_dirty_env_falls_back(monkeypatch):
    """脏值（非整数）→ 如实回落字段默认，不猜."""
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "not-an-int")
    assert run_eval._product_default_max_iterations() == 500


def test_product_default_missing_env_uses_settings_field(monkeypatch):
    """未设置 → Settings.max_iterations 字段默认（与 runtime.toml 同源 = 500）."""
    monkeypatch.delenv("LLM_MAX_ITERATIONS", raising=False)
    from llm_loop.config import Settings

    field_default = next(
        f.default for f in dataclasses.fields(Settings) if f.name == "max_iterations"
    )
    assert field_default == 500
    assert run_eval._product_default_max_iterations() == field_default


# ── 预算解析矩阵（_resolve_run_budget 纯函数） ──────────────────


def test_default_profile_uses_product_budget():
    """默认（product + pin honored）：基准=产品默认，pin 场景用 pin，无 pin 用基准."""
    b = run_eval._resolve_run_budget(
        _scenarios([12, None]),
        product_default=500,
        profile="product",
        ignore_scenario_pins=False,
        force_max_iterations=None,
    )
    assert b["product_default"] == 500
    assert b["base"] == 500
    assert b["profile"] == "product"
    assert b["scenario_pins"] == {"sc_0": 12}
    assert b["pins_honored"] is True
    assert b["effective_by_scenario"] == {"sc_0": 12, "sc_1": 500}


def test_pinned10_profile_reproduces_legacy_behavior():
    """pinned10：基准=10（复现历史跑批）；场景 pin 仍 honored（旧行为 pin 也生效）."""
    b = run_eval._resolve_run_budget(
        _scenarios([12, None]),
        product_default=500,
        profile="pinned10",
        ignore_scenario_pins=False,
        force_max_iterations=None,
    )
    assert b["base"] == 10
    assert b["pins_honored"] is True
    assert b["effective_by_scenario"] == {"sc_0": 12, "sc_1": 10}


def test_ignore_scenario_pins():
    """--ignore-scenario-pins：忽略 pin，全部场景用基准（与 profile 正交）."""
    b = run_eval._resolve_run_budget(
        _scenarios([12, None]),
        product_default=500,
        profile="product",
        ignore_scenario_pins=True,
        force_max_iterations=None,
    )
    assert b["pins_honored"] is False
    assert b["scenario_pins"] == {"sc_0": 12}  # 原始 pin 仍如实记录
    assert b["effective_by_scenario"] == {"sc_0": 500, "sc_1": 500}


def test_force_max_iterations_overrides_all():
    """--max-iterations 显式覆盖：优先级最高，忽略 pin（保留旧行为语义）."""
    b = run_eval._resolve_run_budget(
        _scenarios([12, None]),
        product_default=500,
        profile="pinned10",
        ignore_scenario_pins=False,
        force_max_iterations=25,
    )
    assert b["base"] == 25
    assert b["pins_honored"] is False
    assert b["effective_by_scenario"] == {"sc_0": 25, "sc_1": 25}


def test_budget_block_field_set_complete():
    """budget 块字段齐全（恰好六键，类型正确）."""
    b = run_eval._resolve_run_budget(
        _scenarios([12]),
        product_default=500,
        profile="product",
        ignore_scenario_pins=False,
        force_max_iterations=None,
    )
    assert set(b.keys()) == _BUDGET_KEYS
    assert isinstance(b["product_default"], int)
    assert isinstance(b["base"], int)
    assert isinstance(b["profile"], str)
    assert isinstance(b["pins_honored"], bool)
    assert all(isinstance(v, int) for v in b["scenario_pins"].values())
    assert all(isinstance(v, int) for v in b["effective_by_scenario"].values())


# ── evaluate 接线（runner 实际拿到的预算） ──────────────────────


def test_evaluate_default_budget_is_product(monkeypatch, tmp_path):
    """evaluate 不传 budget → 默认产品口径（env 值即基准；pin honored）."""
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "321")
    calls: list = []
    orig = run_eval.run_dry_sample
    run_eval.run_dry_sample = _fake_runner(calls)
    try:
        out = run_eval.evaluate(
            _scenarios([12, None]), dry=True, samples_override=1, workdir=tmp_path
        )
    finally:
        run_eval.run_dry_sample = orig
    assert calls == [12, 321]  # pin 场景用 pin，无 pin 场景用产品默认
    assert out["budget"]["product_default"] == 321
    assert out["budget"]["base"] == 321
    assert out["budget"]["effective_by_scenario"] == {"sc_0": 12, "sc_1": 321}


def test_evaluate_runner_receives_effective_budget(tmp_path):
    """pin honored vs ignored：runner 收到的正是 effective_by_scenario."""
    scenarios = _scenarios([12, None])
    for ignore_pins, expected in ((False, [12, 500]), (True, [500, 500])):
        budget = run_eval._resolve_run_budget(
            scenarios,
            product_default=500,
            profile="product",
            ignore_scenario_pins=ignore_pins,
            force_max_iterations=None,
        )
        calls: list = []
        orig = run_eval.run_dry_sample
        run_eval.run_dry_sample = _fake_runner(calls)
        try:
            out = run_eval.evaluate(
                scenarios,
                dry=True,
                samples_override=1,
                workdir=tmp_path,
                budget=budget,
            )
        finally:
            run_eval.run_dry_sample = orig
        assert calls == expected
        assert out["budget"]["effective_by_scenario"] == {
            "sc_0": expected[0],
            "sc_1": expected[1],
        }


# ── main() dry 端到端（JSON budget 块 + MD 渲染） ───────────────


def _run_main_dry(monkeypatch, tmp_path, name: str, extra_args: list) -> tuple[dict, str]:
    """跑一次 --dry main()，返回 (report.json dict, report.md text).

    快照/恢复 os.environ：main() 内部 load_env_file() 会把 .env 写进进程环境
    （已设置的键不覆盖），不能让这份副作用泄漏给同进程的其它测试。
    """
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "321")
    scen = tmp_path / f"scen_{name}.json"
    scen.write_text(json.dumps(_scenarios([12, None]), ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / f"out_{name}"
    saved = dict(os.environ)
    try:
        rc = run_eval.main(
            [
                "--dry",
                "--scenarios",
                str(scen),
                "--output",
                str(out_dir),
                "--samples",
                "1",
                *extra_args,
            ]
        )
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert rc == 0
    rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    md = (out_dir / "report.md").read_text(encoding="utf-8")
    return rep, md


def test_main_dry_default_writes_budget_block_and_disclaimer(monkeypatch, tmp_path):
    """默认口径端到端：JSON 含 budget 块；pin 场景预算≠产品默认 → MD 必须有 Δpass@1 声明."""
    rep, md = _run_main_dry(monkeypatch, tmp_path, "default", [])
    b = rep["budget"]
    assert set(b.keys()) == _BUDGET_KEYS
    assert b["product_default"] == 321
    assert b["base"] == 321
    assert b["profile"] == "product"
    assert b["scenario_pins"] == {"sc_0": 12}
    assert b["pins_honored"] is True
    assert b["effective_by_scenario"] == {"sc_0": 12, "sc_1": 321}
    assert "profile=product" in md
    assert "base=321" in md
    assert "product_default=321" in md
    assert "Δpass@1" in md  # sc_0 有效预算 12 ≠ 321 → 声明必须在场


def test_main_dry_aligned_budget_no_disclaimer(monkeypatch, tmp_path):
    """对齐口径（--ignore-scenario-pins）：全部=产品默认 → 不得出现 Δpass@1 声明."""
    rep, md = _run_main_dry(monkeypatch, tmp_path, "aligned", ["--ignore-scenario-pins"])
    b = rep["budget"]
    assert b["pins_honored"] is False
    assert b["scenario_pins"] == {"sc_0": 12}  # pin 仍如实记录，只是不生效
    assert b["effective_by_scenario"] == {"sc_0": 321, "sc_1": 321}
    assert "profile=product" in md
    assert "Δpass@1" not in md


def test_main_dry_pinned10_profile(monkeypatch, tmp_path):
    """--budget-profile pinned10 端到端：基准=10，pin 仍 honored，声明在场（12/10 ≠ 321）."""
    rep, md = _run_main_dry(
        monkeypatch, tmp_path, "pinned10", ["--budget-profile", "pinned10"]
    )
    b = rep["budget"]
    assert b["product_default"] == 321
    assert b["base"] == 10
    assert b["profile"] == "pinned10"
    assert b["pins_honored"] is True
    assert b["effective_by_scenario"] == {"sc_0": 12, "sc_1": 10}
    assert "profile=pinned10" in md
    assert "base=10" in md
    assert "Δpass@1" in md
