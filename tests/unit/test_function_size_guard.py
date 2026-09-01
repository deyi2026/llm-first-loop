"""函数级防膨胀守卫（AST 实测 + 基线外置 + 单向棘轮）.

为什么需要这个文件
------------------
既有守卫 `test_complexity_reduction`（tests/unit/test_loop_mixin_split.py）只量
**engine.py 单个文件的行数**。实测证明该口径已被绕过：

    src/llm_loop/core/loop/build.py::_build_llm_messages   1732 行
    src/llm_loop/core/loop/engine.py::_run_stream_inner    1135 行
    src/llm_loop/factory.py::build_engine                  1004 行
    src/llm_loop/core/history.py::build_history_messages    721 行

前 4 名全部位于「已经按守卫要求拆过」的文件里——2026-08-18 那次 engine.py 拆分
只是把代码在文件之间搬家，函数从未变小。文件级口径量不出这件事。

本守卫改为 **AST 函数级** 口径，并针对旧守卫的两个失效模式做设计：

1. 基线写在测试源码里 → 改一个数字就是一次普通提交，零摩擦。
   本守卫把基线外置到 `tests/guards/function_size_baseline.json`，
   并在 `test_baseline_ratchet_not_raised` 中与 git HEAD 版本逐键比对，
   **只允许下降，不允许升高**。

2. 硬基线会被「先改数字、后补拆分」架空（旧守卫 docstring 的「基线失真」
   正是这么来的）。本守卫保留一条**不可豁免的硬顶** HARD_CAP，
   超过即 CI 红，没有调参通道——只能拆。

如需临时上调某个函数的限额，走 `exemptions`（带 reason + expires，
最长 30 天）。到期未清除 → 测试失败。这样「放宽守卫」变成一次
**可见的、有理由的、有期限的**动作，而不是一次普通提交。

收录标准: 单函数 ≥ INCLUDE_THRESHOLD(150) 行。
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

# tests/unit/test_function_size_guard.py → parents[2] = 仓库根
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BASELINE_PATH = ROOT / "tests" / "guards" / "function_size_baseline.json"

# 绝对红线：任何函数不得超过此行数。无豁免通道，超限只能拆分。
# 当前最大函数 1732 行，留 ~15% 余量给正常的特性增量。
HARD_CAP = 2000

# 收录基线的门槛（低于此值的函数不纳入基线，避免过度约束）
INCLUDE_THRESHOLD = 150

# 豁免有效期上限（天）
MAX_EXEMPTION_DAYS = 30


def _measure() -> dict[str, int]:
    """AST 实测 src/ 下所有函数的行数，返回 {key: lines}。"""
    out: dict[str, int] = {}
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 语法错误由 lint/CI 负责，守卫不重复报错
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = getattr(n, "end_lineno", n.lineno) - n.lineno + 1
                out[f"{p.relative_to(ROOT).as_posix()}::{n.name}"] = lines
    return out


def _load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.exists():
        pytest.fail(f"基线文件缺失: {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _valid_exemptions(baseline: dict[str, Any], today: _dt.date) -> dict[str, int]:
    """返回 {key: 豁免后允许的最大行数}，已过期的豁免不计入。"""
    out: dict[str, int] = {}
    for ex in baseline.get("exemptions", []):
        try:
            expires = _dt.date.fromisoformat(ex["expires"])
        except Exception:  # noqa: BLE001
            continue  # 格式错误由 test_exemptions_wellformed 负责报错
        if expires >= today:
            out[ex["key"]] = max(out.get(ex["key"], 0), int(ex["limit"]))
    return out


@pytest.fixture(scope="module")
def measured() -> dict[str, int]:
    return _measure()


def test_hard_cap(measured: dict[str, int]):
    """硬顶：任何函数不得超 HARD_CAP 行。无豁免通道——超限只能拆。"""
    over = {k: v for k, v in measured.items() if v > HARD_CAP}
    assert not over, (
        f"{len(over)} 个函数超过硬顶 {HARD_CAP} 行（不可豁免，必须拆分）：\n"
        + "\n".join(f"  {v} 行  {k}" for v, k in sorted(((v, k) for k, v in over.items()), reverse=True))
    )


def test_functions_within_baseline(measured: dict[str, int]):
    """每个已收录函数不得超过基线值（或有效豁免限额）。"""
    baseline = _load_baseline()
    base: dict[str, int] = baseline.get("functions", {})
    exempt = _valid_exemptions(baseline, _dt.date.today())

    violations: list[str] = []
    for key, limit in base.items():
        cur = measured.get(key)
        if cur is None:
            continue  # 函数已被拆分/删除——这是好事，不报错
        allowed = max(limit, exempt.get(key, 0))
        if cur > allowed:
            violations.append(f"  {cur} 行（基线 {limit}，允许 {allowed}）  {key}")

    assert not violations, (
        f"{len(violations)} 个函数超过基线（基线只降不升；确需上调请走 exemptions 并写明理由与到期日）：\n"
        + "\n".join(violations)
    )


def test_new_large_functions_must_be_recorded(measured: dict[str, int]):
    """新出现的 ≥INCLUDE_THRESHOLD 行函数必须登记进基线（防止无人看守的膨胀）。"""
    baseline = _load_baseline()
    base: dict[str, int] = baseline.get("functions", {})
    new = {
        k: v for k, v in measured.items() if v >= INCLUDE_THRESHOLD and k not in base
    }
    assert not new, (
        f"{len(new)} 个函数已达 {INCLUDE_THRESHOLD} 行但未登记基线。"
        f"请将其当前行数写入 {BASELINE_PATH.name}：\n"
        + "\n".join(f'  "{k}": {v},' for k, v in sorted(new.items(), key=lambda x: -x[1]))
        + "\n登记即锁定为后续上限（只降不升）。"
    )


def test_baseline_ratchet_not_raised():
    """棘轮：与 git HEAD 版本逐键比对，基线值只允许下降，不允许升高。

    旧守卫失效的根因是「改测试里的一个数字」和「改业务逻辑」是同一种提交，
    没有任何摩擦。这里把摩擦补上：任何上调都会在 PR diff 里显式暴露。
    """
    rel = BASELINE_PATH.relative_to(ROOT).as_posix()
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"基线文件尚未提交到 git（{rel}），提交后棘轮生效")

    head_base: dict[str, int] = json.loads(proc.stdout).get("functions", {})
    cur_base: dict[str, int] = _load_baseline().get("functions", {})

    raised = [
        f"  {k}: {head_base[k]} → {cur_base[k]}（+{cur_base[k] - head_base[k]}）"
        for k in head_base
        if k in cur_base and cur_base[k] > head_base[k]
    ]
    assert not raised, (
        "基线被上调（棘轮只允许下降）。如为有意放宽，请改用 exemptions 并写明"
        "理由与到期日，不要直接改基线值：\n" + "\n".join(raised)
    )


def test_exemptions_wellformed():
    """豁免条目必须字段完整、格式合法、期限不超过 MAX_EXEMPTION_DAYS 天。"""
    baseline = _load_baseline()
    today = _dt.date.today()
    problems: list[str] = []

    for i, ex in enumerate(baseline.get("exemptions", [])):
        for field in ("key", "limit", "reason", "expires"):
            if field not in ex:
                problems.append(f"  exemptions[{i}] 缺字段 {field}")
        if "expires" in ex:
            try:
                expires = _dt.date.fromisoformat(ex["expires"])
                if expires < today:
                    problems.append(
                        f"  exemptions[{i}] 已于 {ex['expires']} 过期，请清除或续期（附新理由）"
                    )
                elif (expires - today).days > MAX_EXEMPTION_DAYS:
                    problems.append(
                        f"  exemptions[{i}] 期限 {(expires - today).days} 天，"
                        f"超过上限 {MAX_EXEMPTION_DAYS} 天"
                    )
            except ValueError:
                problems.append(f"  exemptions[{i}].expires 日期格式非法: {ex['expires']!r}")
        if "reason" in ex and len(str(ex["reason"]).strip()) < 10:
            problems.append(f"  exemptions[{i}].reason 过短，需说明为何不能拆、何时拆")

    assert not problems, "豁免条目存在问题：\n" + "\n".join(problems)
