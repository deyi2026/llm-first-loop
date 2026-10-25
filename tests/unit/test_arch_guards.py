"""R9 架构守卫（AST 实测 + 基线外置 v2 + 单向棘轮 + 防篡改三层）.

前身 `test_function_size_guard.py`（workbuddy 雏形，B2-P1-01 收编）经 git mv
更名扩展——文件历史可追溯。v2 基线五节（design T3-C）：

- ``function_lines``：全函数 ≥120 行登记（三层红线联动阈值）
- ``legacy_super_functions``：实测 >300 超大函数棘轮（EVO-20261025-e0bff8ee
  起由原四函数 build/engine/factory/history 扩展为全量登记）
- ``local_imports``：文件级函数内 import 总量（只减不增；豁免仅 optional/plugin）
- ``known_cycles``：环登记（Phase 3 断两环后清空并断言空）
- ``exemptions``：OQ-7 强约束豁免清单（reason ≥10 字符 + deadline ≤30 天 + 数量单调不增）

防篡改三层：
1. 数据外置——基线数值不在测试源码（`_base=1361` 教训）；
2. 棘轮 git HEAD 比对——任何数值节较 HEAD 上升即 FAIL，无论实测如何
   （先堵"改数字让测试通过"路径，本文件 ``test_baseline_ratchet_not_raised``）；
3. 守卫文件保护——基线 JSON 与本文件修改必须 `guard(r9):` 前缀提交
   （`scripts/r9_commit_check.sh` 规则④机检）。

外部演进合流冲击预案（R-2）若触发（外部提交使 HEAD 破基线）：登记偏差 →
判定"外部入库膨胀"（非 R9 违规，R9 提交链机检可自证）→ EVO + 交用户裁决。
**基线不上调**（裁决 4 无条件）。
"""

from __future__ import annotations

import ast
import functools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# tests/unit/test_arch_guards.py → parents[2] = 仓库根
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BASELINE_PATH = ROOT / "tests" / "guards" / "function_size_baseline.json"

# 收录基线的门槛（v2：与三层红线 WARN 下限联动，150 → 120）
INCLUDE_THRESHOLD = 120

# ── 历史函数尺寸分类器（仅诊断/合成夹具，不再对真实源码形成 CI 形状门）──
# 这些阈值保留用于 guard_report 与合成树回归，帮助审查复杂度趋势；不得为了
# 通过测试而拆分生产函数、登记豁免或改变模型/运行时语义。
GLOBAL_FAIL = 300
CORE_FAIL = 200
CORE_WARN_LO, CORE_WARN_HI = 120, 150
# core 文件清单（R9-P2-04 全覆盖口径：旧守卫"只量 engine.py"盲区消除；后续
# 新域包在此常量追加——数据外置于源码常量而非基线 JSON，因它是"设防面"而非
# "棘轮值"，变更本身须过 guard(r9) 前缀机检）
CORE_FILES: tuple[str, ...] = (
    "src/llm_loop/core/loop/",  # 前缀匹配：整个 loop 域
    "src/llm_loop/core/history.py",
    "src/llm_loop/factory.py",
    "src/llm_loop/tools/registry.py",
)

# 数值节清单（防篡改层 2 的 HEAD 比对范围）
NUMERIC_SECTIONS = ("function_lines", "legacy_super_functions", "local_imports")


def _is_core(rel_key: str) -> bool:
    """rel_key 形如 'src/llm_loop/core/loop/engine.py::_run_stream_inner'。"""
    return any(rel_key.startswith(p) or rel_key == p for p in CORE_FILES)


def _classify_redlines(
    measured: dict[str, int], registered_keys: frozenset[str] | None = None
) -> tuple[list[str], list[str]]:
    """三层红线分类：返回 (failures, warns)。纯函数——tmp_path 构造树单测直调。

    **红线管辖 = 未登记函数（防新增膨胀）**；已登记函数（function_lines ∪
    legacy_super_functions）归棘轮管辖（`test_function_lines_ratchet_within_baseline`
    零增长断言——比红线更严：214 行登记函数长到 215 即红，无需等 300）。
    legacy 为实测 >300 的超大函数棘轮（原四函数 build/engine/factory/history，
    EVO-20261025-e0bff8ee 扩展全量登记并按实测重定：721→745 / 866→2219 /
    1004→2157，_build_llm_messages 199→197 收缩回 function_lines；清单与数值
    以基线 JSON 为准，此处数字仅为重登记时点快照），Phase 6/7 拆分目标
    （D10 收编延续：v1 硬顶 2000 从不拦 1732 存量——红线语义自始是防新增）。
    """
    if registered_keys is None:
        b = _load_baseline()
        registered_keys = frozenset(b["function_lines"]) | frozenset(b["legacy_super_functions"])
    failures, warns = [], []
    for key, lines in measured.items():
        if key in registered_keys:
            continue
        if lines > GLOBAL_FAIL:
            failures.append(f"  [全局红线>{GLOBAL_FAIL}] {key}: {lines}")
        elif _is_core(key):
            if lines > CORE_FAIL:
                failures.append(f"  [core红线>{CORE_FAIL}] {key}: {lines}")
            elif CORE_WARN_LO <= lines <= CORE_WARN_HI:
                warns.append(f"  [core WARN {CORE_WARN_LO}-{CORE_WARN_HI}] {key}: {lines}")
    return failures, warns


@pytest.mark.guard_report
def test_core_warn_report_120_150():
    """core 层 WARN 区间报告（guard_report marker 独立呈现，不阻断；T3-A 口径）。

    WARN ≠ 违例：120-150 是"审查提醒带"——首行可见于 -m guard_report 运行，
    CI 常驻报告中呈现（spec §5.3.3-1c 可见性），FAIL 用例默认跑不受影响。
    """
    _, warns = _classify_redlines(_measure_functions_cached())
    if warns:
        print(f"\ncore 层 WARN（{len(warns)} 处，审查提醒不阻断）：\n" + "\n".join(warns))


def test_redline_synthetic_trees(tmp_path):
    """tmp_path 构造树承载 EARS 断言面（R9-P2-01a/02a 三形态）。

    - 301 行全局函数 → 全局 FAIL
    - core 文件 201 行函数 → core FAIL
    - core 文件 130 行函数 → WARN（非 FAIL）
    - 非 core 文件 250 行函数 → 仅全局面之外合法（<300 不 FAIL 不 WARN）
    """
    core = tmp_path / "src/llm_loop/core/loop"
    other = tmp_path / "src/llm_loop/other"
    core.mkdir(parents=True)
    other.mkdir(parents=True)

    def fn(name: str, lines: int) -> str:
        # 精确 lines 行：def + x=1 + (lines-3) 填充 + return
        return f"def {name}():\n    x = 1\n" + "    \n" * (lines - 3) + "    return x\n"

    (core / "a.py").write_text(fn("over_global", 301) + "\n\n" + fn("over_core", 201), encoding="utf-8")
    (core / "b.py").write_text(fn("warn_zone", 130), encoding="utf-8")
    (other / "c.py").write_text(fn("ok_below_global", 250), encoding="utf-8")

    m = _measure_functions(tmp_path / "src")
    failures, warns = _classify_redlines(m)
    fkeys = " ".join(failures)
    assert "over_global" in fkeys and "全局红线" in fkeys
    assert "over_core" in fkeys and "core红线" in fkeys
    assert not any("warn_zone" in f for f in failures)
    assert any("warn_zone" in w and "WARN" in w for w in warns)
    assert not any("ok_below_global" in f for f in failures)
    assert not any("ok_below_global" in w for w in warns)


# ── 守卫读源口径（B2-P2-06 / D-07 机制化）───────────────────────────────────
# 对 git status 中 M 状态且未 staged 的 src/llm_loop 文件（外部漂移，如
# factory.py working 1031）回退读 git HEAD 版本——效果：外部漂移不触发守卫红
# （守卫测 HEAD 1004），真实违规（staged/已提交内容）全量设防。动态判定，
# 不维护静态清单（防腐化）。


@functools.lru_cache(maxsize=1)
def _git_porcelain() -> list[str]:
    """会话级缓存（只读守卫进程内 porcelain 稳定；R9-DFX-16 性能——254 文件
    单次判定，免每文件 spawn git status）。"""
    proc = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=ROOT
    )
    return proc.stdout.splitlines()


