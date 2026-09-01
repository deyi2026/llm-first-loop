"""R9 架构守卫（AST 实测 + 基线外置 v2 + 单向棘轮 + 防篡改三层）.

前身 `test_function_size_guard.py`（workbuddy 雏形，B2-P1-01 收编）经 git mv
更名扩展——文件历史可追溯。v2 基线五节（design T3-C）：

- ``function_lines``：全函数 ≥120 行登记（三层红线联动阈值）
- ``legacy_super_functions``：四函数专属棘轮（build/engine/factory/history）
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
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

# tests/unit/test_arch_guards.py → parents[2] = 仓库根
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BASELINE_PATH = ROOT / "tests" / "guards" / "function_size_baseline.json"

# 收录基线的门槛（v2：与三层红线 WARN 下限联动，150 → 120）
INCLUDE_THRESHOLD = 120

# ── 三层红线（B2-P2-02 / R9-P2-01·02·04，取代 v1 HARD_CAP=2000 硬顶 D10）──
# 全局层：任意函数 >300 行 FAIL（无豁免通道，超限只能拆）
GLOBAL_FAIL = 300
# core 层：core 文件内函数 >200 FAIL；120-150 区间 WARN（guard_report 报告态，
# 不阻断 CI）；151-200 为合法增长走廊（超 200 即 FAIL）
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
    legacy 四函数（1702/1126/1004/721）同为登记存量，Phase 6/7 拆分目标
    （D10 收编延续：v1 硬顶 2000 从不拦 1732 存量——红线语义自始是防新增）。
    纵深防御：未登记 301 行函数同时触发本红线（FAIL）与
    `test_new_large_functions_must_be_recorded`（强制登记）——belt + suspenders。
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


def test_global_redline_300():
    """全局层：任意**非 legacy** 函数 >300 行 FAIL（R9-P2-01a：新增 301 行函数→CI FAIL）。

    已登记函数豁免红线、走棘轮零增长断言（见 _classify_redlines docstring）。
    """
    failures, _ = _classify_redlines(_measure_functions())
    assert not failures, "三层红线违例（拆分是唯一通道，基线不上调）：\n" + "\n".join(failures)


def test_core_redline_200():
    """core 层：CORE_FILES 内函数 >200 FAIL（R9-P2-01a core 面）。"""
    failures, _ = _classify_redlines(_measure_functions())
    core_only = [f for f in failures if "core红线" in f]
    assert not core_only, "core 层违例：\n" + "\n".join(core_only)


@pytest.mark.guard_report
def test_core_warn_report_120_150():
    """core 层 WARN 区间报告（guard_report marker 独立呈现，不阻断；T3-A 口径）。

    WARN ≠ 违例：120-150 是"审查提醒带"——首行可见于 -m guard_report 运行，
    CI 常驻报告中呈现（spec §5.3.3-1c 可见性），FAIL 用例默认跑不受影响。
    """
    _, warns = _classify_redlines(_measure_functions())
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


def _measure_functions(root: Path | None = None) -> dict[str, int]:
    """AST 实测函数行数，返回 {key: lines}（R9-DFX-16 单遍解析共享入口）。

    key 形如 'src/llm_loop/...::name'：真实树以 ROOT/src 为基；tmp_path 构造树
    传入其 src 目录，key 空间与真实树一致（供三层红线/基线检测器直调）。
    """
    base = root if root is not None else SRC
    out: dict[str, int] = {}
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 语法错误由 lint/CI 负责，守卫不重复报错
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = getattr(n, "end_lineno", n.lineno) - n.lineno + 1
                out[f"src/{p.relative_to(base).as_posix()}::{n.name}"] = lines
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


def test_function_lines_ratchet_within_baseline(measured: dict[str, int] | None = None):
    """实测 ≤ 基线（function_lines + legacy 四函数）；实测更低输出收紧建议。"""
    m = measured if measured is not None else _measure_functions()
    b = _load_baseline()
    failures, suggestions = [], []
    for sec in ("function_lines", "legacy_super_functions"):
        for key, cap in b[sec].items():
            cur = m.get(key)
            if cur is None:
                failures.append(f"  {key}: 函数已不存在于实测集（请随拆分提交收紧基线）")
            elif cur > cap:
                failures.append(f"  {key}: {cap} → {cur}（+{cur - cap}，超标——只能拆分，基线不上调）")
            elif cur < cap:
                suggestions.append(f"  {key}: 基线 {cap} 可收紧为 {cap - (cap - cur)} → 实测 {cur}")
    assert not failures, "函数行数超基线（棘轮只降不升）：\n" + "\n".join(failures)
    if suggestions:
        print("\n建议随下次 guard(r9) 提交收紧基线（只提示不自动改）：\n" + "\n".join(suggestions))


def test_new_large_functions_must_be_recorded(measured: dict[str, int] | None = None):
    """新出现 ≥INCLUDE_THRESHOLD 行的函数必须登记进基线（防漏网）。"""
    m = measured if measured is not None else _measure_functions()
    b = _load_baseline()
    known = set(b["function_lines"]) | set(b["legacy_super_functions"])
    unrecorded = [k for k, v in m.items() if v >= INCLUDE_THRESHOLD and k not in known]
    assert not unrecorded, (
        f"存在 ≥{INCLUDE_THRESHOLD} 行未登记函数（{len(unrecorded)} 个）。"
        f"请将其当前行数写入 {BASELINE_PATH.name}：\n"
        + "\n".join(f"  {k}: {m[k]}" for k in sorted(unrecorded)[:20])
    )


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

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[method-assign]  # noqa: N802

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
        counted, _exempt, bad_marks = _count_fn_imports(p.read_text(encoding="utf-8"))
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
    """本批豁免标记登记 0 处（D2 裁定：存量五键为总量基线，逐处语义标注留待
    Phase 4/6/7 域收口时随拆分登记——标注即行为判断，不提前批量标注）。"""
    b = _load_baseline()
    total_marks = 0
    for rel in b["local_imports"]:
        p = ROOT / rel
        if p.exists():
            _, exempt, _ = _count_fn_imports(p.read_text(encoding="utf-8"))
            total_marks += exempt
    assert total_marks == 0, f"本批应登记 0 处豁免标记，实测 {total_marks} 处"


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
    """豁免条目 v2 字段完整（key/reason≥10 字符/review_deadline≤30 天/class∈{optional,plugin}）。

    数量单调不增断言随 B2-P2-07 补齐（与 HEAD 比对联动）。
    """
    import datetime as _dt

    b = _load_baseline()
    today = _dt.date.today()
    problems: list[str] = []
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