def _external_unstaged_src(porcelain: list[str]) -> frozenset[str]:
    """porcelain 行 → M 状态且不在 staged 集的 src/llm_loop 文件集（纯函数）。

    XY 码：X=staged / Y=worktree。判定 = Y=='M' 且 X 不在 {'M','A'}（' M' 纯
    外部漂移 → HEAD 口径；'M '/'MM' 含 staged 内容 → working 口径——staged 集
    是将要提交的现实，守卫必须设防）。
    """
    out: list[str] = []
    for ln in porcelain:
        if len(ln) > 3 and ln[1] == "M" and ln[0] not in ("M", "A"):
            path = ln[3:]
            if path.startswith("src/llm_loop"):
                out.append(path)
    return frozenset(out)


_head_caliber_noted: set[str] = set()


def _note_head_caliber(rel: str) -> None:
    """EVO-20261014-f96d8158：按 HEAD 口径读 unstaged 漂移文件时提示一次（防假阴性排障损耗）。

    只加可观测性，不改 XY→口径判定语义（安全设计保留）：提示排障者
    「修复若仅在工作树，守卫读到的是 HEAD 旧内容，先 stage 再复验」。
    同文件去重，正常 clean 工作树零输出。
    """
    if rel in _head_caliber_noted:
        return
    _head_caliber_noted.add(rel)
    print(
        f"note: {rel} 存在 unstaged 工作树改动，守卫按 HEAD（staged 现实）口径校验；"
        f"若你的修复仅在工作树，请 `git add {rel}` 后复验。",
        file=sys.stderr,
    )


def _read_source(rel: str) -> str:
    """守卫读源：外部漂移未 staged 文件回退 `git show HEAD:<rel>`，其余 working。"""
    if rel in _external_unstaged_src(_git_porcelain()):
        _note_head_caliber(rel)
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], capture_output=True, text=True, check=True, cwd=ROOT
        )
        return proc.stdout
    return (ROOT / rel).read_text(encoding="utf-8")



@functools.lru_cache(maxsize=1)
def _measure_functions_cached() -> dict[str, int]:
    """真实树实测的会话级缓存（R9-DFX-16：254 文件单遍共享，多检测器复用）。"""
    return _measure_functions()



def test_external_unstaged_pure_classification():
    """双口径切换纯函数断言面：' M'→HEAD / 'M '/'MM'→working / untracked 与非 src 不计。"""
    porcelain = [
        " M src/llm_loop/factory.py",      # 纯外部漂移 → HEAD
        "M  src/llm_loop/core/prompt.py",  # staged → working
        "MM src/llm_loop/config.py",       # staged 后又改 → working（含 staged 现实）
        "?? src/llm_loop/new.py",          # untracked → 不计（守卫测已提交树+staged）
        " M tests/unit/x.py",              # 非 src/llm_loop → 不计
        "A  src/llm_loop/added.py",        # 新增 staged → working
    ]
    assert _external_unstaged_src(porcelain) == {"src/llm_loop/factory.py"}


def test_read_source_dual_caliber_integration(monkeypatch):
    """双口径行为应由 porcelain 状态决定，不依赖当前共享工作树恰好谁是 clean。"""
    import sys

    mod = sys.modules[__name__]
    rel = "src/llm_loop/core/cache_health.py"
    show = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    ).stdout

    # 外部未 staged 漂移 → 守卫读 HEAD，避免把别的会话 working drift 归罪于本提交。
    monkeypatch.setattr(mod, "_git_porcelain", lambda: [f" M {rel}"])
    assert _read_source(rel) == show

    # 同一文件若不属于外部未 staged 集 → 读 working tree。
    monkeypatch.setattr(mod, "_git_porcelain", lambda: [])
    assert _read_source(rel) == (ROOT / rel).read_text(encoding="utf-8")


def test_read_source_head_caliber_note(monkeypatch, capsys):
    """EVO-20261014-f96d8158：HEAD 口径读源输出一行 stage 提示；同文件去重；working 口径无提示。"""
    mod = sys.modules[__name__]
    rel = "src/llm_loop/core/cache_health.py"

    monkeypatch.setattr(mod, "_git_porcelain", lambda: [f" M {rel}"])
    mod._head_caliber_noted.clear()
    try:
        _read_source(rel)
        first = capsys.readouterr()
        assert "git add" in first.err
        assert rel in first.err
        assert "HEAD" in first.err

        # 同文件第二次读：去重，不再输出
        _read_source(rel)
        assert capsys.readouterr().err == ""

        # 无漂移（working 口径）：无提示
        monkeypatch.setattr(mod, "_git_porcelain", lambda: [])
        _read_source(rel)
        assert capsys.readouterr().err == ""
    finally:
        mod._head_caliber_noted.clear()


def _measure_functions(root: Path | None = None) -> dict[str, int]:
    """AST 实测函数行数，返回 {key: lines}（R9-DFX-16 单遍解析共享入口）。

    key 形如 'src/llm_loop/...::name'：真实树以 ROOT/src 为基（**走守卫读源口径
    ——外部漂移未 staged 文件回退 HEAD**，D-07 收口）；tmp_path 构造树传入其
    src 目录直读文件，key 空间与真实树一致。
    """
    base = root if root is not None else SRC
    real = root is None
    out: dict[str, int] = {}
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        rel = f"src/{p.relative_to(base).as_posix()}"
        try:
            tree = ast.parse(_read_source(rel) if real else p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 语法错误由 lint/CI 负责，守卫不重复报错
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = getattr(n, "end_lineno", n.lineno) - n.lineno + 1
                out[f"{rel}::{n.name}"] = lines
    return out


def _load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.exists():
        pytest.fail(f"基线文件缺失: {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_v2_schema():
    """v2 五节齐全、数值节类型正确、meta 口径字段在位（B2-P2-01 验收）。"""
    b = _load_baseline()
    for sec in NUMERIC_SECTIONS + ("known_cycles", "exemptions"):
        assert sec in b, f"缺 v2 节: {sec}"
    for sec in NUMERIC_SECTIONS:
        assert isinstance(b[sec], dict) and b[sec], f"{sec} 应为非空 dict"
        assert all(isinstance(v, int) and v > 0 for v in b[sec].values()), f"{sec} 值应为正整数"
    assert isinstance(b["known_cycles"], list)
    assert isinstance(b["exemptions"], list)
    meta = b.get("_meta", {})
    assert meta.get("schema") == 2
    assert meta.get("ratchet") == "only-decrease"
    assert meta.get("head_compare") is True
    # legacy 四函数与 function_lines 不得重复登记（三层各司其职）
    overlap = set(b["legacy_super_functions"]) & set(b["function_lines"])
    assert not overlap, f"legacy 键不得同时出现在 function_lines: {overlap}"


# ── EVO-20261025-e0bff8ee：基线↔实测双向对账（堵"登记即豁免"）───────────────
# 漏洞链：_classify_redlines 只对未登记函数设红线，而登记值从不与实测对账——
# 任何函数一旦进 function_lines 即永久免于红线，死键还掩盖真实违规。本节把
# "登记"从豁免变成棘轮锚点：键必须存活、登记值必须 ≥ 实测、>300 必须进
# legacy、≥120 必须登记（阈值带内不得存在未登记增长）。


def _ratchet_problems(
    measured: dict[str, int],
    function_lines: dict[str, int],
    legacy: dict[str, int],
    include_threshold: int = INCLUDE_THRESHOLD,
) -> list[str]:
    """基线登记 × AST 实测双向对账，返回问题清单（纯函数，不 assert）。

    四规则（每条独立可红，合成数据单测 test_ratchet_rule_*）：
    a ``[死键]``：登记键（fl ∪ legacy）在实测中不存在——防死键掩盖真实违规；
    b ``[棘轮增长]``：实测 > 登记值——零增长，登记函数长 1 行即红（fl/legacy 同检）；
    c ``[超限未进legacy]``：function_lines 键的登记值或实测 >300——>300 只能进 legacy；
    d ``[未登记]``：实测 ≥ include_threshold 且不在 fl ∪ legacy——阈值带内不得
      未登记（<120 的存活历史小键允许保留在 fl，承载"曾经很大"的棘轮锚）。
    """
    problems: list[str] = []
    for key in sorted(set(function_lines) | set(legacy)):
        if key not in measured:
            problems.append(f"  [死键] {key}: 登记存在但实测不存在（请随拆分/删除提交清理）")
    for key, reg in sorted(function_lines.items()):
        m = measured.get(key)
        if m is None:
            continue  # 已按 a 计死键
        if m > reg:
            problems.append(f"  [棘轮增长] {key}: 登记 {reg} → 实测 {m}（零增长）")
        if reg > GLOBAL_FAIL or m > GLOBAL_FAIL:
            problems.append(
                f"  [超限未进legacy] {key}: 登记 {reg}/实测 {m} >{GLOBAL_FAIL}（>300 只能进 legacy）"
            )
    for key, reg in sorted(legacy.items()):
        m = measured.get(key)
        if m is not None and m > reg:
            problems.append(f"  [棘轮增长] {key}: 登记 {reg} → 实测 {m}（零增长）")
    for key, lines in sorted(measured.items()):
        if lines >= include_threshold and key not in function_lines and key not in legacy:
            problems.append(
                f"  [未登记] {key}: 实测 {lines} ≥{include_threshold} 且不在 function_lines∪legacy"
            )
    return problems


def test_function_lines_ratchet_within_baseline():
    """真实树 × 真实基线四规则对账：problems 必须为空（EVO-20261025-e0bff8ee）。

    `_classify_redlines` docstring 曾承诺而不存在的断言在此真实落地：登记集
    不再"登记即豁免"——死键/实测增长/>300 误置 fl/≥120 未登记均红。
    """
    b = _load_baseline()
    problems = _ratchet_problems(
        _measure_functions_cached(), b["function_lines"], b["legacy_super_functions"]
    )
    assert not problems, (
        "基线登记与 AST 实测不一致（EVO-20261025-e0bff8ee 四规则对账）：\n"
        + "\n".join(problems)
        + "\n重登记：python scripts/regen_function_size_baseline.py（guard(r9): 前缀提交）"
    )


def test_global_redline_300():
    """真实树口径全局红线：所有实测 >300 的函数必须登记且登记 ≥ 实测。

    未登记者逐条列出即 FAIL；登记 < 实测（无论登记在 legacy 还是 fl）同样
    FAIL——与 [棘轮增长] 同语义的红线视角；>300 键误置 function_lines 由
    `_ratchet_problems` 规则 c（[超限未进legacy]）另检。
    """
    b = _load_baseline()
    fl, legacy = b["function_lines"], b["legacy_super_functions"]
    problems: list[str] = []
    for key, lines in sorted(_measure_functions_cached().items()):
        if lines <= GLOBAL_FAIL:
            continue
        if key in legacy:
            reg, where = legacy[key], "legacy_super_functions"
        elif key in fl:
            reg, where = fl[key], "function_lines"
        else:
            problems.append(f"  [全局红线>{GLOBAL_FAIL}] {key}: 实测 {lines}，未登记（legacy/fl 均无）")
            continue
        if reg < lines:
            problems.append(f"  [全局红线>{GLOBAL_FAIL}] {key}: 实测 {lines} > {where} 登记 {reg}")
    assert not problems, (
        f"实测 >{GLOBAL_FAIL} 的函数存在未登记/低登记（全量重登记："
        "python scripts/regen_function_size_baseline.py，guard(r9): 前缀提交）：\n"
        + "\n".join(problems)
    )


def test_ratchet_rule_dead_key():
    """规则 a 红证据（合成数据）：登记键实测不存在 → [死键]，其余规则不误报。"""
    problems = _ratchet_problems(
        measured={"src/x.py::keep": 130},
        function_lines={"src/x.py::gone": 130, "src/x.py::keep": 130},
        legacy={"src/y.py::gone_l": 400},
    )
    dead = [p for p in problems if "[死键]" in p]
    assert any("src/x.py::gone" in p for p in dead)
    assert any("src/y.py::gone_l" in p for p in dead)
    assert len(problems) == 2, f"除两条死键外不应有其他问题: {problems}"


def test_ratchet_rule_growth():
    """规则 b 红证据（合成数据）：实测 > 登记 → [棘轮增长]（fl 与 legacy 同检）。"""
    problems = _ratchet_problems(
        measured={"src/x.py::f": 131, "src/y.py::g": 401},
        function_lines={"src/x.py::f": 130},
        legacy={"src/y.py::g": 400},
    )
    growth = [p for p in problems if "[棘轮增长]" in p]
    assert any("src/x.py::f" in p and "131" in p for p in growth)
    assert any("src/y.py::g" in p and "401" in p for p in growth)
    assert len(problems) == 2, f"除两条增长外不应有其他问题: {problems}"


def test_ratchet_rule_over300_must_be_legacy():
    """规则 c 红证据（合成数据）：>300 键登记在 function_lines → [超限未进legacy]。"""
    problems = _ratchet_problems(
        measured={"src/x.py::big": 350},
        function_lines={"src/x.py::big": 350},
        legacy={},
    )
    assert any("[超限未进legacy]" in p and "src/x.py::big" in p for p in problems)
    # 同数据进 legacy 后干净（d 规则视角：已登记，无论数值多大）
    assert _ratchet_problems({"src/x.py::big": 350}, {}, {"src/x.py::big": 350}) == []


def test_ratchet_rule_unregistered_threshold_band():
    """规则 d 红证据（合成数据）：实测 ≥120 未登记 → [未登记]；<120 不要求。"""
    problems = _ratchet_problems(
        measured={"src/x.py::f": 120, "src/x.py::small": 119},
        function_lines={},
        legacy={},
    )
    unreg = [p for p in problems if "[未登记]" in p]
    assert len(unreg) == 1 and "src/x.py::f" in unreg[0] and "120" in unreg[0]
    assert not any("src/x.py::small" in p for p in problems)


_IMPORT_EXEMPT_RE = re.compile(r"#\s*r9-import-exempt:\s*(\w+)\s*$")


def _is_type_checking(test: ast.expr) -> bool:
    """TYPE_CHECKING 判定：裸 Name 或 typing.TYPE_CHECKING 属性形态。"""
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
    )


def _count_fn_imports(source: str) -> tuple[int, int, int]:
    """函数内 import 计数：返回 (未豁免计数, 豁免计数, 非法标记数)。纯函数供单测直调。

    口径（B2-P2-04 / D2 裁定）：
    - 只计 FunctionDef/AsyncFunctionDef 直接体内（含嵌套函数）的 Import/ImportFrom；
    - **不进入嵌套类**（depth>0 时 ClassDef 子树整体跳过）；模块级类方法天然不计；
    - 排除 `if TYPE_CHECKING:` 块（静态类型面，非运行时 import）；
    - 行内 `# r9-import-exempt: optional|plugin` 标记的 import 计入豁免桶不占棘轮
      （豁免仅两类语义：optional 依赖 try/except、registry 延迟插件加载）。
    """
    lines = source.splitlines()
    v = _FnImportCounter(lines)
    v.visit(ast.parse(source))
    return v.counted, v.exempt, v.bad_marks


class _FnImportCounter(ast.NodeVisitor):
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.depth = 0
        self.counted = 0
        self.exempt = 0
        self.bad_marks = 0
        self._tc = 0

    def visit_FunctionDef(self, n: ast.FunctionDef) -> None:  # noqa: N802
        self.depth += 1
        self.generic_visit(n)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[method-assign]  # noqa: N802,N815

    def visit_ClassDef(self, n: ast.ClassDef) -> None:  # noqa: N802
        if self.depth > 0:
            return  # 不进入嵌套类
        self.generic_visit(n)

    def visit_If(self, n: ast.If) -> None:  # noqa: N802
        if _is_type_checking(n.test):
            self._tc += 1
            self.generic_visit(n)
            self._tc -= 1
        else:
            self.generic_visit(n)

    def _mark_class(self, lineno: int) -> str | None:
        m = _IMPORT_EXEMPT_RE.search(self.lines[lineno - 1]) if lineno - 1 < len(self.lines) else None
        if m is None:
            return None
        return m.group(1) if m.group(1) in ("optional", "plugin") else "INVALID"

    def visit_Import(self, n: ast.Import) -> None:  # noqa: N802
        self._hit(n)

    def visit_ImportFrom(self, n: ast.ImportFrom) -> None:  # noqa: N802
        self._hit(n)

    def _hit(self, n: ast.AST) -> None:
        if self.depth <= 0 or self._tc > 0:
            return
        mark = self._mark_class(getattr(n, "lineno", 0))
        if mark is None:
            self.counted += 1
        elif mark == "INVALID":
            self.bad_marks += 1
        else:
            self.exempt += 1


def test_import_counter_semantics():
    """豁免标记解析 + 差值核对口径单测（tmp 源码字符串直调，覆盖四形态）。"""
    src = (
        "import os\n"                                    # 模块级 → 不计
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from x import A\n"                          # TC 块 → 不计
        "def f():\n"
        "    import json\n"                              # 函数内未豁免 → counted
        "    import yaml  # r9-import-exempt: optional\n"  # 豁免桶
        "    from z import w  # r9-import-exempt: plugin\n"  # 豁免桶
        "    class Inner:\n"
        "        def m(self):\n"
        "            import io\n"                        # 嵌套类 → 不计
        "    def g():\n"
        "        import re\n"                            # 嵌套函数 → counted
        "    import q  # r9-import-exempt: wrongclass\n"  # 非法标记
    )
    counted, exempt, bad = _count_fn_imports(src)
    assert counted == 2, f"未豁免计数应为 2（json/re），实测 {counted}"
    assert exempt == 2 and bad == 1


def test_local_imports_ratchet():
    """五文件函数内 import 总量 ≤ 基线（D2 裁定：文件级总量棘轮，分函数不登记）。"""
    b = _load_baseline()
    problems = []
    for rel, cap in b["local_imports"].items():
        p = ROOT / rel
        if not p.exists():
            problems.append(f"  {rel}: 文件不存在（请随拆分提交更新 local_imports 节）")
            continue
        counted, _exempt, bad_marks = _count_fn_imports(_read_source(rel))
        if bad_marks:
            problems.append(f"  {rel}: {bad_marks} 处非法豁免标记（须 optional|plugin）")
        if counted > cap:
            problems.append(
                f"  {rel}: {cap} → {counted}（函数内 import 只减不增——豁免仅 optional/plugin 行内标记）"
            )
        if cap == 0 and counted > _exempt:  # 值=0 收口目标键：实测 ≤ 豁免标记数
            problems.append(f"  {rel}: 收口目标键实测 {counted} > 豁免标记 {_exempt}")
    assert not problems, "local_imports 超基线：\n" + "\n".join(problems)


def test_import_exempt_markers_zero_this_batch():
    """豁免标记登记 5 处（D2 裁定：标注即行为判断，不提前批量标注）。

    登记簿（逐处语义，增量需同步更新断言与本注释）：
    - 2026-09-29 +2 plugin：factory.py 的 chatgpt_web/deepseek_web provider 注册
      （feat 0b5f411e5/b8857b381 引入，settings 门控的 registry 延迟插件加载，
      恰为 D2 豁免两类语义之一；登记后棘轮回到基线 63）。
    - 2026-10-09 +2 plugin：factory.py 的 ExtensionCatalog/ExtensionStore 装配
      （feat e15d4a2d4/51087e01f，P1-A DESIGN-20261009 §5.3/§5.4；try/except
      fail-open 的可选扩展子系统装配，import 失败降级为无扩展目录，
      插件语义与 provider 注册同类；登记后棘轮保持基线 63）。
    - 2026-10-09 +1 plugin：factory.py 的 MCP 装配路径 ExtensionStore 导入
      （feat/p1a 合入 main 时 b5106a9ac 系；P1-C 装配改经 mcp_assembly，
      workspace>user 安装实例与 legacy MCP_SERVERS 合并；try/except
      fail-open 的可选扩展子系统装配，import 失败降级为无 MCP 工具，
      与 §5.4 ExtensionStore 装配同一语义；登记后棘轮保持基线 63）。
    - 2026-10-14 净 -2+1=4 plugin：web-carveout M3（6db89d6b5）删除
      chatgpt_web/deepseek_web 内置注册两标记（-2，注册段移出 factory），
      新增 web_provider_registration 外部模块加载（+1，importlib 动态加载
      +失败分级「未配置静默/失败 warning 不注册」，与 provider 注册同类
      plugin 语义）；登记后棘轮回基线 63。〔守卫书补：carveout M3 提交时
      漏同步本登记簿与断言，观测面板 M1d 全量回归期机械补正〕
    """
    b = _load_baseline()
    total_marks = 0
    for rel in b["local_imports"]:
        p = ROOT / rel
        if p.exists():
            _, exempt, _ = _count_fn_imports(_read_source(rel))
            total_marks += exempt
    assert total_marks == 4, f"豁免标记应登记 4 处（见登记簿注释），实测 {total_marks} 处"


# ── runtime cycle 守卫（B2-P2-05 / R9-P2-06·DFX-12）─────────────────────────
# 图构建口径：节点 = llm_loop.* 模块；static 边 = 模块级（TYPE_CHECKING 外）import；
# runtime 边 = 函数体内 import；TYPE_CHECKING 块一律排除（静态类型面非运行时）。
# core runtime cycle = SCC（≥2 模块）且成员间含 ≥1 条 runtime 边。
# 纯 AST 推断，不执行真实 import（防副作用）。

_PKG = "llm_loop"


def _module_name(p: Path, base: Path) -> tuple[str | None, bool]:
    """路径 → (模块名, 是否包 __init__)；src 外/非 llm_loop 返回 (None, False)。"""
    try:
        rel = p.relative_to(base).with_suffix("")
    except ValueError:
        return None, False
    parts = [x for x in rel.parts if x != "__init__"]
    if not parts or parts[0] != _PKG:
        return None, False
    return ".".join(parts), p.name == "__init__.py"


class _ImportGraphBuilder(ast.NodeVisitor):
    def __init__(self, mod: str, is_pkg: bool) -> None:
        self.mod, self.is_pkg = mod, is_pkg
        self.static: set[str] = set()
        self.runtime: set[str] = set()
        self.depth = 0
        self._tc = 0

    def _edge(self, target: str) -> None:
        if target != self.mod:
            (self.runtime if self.depth > 0 else self.static).add(target)

    def _hit(self, node: ast.Import | ast.ImportFrom) -> None:
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == _PKG or a.name.startswith(_PKG + "."):
                    self._edge(a.name)
            return
        if node.level == 0:
            t = node.module or ""
            if t == _PKG or t.startswith(_PKG + "."):
                self._edge(t)
            return
        base = self.mod if self.is_pkg else self.mod.rsplit(".", 1)[0]
        if node.level > 1:
            for _ in range(node.level - 1):
                base = base.rsplit(".", 1)[0]
        t = f"{base}.{node.module}" if node.module else base
        if t == _PKG or t.startswith(_PKG + "."):
            self._edge(t)

    def visit_FunctionDef(self, n: ast.FunctionDef) -> None:  # noqa: N802
        self.depth += 1
        self.generic_visit(n)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[method-assign]  # noqa: N802,N815

    def visit_If(self, n: ast.If) -> None:  # noqa: N802
        if _is_type_checking(n.test):
            self._tc += 1
            self.generic_visit(n)
            self._tc -= 1
        else:
            self.generic_visit(n)

    def visit_Import(self, n: ast.Import) -> None:  # noqa: N802
        if self._tc == 0:
            self._hit(n)

    def visit_ImportFrom(self, n: ast.ImportFrom) -> None:  # noqa: N802
        if self._tc == 0:
            self._hit(n)


def _build_import_graph(root: Path | None = None) -> dict[str, dict[str, set[str]]]:
    """AST 构建模块依赖图（static/runtime 双边集）。root 缺省真实 src。"""
    base = root if root is not None else SRC
    graph: dict[str, dict[str, set[str]]] = {}
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        mod, is_pkg = _module_name(p, base)
        if mod is None:
            continue
        try:
            tree = ast.parse(
                _read_source(f"src/{p.relative_to(base).as_posix()}") if root is None
                else p.read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            continue
        v = _ImportGraphBuilder(mod, is_pkg)
        v.visit(tree)
        graph[mod] = {"static": v.static, "runtime": v.runtime}
    return graph


def _find_runtime_cycles(graph: dict[str, dict[str, set[str]]]) -> set[str]:
    """Tarjan SCC（迭代式）；返回 runtime 环签名集（'a<->b'，成员短名排序）。

    短名 = 模块末段；若环内出现短名歧义（不同模块同末段）退化为全名防误判。
    """
    sccs: list[list[str]] = []
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    onstack: set[str] = set()
    stack: list[str] = []
    counter = [0]

    def succs(m: str):
        d = graph.get(m, {})
        return d.get("static", set()) | d.get("runtime", set())

    for root_mod in sorted(graph):
        if root_mod in index:
            continue
        work: list[tuple[str, list[str]]] = [(root_mod, sorted(succs(root_mod)))]
        index[root_mod] = low[root_mod] = counter[0]
        counter[0] += 1
        stack.append(root_mod)
        onstack.add(root_mod)
        while work:
            node, it = work[-1]
            advanced = False
            for succ in it:
                if succ not in graph:
                    continue
                if succ not in index:
                    index[succ] = low[succ] = counter[0]
                    counter[0] += 1
                    stack.append(succ)
                    onstack.add(succ)
                    work.append((succ, sorted(succs(succ))))
                    advanced = True
                    break
                if succ in onstack:
                    low[node] = min(low[node], index[succ])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) >= 2:
                    sccs.append(comp)

    cycles: set[str] = set()
    for comp in sccs:
        cs = set(comp)
        has_rt = any(t in cs for m in comp for t in graph[m].get("runtime", set()))
        if not has_rt:
            continue
        shorts = [m.rsplit(".", 1)[-1] for m in comp]
        if len(set(shorts)) != len(shorts):  # 短名歧义 → 全名签名
            sig = "<->".join(sorted(comp))
        else:
            sig = "<->".join(sorted(shorts))
        cycles.add(sig)
    return cycles


def test_runtime_cycles_match_known():
    """实测 runtime 环集合 == known_cycles（R9-P2-06a：新增任何运行时环 → CI FAIL）。

    终态（R9-P2-06b，2026-09-01 B3-C1/C2 七连链断环后）：两存量环已断，known_cycles
    空态锚定，本断言生效为"实测恒空"——任何新环（含拆分中间态环）一律 CI FAIL，
    无中间态豁免路径（拆分期间如需临时环：先 exemptions 登记 + 独立提交清理）。

    历史锚点（断环前存量两环，§0.5-5 修正表）：
    - engine<->build：已断（ac7b7c6）——build.py 快照 import 改指 session_snapshot
      叶子模块，函数内 engine 反向边退役
    - session<->fork：已断（95c5724）——session_types 纯类型先行 + BranchSeed 重建
      入口，fork 收窄为数据生成（f98b527/3e6cf72/95c5724 三步）
    """
    def _canon(sig: str) -> str:
        return "<->".join(sorted(sig.split("<->")))

    known = {_canon(c) for c in _load_baseline()["known_cycles"]}
    measured = _find_runtime_cycles(_build_import_graph())
    unknown = measured - known
    assert not unknown, (
        "新增 runtime 环（R9-P2-06a 违例，恒 0 终态：环计数只减不增且已归零）：\n  "
        + "\n  ".join(sorted(unknown))
        + "\n如为拆分中间态，请走 exemptions 或先断旧环。"
    )
    stale = known - measured
    assert not stale, f"known 环已消失（好消息！）——请随拆分提交清空 known_cycles：\n  {'\n  '.join(sorted(stale))}"


def test_cycle_detector_synthetic(tmp_path):
    """tmp 构造树：第三环检出 FAIL 面 + TYPE_CHECKING 边排除语义（R9-P2-06a 断言面）。"""
    pkg = tmp_path / "src" / "llm_loop"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # 第三环（模拟）：x → y 静态，y → x 函数内
    (pkg / "x.py").write_text("from llm_loop.y import g\n\ndef f():\n    pass\n", encoding="utf-8")
    (pkg / "y.py").write_text("def g():\n    from llm_loop.x import f\n    return f\n", encoding="utf-8")
    cycles = _find_runtime_cycles(_build_import_graph(tmp_path / "src"))
    assert "x<->y" in cycles, "模拟第三环未检出"

    # TYPE_CHECKING 边不构成环：a → b（TC 内 import，被排除），b 顶层 → 无环
    pkg2 = tmp_path / "tc" / "src" / "llm_loop"
    pkg2.mkdir(parents=True)
    (pkg2 / "__init__.py").write_text("", encoding="utf-8")
    (pkg2 / "a.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from llm_loop.b import h\n"
        "def fa():\n    return 1\n",
        encoding="utf-8",
    )
    (pkg2 / "b.py").write_text("def h():\n    return 2\n", encoding="utf-8")
    assert _find_runtime_cycles(_build_import_graph(tmp_path / "tc" / "src")) == set(), "TC 边应被排除"


def _numeric_raises(head_base: dict[str, Any], cur_base: dict[str, Any]) -> list[str]:
    """纯函数：基线数值节同键上调检测（v1/v2 兼容）——棘轮测试与篡改负例单测直调。

    - v2（schema≥2）：三数值节同键上调 + known_cycles 长度增加 → 逐条列出
    - v1（迁移视图）：functions ∩（function_lines ∪ legacy）同键上调；
      known_cycles 在 v1 无登记，初登记属 bootstrap 非增长
    - 下降与新键放行（收紧/登记 = 一次可见的 guard(r9) 提交）
    """
    problems: list[str] = []
    head_schema = head_base.get("_meta", {}).get("schema", 1)
    if head_schema < 2:
        merged = dict(cur_base.get("function_lines", {}))
        merged.update(cur_base.get("legacy_super_functions", {}))
        for k, head_v in head_base.get("functions", {}).items():
            if k in merged and merged[k] > head_v:
                problems.append(f"  {k}: {head_v} → {merged[k]}（+{merged[k] - head_v}）")
        return problems
    for sec in NUMERIC_SECTIONS:
        head_sec = head_base.get(sec, {})
        cur_sec = cur_base.get(sec, {})
        for k, head_v in head_sec.items():
            if k in cur_sec and cur_sec[k] > head_v:
                problems.append(f"  {sec}[{k}]: {head_v} → {cur_sec[k]}（+{cur_sec[k] - head_v}）")
    head_cycles = len(head_base.get("known_cycles", []))
    cur_cycles = len(cur_base.get("known_cycles", []))
    if cur_cycles > head_cycles:
        problems.append(f"  known_cycles: {head_cycles} → {cur_cycles}（环只减不增）")
    return problems


def test_baseline_tamper_negative_cases():
    """[任何修改基线常量使其上调的提交] → [CI FAIL + 评审拒绝]（R9-P2-03b 断言面）。

    纯函数直调模拟篡改：三数值节同键上调与环登记增加必须全部检出；
    下降与新键放行（合法收紧/登记通道）；v1→v2 迁移视图同检。
    """
    head = {
        "_meta": {"schema": 2},
        "function_lines": {"src/x.py::f": 100},
        "legacy_super_functions": {"src/y.py::g": 700},
        "local_imports": {"src/y.py": 10},
        "known_cycles": ["x<->y"],
    }
    tampered = {
        "_meta": {"schema": 2},
        "function_lines": {"src/x.py::f": 101},
        "legacy_super_functions": {"src/y.py::g": 701},
        "local_imports": {"src/y.py": 11},
        "known_cycles": ["x<->y", "x<->z"],
    }
    raises = _numeric_raises(head, tampered)
    joined = "\n".join(raises)
    assert "function_lines[src/x.py::f]" in joined and "101" in joined
    assert "legacy_super_functions[src/y.py::g]" in joined and "701" in joined
    assert "local_imports[src/y.py]" in joined and "11" in joined
    assert "known_cycles" in joined and "环只减不增" in joined

    # 下降 + 新键登记 + 环清空 → 全放行（合法通道）
    legit = {
        "_meta": {"schema": 2},
        "function_lines": {"src/x.py::f": 90, "src/new.py::h": 130},
        "legacy_super_functions": {"src/y.py::g": 699},
        "local_imports": {"src/y.py": 10},
        "known_cycles": [],
    }
    assert _numeric_raises(head, legit) == []

    # v1 迁移视图：functions 同键上调检出（迁移期不放松防篡改）
    v1_head = {"functions": {"src/x.py::f": 100}}
    v1_check = {"function_lines": {"src/x.py::f": 105}, "legacy_super_functions": {}}
    assert any("105" in r for r in _numeric_raises(v1_head, v1_check))


def test_baseline_ratchet_not_raised():
    """防篡改层 2（全节）：基线 JSON 任何数值较 git HEAD 上升即 FAIL（无论实测）。"""
    rel = BASELINE_PATH.relative_to(ROOT).as_posix()
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        head_base = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pytest.skip(f"基线文件尚未提交到 git（{rel}），提交后棘轮生效")

    problems = _numeric_raises(head_base, _load_baseline())
    assert not problems, (
        "基线被上调（棘轮只允许下降）。如为有意放宽，请走 exemptions（reason + deadline），"
        "不要直接改基线值：\n" + "\n".join(problems)
    )


def test_exemptions_wellformed():
    """豁免条目 v2 字段完整 + **数量较 HEAD 单调不增**（T3-C 层 3 防篡改）。

    初始登记：本批空清单成立——四函数走 legacy 棘轮、≥120 存量走 function_lines
    基线、optional/plugin 走行内标记（三层各司其职，无存量豁免需求）；守卫上线
    红区无非 legacy ≥300 命中（test_global_redline_300 绿即回执），OQ-7 无需
    显式登记项——不允许上调红线（spec §5.3.3-1b）。
    """
    import datetime as _dt

    b = _load_baseline()
    cur_n = len(b.get("exemptions", []))
    # 数量单调不增：与 HEAD 比对（新增豁免 = 绕过棘轮的暗门，必须走可见提交评审）
    rel = BASELINE_PATH.relative_to(ROOT).as_posix()
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], capture_output=True, text=True, check=True, cwd=ROOT
        )
        head_n = len(json.loads(proc.stdout).get("exemptions", []))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        head_n = None  # 基线首次提交前无对照
    problems: list[str] = []
    if head_n is not None and cur_n > head_n:
        problems.append(f"  exemptions 数量 {head_n} → {cur_n}（豁免只减不增；新增须评审可见）")
    today = _dt.date.today()
    for i, ex in enumerate(b.get("exemptions", [])):
        for field in ("key", "reason", "review_deadline", "class"):
            if field not in ex:
                problems.append(f"  exemptions[{i}] 缺字段 {field}")
        if str(ex.get("class", "")) not in ("optional", "plugin"):
            problems.append(f"  exemptions[{i}].class 应为 optional|plugin: {ex.get('class')!r}")
        if len(str(ex.get("reason", "")).strip()) < 10:
            problems.append(f"  exemptions[{i}].reason 过短，需说明为何不能拆、何时拆")
        dl = ex.get("review_deadline")
        if dl:
            try:
                d = _dt.date.fromisoformat(str(dl))
                if d < today:
                    problems.append(f"  exemptions[{i}] 已于 {dl} 过期，请清除或续期（附新理由）")
                elif (d - today).days > 30:
                    problems.append(f"  exemptions[{i}] 期限 {(d - today).days} 天 > 上限 30 天")
            except ValueError:
                problems.append(f"  exemptions[{i}].review_deadline 日期格式非法: {dl!r}")
    assert not problems, "豁免条目存在问题：\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# R9-P5-01 Mixin 不可增棘轮：LoopEngine 基类列表只能缩短（退役），不能新增
# ---------------------------------------------------------------------------

_ENGINE_REL = "src/llm_loop/core/loop/engine.py"
_MIXIN_CAP = 6  # B5-W4-02d 实测 7 个（_RuntimeParamsMixin/_RoutingMixin/_FallbackMixin/_ArchiveMixin 已退役 → RuntimeParams/Routing/Fallback/ArchiveService；累计 _Signals/_Overflow/_Err1210/_ToolExec/_ToolEligibility/_RuntimeParams/_Routing/_Fallback/_Archive）；只允许随退役单调递减


def _parse_loop_engine_bases(source: str) -> list[str]:
    """从 engine.py 源码解析 class LoopEngine(...) 基类列表（文本口径，逗号切分）。"""
    m = re.search(r"^class LoopEngine\(([^)]*)\):", source, re.MULTILINE)
    assert m, "engine.py 中未找到 LoopEngine 类定义（文本口径解析失败）"
    return [b.strip() for b in m.group(1).split(",") if b.strip()]


# R9-B5-W2-01: Mixin 更名映射（职责面迁出后的名称演化，数量守恒不算新增）
_MIXIN_RENAMES = {
    "_RunEntrypointMixin": "_LifecycleMixin",  # 职责面迁 SessionLifecycle，编排入口留名
}


def test_loop_engine_mixin_ratchet():
    """Mixin 数量棘轮：上限 16 + 与 HEAD 比对单调递减 + 禁止新增基类（更名经 _MIXIN_RENAMES 折算）."""
    current = _parse_loop_engine_bases((ROOT / _ENGINE_REL).read_text(encoding="utf-8"))
    assert len(current) <= _MIXIN_CAP, (
        f"LoopEngine 基类 {len(current)} 个 > 上限 {_MIXIN_CAP}：禁止新增 Mixin（R9-P5-01）；"
        "新逻辑请落 engine_services/ 组合对象，不走继承"
    )
    head = subprocess.run(
        ["git", "show", f"HEAD:{_ENGINE_REL}"], cwd=ROOT, capture_output=True, text=True
    )
    if head.returncode != 0:
        pytest.skip("engine.py 尚未入库，棘轮比对跳过")
    head_bases = _parse_loop_engine_bases(head.stdout)
    # 更名折算：双侧均折算到固定名域（PROBE 检出态 HEAD=本提交，双侧同名；
    # 工作态 HEAD=旧世代，current 侧新名→旧名）；不动点迭代支持链式更名
    def _canon(names: set[str]) -> set[str]:
        prev = None
        cur = set(names)
        while prev != cur:
            prev = cur
            cur = {_MIXIN_RENAMES.get(n, n) for n in cur}
        return cur

    extra = _canon(set(current)) - _canon(set(head_bases))
    assert not extra, (
        f"检测到新增基类 {sorted(extra)}：Mixin 列表只允许退役（单调递减），不允许新增"
        f"（更名须登记 _MIXIN_RENAMES）"
    )
    assert len(current) <= len(head_bases), (
        f"基类数 {len(current)} > HEAD {len(head_bases)}：违反单调递减棘轮（R9-P5-01）"
    )


# ---------------------------------------------------------------------------
# P0-3 扩张冻结（AUDIT-20261007 rev2 / 用户授权 2026-10-07）：顶层单元登记制
# ---------------------------------------------------------------------------


def _scan_top_level_units(base: Path) -> tuple[set[str], set[str]]:
    """src/llm_loop 直下单元扫描：返回 (packages, modules)。

    纯函数——tmp_path 构造树单测直调；真实树传 ``SRC / "llm_loop"``。
    ``__pycache__`` 与 ``__init__.py`` 不计；**untracked 新目录/新文件同样在
    扫描面内**（扩张冻结的设防对象就是"未经登记的新增"，含未提交者）。
    """
    pkgs: set[str] = set()
    mods: set[str] = set()
    if not base.exists():
        return pkgs, mods
    for p in sorted(base.iterdir()):
        if p.name == "__pycache__":
            continue
        if p.is_dir():
            pkgs.add(p.name)
        elif p.is_file() and p.suffix == ".py" and p.name != "__init__.py":
            mods.add(p.name)
    return pkgs, mods


def test_top_level_units_registered():
    """[新增顶层包/能力文件未登记] → [CI FAIL]（P0-3 扩张冻结，EARS 断言面）.

    - 未登记的新包/新文件 → FAIL（登记通道：baseline ``top_level_units`` 节 +
      ``guard(r9):`` 前缀提交——scripts/r9_commit_check.sh 规则④机检）。
    - 已登记但磁盘消失（拆分/更名后未清理）→ FAIL（防登记簿腐化成纸面）。
    - 登记值（plane 归属）必须非空；exemptions 须带非空 reason。
    """
    units = _load_baseline()["top_level_units"]
    reg_pkgs, reg_mods = set(units["packages"]), set(units["modules"])
    exempt = set(units["exemptions"])
    problems: list[str] = []
    for name, plane in {**units["packages"], **units["modules"]}.items():
        if not str(plane).strip():
            problems.append(f"  {name}: 登记的 plane 归属为空（登记必须含六面/kernel/delivery 归属）")
    for name in exempt:
        if not str(units["exemptions"][name]).strip():
            problems.append(f"  exemptions[{name}]: 必须带非空 reason")
    real_pkgs, real_mods = _scan_top_level_units(SRC / "llm_loop")
    for name in sorted((real_pkgs - reg_pkgs) - exempt):
        problems.append(f"  未登记顶层包: src/llm_loop/{name}/")
    for name in sorted((real_mods - reg_mods) - exempt):
        problems.append(f"  未登记能力文件: src/llm_loop/{name}")
    for name in sorted((reg_pkgs - real_pkgs) - exempt):
        problems.append(f"  登记已失效（包不存在，请随拆分提交清理）: {name}")
    for name in sorted((reg_mods - real_mods) - exempt):
        problems.append(f"  登记已失效（文件不存在，请随拆分提交清理）: {name}")
    assert not problems, (
        "P0-3 扩张冻结违例（新顶层单元必须登记归属或显式豁免，AUDIT-20261007 rev2）：\n"
        + "\n".join(problems)
        + "\n登记：tests/guards/function_size_baseline.json → top_level_units 节 + guard(r9): 前缀提交"
    )


def test_top_level_scan_semantics(tmp_path):
    """tmp 构造树：包/模块/排除项（__pycache__、__init__.py、非 py）四形态。"""
    base = tmp_path / "src" / "llm_loop"
    (base / "pkg_a").mkdir(parents=True)
    (base / "__pycache__").mkdir()
    (base / "pkg_a" / "m.py").write_text("", encoding="utf-8")
    (base / "top.py").write_text("", encoding="utf-8")
    (base / "__init__.py").write_text("", encoding="utf-8")
    (base / "notes.txt").write_text("", encoding="utf-8")
    pkgs, mods = _scan_top_level_units(base)
    assert pkgs == {"pkg_a"}  # __pycache__ 排除
    assert mods == {"top.py"}  # __init__.py 与非 py 排除


# ---------------------------------------------------------------------------
# P1-4 Kernel v1 import ratchet（ARCHITECTURE-20261007-kernel-v1-contract）
# ---------------------------------------------------------------------------

_KERNEL_INTERNAL_ROOTS = {"core", "event_log", "resources", "runtime", "llm"}


def _kernel_owner(rel: str) -> str | None:
    if rel.startswith("src/llm_loop/core/loop/"):
        return "core/loop"
    for root in ("event_log", "resources", "runtime", "llm"):
        if rel.startswith(f"src/llm_loop/{root}/"):
            return root
    return None


def _kernel_cross_plane_edges(root: Path | None = None) -> set[str]:
    """AST 扫描 Kernel v1 的 package-level 反向依赖 edge."""
    base = root if root is not None else SRC
    out: set[str] = set()
    llm_root = base / "llm_loop"
    candidates = [llm_root / "core" / "loop"]
    candidates.extend(llm_root / name for name in ("event_log", "resources", "runtime", "llm"))
    for directory in candidates:
        if not directory.exists():
            continue
        for p in sorted(directory.rglob("*.py")):
            rel = f"src/{p.relative_to(base).as_posix()}"
            owner = _kernel_owner(rel)
            if owner is None:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    parts = node.module.split(".")
                    if len(parts) >= 2 and parts[0] == "llm_loop":
                        imported = parts[1]
                        if imported not in _KERNEL_INTERNAL_ROOTS:
                            out.add(f"{owner}->{imported}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        parts = alias.name.split(".")
                        if len(parts) >= 2 and parts[0] == "llm_loop":
                            imported = parts[1]
                            if imported not in _KERNEL_INTERNAL_ROOTS:
                                out.add(f"{owner}->{imported}")
    return out


def test_kernel_import_edges_match_frozen_baseline():
    """Kernel→capability 现存债务精确冻结：新增/陈旧 edge 均 FAIL."""
    registered = set(_load_baseline().get("kernel_import_edges", []))
    current = _kernel_cross_plane_edges()
    added = sorted(current - registered)
    stale = sorted(registered - current)
    assert not added and not stale, (
        "Kernel v1 import ratchet 漂移：\n"
        + ("  未登记新增 edge: " + ", ".join(added) + "\n" if added else "")
        + ("  已消失 edge 仍在基线（应随偿还删除）: " + ", ".join(stale) if stale else "")
    )


def test_kernel_import_edges_baseline_only_decreases():
    """防绕过：不能通过同提交把新反向 edge 顺手登记进 baseline."""
    rel = BASELINE_PATH.relative_to(ROOT).as_posix()
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        head_base = json.loads(proc.stdout)
        if "kernel_import_edges" not in head_base:
            pytest.skip("kernel_import_edges 首次建基线：HEAD 尚无该节")
        head_edges = set(head_base["kernel_import_edges"])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pytest.skip("kernel_import_edges 首次提交前无 HEAD 基线")
    current_registered = set(_load_baseline().get("kernel_import_edges", []))
    added = sorted(current_registered - head_edges)
    assert not added, (
        "kernel_import_edges 基线只允许减少；检测到新增登记 "
        + ", ".join(added)
        + "。新 kernel→capability 依赖必须改设计，不得扩 baseline。"
    )


def test_kernel_import_edge_synthetic_negative(tmp_path):
    """合成负例：kernel 新 import 一个 capability root 必须被扫描出来."""
    target = tmp_path / "src" / "llm_loop" / "runtime"
    target.mkdir(parents=True)
    (target / "x.py").write_text(
        "from llm_loop.new_capability.api import Thing\n",
        encoding="utf-8",
    )
    assert _kernel_cross_plane_edges(tmp_path / "src") == {"runtime->new_capability"}


# ---------------------------------------------------------------------------
# Durable Run Contract: filesystem persistence-write candidate registry
# ---------------------------------------------------------------------------


def _literal_write_mode(call: ast.Call) -> str | None:
    mode_node: ast.expr | None = None
    if isinstance(call.func, ast.Name) and call.func.id == "open":
        if len(call.args) >= 2:
            mode_node = call.args[1]
    elif (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "open"
        and call.args
    ):
        mode_node = call.args[0]
    for kw in call.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return None


def _os_open_has_write_flag(call: ast.Call) -> bool:
    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "os"
        and call.func.attr == "open"
        and len(call.args) >= 2
    ):
        return False
    names = {n.id for n in ast.walk(call.args[1]) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(call.args[1]) if isinstance(n, ast.Attribute)}
    flags = names | attrs
    return bool(flags & {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"})


def _durability_write_candidate_files(root: Path | None = None) -> set[str]:
    """返回出现明确 filesystem 写入原语的生产源码文件.

    这是“需分类面”，不是“都是 durability surface”的断言。每个候选必须至少被
    一个 durability surface 覆盖，或进入 durability_write_exemptions；同一源码
    文件可承载多个不同 tier 的 semantic surface（例如 Evidence blob + ledger）。
    """
    base = root if root is not None else SRC
    out: set[str] = set()
    for p in sorted((base / "llm_loop").rglob("*.py")):
        rel = f"src/{p.relative_to(base).as_posix()}"
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            attr = func.attr if isinstance(func, ast.Attribute) else ""
            is_path_write = attr in {"write_text", "write_bytes"}
            is_open = (
                isinstance(func, ast.Name)
                and func.id == "open"
                or isinstance(func, ast.Attribute)
                and func.attr == "open"
            )
            mode = _literal_write_mode(call) if is_open else None
            if is_path_write or (mode is not None and any(c in mode for c in "wax+")) or _os_open_has_write_flag(call):
                out.add(rel)
                break
    return out


def _registered_durability_write_files() -> tuple[set[str], list[str]]:
    reg = _load_baseline().get("durability_registry", {})
    files: set[str] = set()
    surface_files: set[str] = set()
    problems: list[str] = []
    surfaces = reg.get("surfaces", {})
    exemptions = reg.get("write_exemptions", {})
    for surface_id, spec in surfaces.items():
        if spec.get("tier") not in {"T1", "T2", "T3"}:
            problems.append(f"  surface {surface_id}: tier 必须为 T1/T2/T3")
        if spec.get("status") not in {"conform", "migrate", "partial", "observe"}:
            problems.append(
                f"  surface {surface_id}: status 必须为 conform/migrate/partial/observe"
            )
        paths = spec.get("paths", [])
        if not paths:
            problems.append(f"  surface {surface_id}: paths 不能为空")
        if not str(spec.get("owner", "")).strip():
            problems.append(f"  surface {surface_id}: owner 不能为空")
        if not str(spec.get("rationale", "")).strip():
            problems.append(f"  surface {surface_id}: rationale 不能为空")
        for path in paths:
            surface_files.add(path)
            files.add(path)
    for path, reason in exemptions.items():
        if path in surface_files:
            problems.append(f"  surface/exemption 重复登记: {path}")
        if len(str(reason).strip()) < 10:
            problems.append(f"  exemption 理由过短: {path}")
        files.add(path)
    return files, problems


def test_durability_write_candidates_registered():
    """所有明确 filesystem 写入文件必须归入 durable surface 或显式非-durable 豁免."""
    registered, problems = _registered_durability_write_files()
    current = _durability_write_candidate_files()
    missing = sorted(current - registered)
    stale = sorted(registered - current)
    if missing:
        problems.append("  未登记写入候选: " + ", ".join(missing))
    if stale:
        problems.append("  登记已失效/扫描不到写入原语: " + ", ".join(stale))
    assert not problems, "Durability surface registry 漂移:\n" + "\n".join(problems)


def test_durability_write_candidate_synthetic_negative(tmp_path):
    """合成负例：既有包中新造 write_text 也必须被扫描，不能绕过顶层单元 guard."""
    target = tmp_path / "src" / "llm_loop" / "runtime"
    target.mkdir(parents=True)
    (target / "new_store.py").write_text(
        "from pathlib import Path\n"
        "def persist(path: Path, value: str) -> None:\n"
        "    path.write_text(value, encoding='utf-8')\n",
        encoding="utf-8",
    )
    assert _durability_write_candidate_files(tmp_path / "src") == {
        "src/llm_loop/runtime/new_store.py"
    }


# ── 静默异常吞没守卫（P1-4）────────────────────────────────────────────────
# 口径：`except (Exception|BaseException)` 的 body 仅一条 `pass` 时，必须带
# 原因说明注释——注释写清「为什么这里必须 fail-open」，而不是复述代码。
# 扫描面 = src/tests/scripts（与 ruff 全树一致）。仅检查明确的宽捕获 + 单条 pass
# 是否带说明，不判断说明的语义正确性。删除/收窄吞没不受总数量下限阻挡；
# 具体 fallback 的保留应由其行为回归测试证明，不能用全仓总数替代。
SCAN_ROOTS = ("src", "tests", "scripts")


def _iter_py_rels(root: Path) -> list[str]:
    rels: list[str] = []
    for prefix in SCAN_ROOTS:
        base = root / prefix
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" not in str(p):
                rels.append(p.relative_to(root).as_posix())
    return rels


def _catches_all(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True  # 裸 except
    return _is_broad_exception_type(handler.type)


def _is_broad_exception_type(node: ast.expr) -> bool:
    names = {"Exception", "BaseException"}
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id == "builtins" and node.attr in names
    if isinstance(node, ast.Tuple):
        return any(_is_broad_exception_type(item) for item in node.elts)
    return False


def _handler_has_reason(handler: ast.ExceptHandler, lines: list[str]) -> bool:
    """原因说明 = handler 源码段内有注释，且去掉 `noqa` 代号后仍有 ≥3 字符内容。"""
    first = handler.body[0]
    end = getattr(first, "end_lineno", first.lineno) or first.lineno
    segment = "\n".join(lines[handler.lineno - 1:end])
    comments = [c.strip() for c in re.findall(r"#\s*([^\n]+)", segment)]
    if not comments:
        return False
    stripped = re.sub(r"noqa[:\s]*[A-Z0-9,\s]*", "", " ".join(comments), flags=re.I)
    return len(stripped.strip(" —-:：")) >= 3


def _scan_swallows(rels: list[str], source_of: Any) -> tuple[list[str], int]:
    """返回 (无原因说明的位置清单, 单条 pass 吞异常总处数)。

    `source_of(rel)` 提供源码文本：真实树走守卫读源口径（D-07 外部漂移回退
    HEAD），合成树直读文件。
    """
    offenders: list[str] = []
    total = 0
    for rel in rels:
        try:
            source = source_of(rel)
            tree = ast.parse(source)
        except Exception:  # noqa: BLE001 — 语法错误由 lint/CI 负责，守卫不重复报错
            continue
        lines = source.splitlines()
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler):
                continue
            if not _catches_all(handler):
                continue
            if len(handler.body) != 1 or not isinstance(handler.body[0], ast.Pass):
                continue
            total += 1
            if not _handler_has_reason(handler, lines):
                offenders.append(f"{rel}:{handler.lineno}")
    return offenders, total


def _rel_source_real(rel: str) -> str:
    return _read_source(rel)


@functools.lru_cache(maxsize=1)
def _scan_swallows_real() -> tuple[tuple[str, ...], int]:
    return tuple(_scan_swallows(_iter_py_rels(ROOT), _rel_source_real))  # type: ignore[return-value]


def test_no_silent_exception_swallow() -> None:
    """零容忍：src/tests/scripts 内不允许存在无原因说明的静默异常吞没。"""
    offenders, _total = _scan_swallows_real()
    assert not offenders, (
        "静默异常吞没（except Exception: pass 无原因说明）："
        + ", ".join(offenders)
        + " —— 要么写成 `except Exception:  # noqa: BLE001 — <为什么必须 fail-open>`，"
        "要么收窄为具体异常类型"
    )


def _synthetic_tree(tmp_path: Path) -> Path:
    """合成树：a/b 违规（裸 except、仅 noqa），c/d 合规（带原因、已收窄）。"""
    bad = tmp_path / "src"
    bad.mkdir(parents=True)
    (bad / "a.py").write_text(
        "def f():\n    try:\n        return 1\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    (bad / "b.py").write_text(
        "def g():\n    try:\n        return 1\n"
        "    except BaseException:  # noqa: BLE001\n        pass\n",
        encoding="utf-8",
    )
    (bad / "c.py").write_text(
        "def h():\n    try:\n        return 1\n"
        "    except Exception:  # noqa: BLE001 — 埋点失败不影响主路径\n        pass\n",
        encoding="utf-8",
    )
    (bad / "d.py").write_text(
        "def i():\n    try:\n        return 1\n    except ValueError:\n        pass\n",
        encoding="utf-8",
    )
    return bad


def test_silent_swallow_rule_semantics(tmp_path: Path) -> None:
    """规则语义：裸 except / 仅 noqa 违规；带原因说明、已收窄类型均不违规。"""
    _synthetic_tree(tmp_path)
    rels = [f"src/{n}" for n in ("a.py", "b.py", "c.py", "d.py")]
    offenders, total = _scan_swallows(rels, lambda rel: (tmp_path / rel).read_text(encoding="utf-8"))
    assert offenders == ["src/a.py:4", "src/b.py:4"], f"规则判定不符预期: {offenders}"
    assert total == 3, f"仅单条 pass 的三处应计入总数: {total}"


def test_silent_swallow_guard_fails_on_new_violation(tmp_path: Path) -> None:
    """负例自验：新写的无说明 `except Exception: pass` 必须被守卫拦下。"""
    _synthetic_tree(tmp_path)
    offenders, _ = _scan_swallows(
        ["src/a.py"], lambda rel: (tmp_path / rel).read_text(encoding="utf-8")
    )
    assert offenders, "违规样本未被拦下——守卫失效"
    (tmp_path / "src" / "clean_ok.py").write_text(
        "def f():\n    try:\n        return 1\n"
        "    except Exception:  # noqa: BLE001 — 埋点失败不得阻断主流程\n        pass\n",
        encoding="utf-8",
    )
    offenders_clean, _ = _scan_swallows(
        ["src/clean_ok.py"], lambda rel: (tmp_path / rel).read_text(encoding="utf-8")
    )
    assert offenders_clean == []


@pytest.mark.parametrize("exception_type, broad", [
    ("CustomException", False),
    ("SpecificBaseException", False),
    ("(KeyError, CustomException)", False),
    ("builtins.Exception", True),
    ("(ValueError, BaseException)", True),
])
def test_broad_exception_match_uses_exact_type_names(exception_type, broad):
    source = f"try:\n    f()\nexcept {exception_type}:\n    pass\n"
    handler = ast.parse(source).body[0].handlers[0]
    assert _catches_all(handler) is broad
