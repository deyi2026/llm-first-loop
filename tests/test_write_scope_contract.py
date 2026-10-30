"""write_scope 核心契约层（P0）测试：解析三分态 / 判定四类 reason / glob 边界 /
symlink 逃逸 / .. 穿越 / 父子求交与越界拒绝 / SurfaceRequirements 接线零回归。

对应 DESIGN-20261030-write-scope-and-concurrent-writer-ownership.md §5.2/§5.4 与
验收条件 1-4。既有测试零修改；本文件只测新增契约。
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from llm_loop.core.execution_surface import SurfaceRequirements
from llm_loop.core.run_context import current_write_scope
from llm_loop.core.write_scope import (
    MAX_PATTERN_LEN,
    MAX_PATTERNS,
    WriteScope,
    intersect_write_scope,
    parse_write_scope,
    scope_allows,
    write_scope_audit_record_violation,
    write_scope_audit_record_write,
    write_scope_audit_reset,
    write_scope_audit_snapshot,
)
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool


@pytest.fixture(autouse=True)
def _reset_audit():
    write_scope_audit_reset()
    yield
    write_scope_audit_reset()


# ── parse_write_scope：合法/非法分支 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "src/**",              # 字符串 raw
        42,
        ["src/**"],
        None,
        ("paths",),            # tuple 非 dict
    ],
)
def test_parse_rejects_non_dict(raw):
    assert parse_write_scope(raw) is None


def test_parse_rejects_paths_not_list():
    assert parse_write_scope({"paths": "src/**"}) is None
    assert parse_write_scope({"paths": {"a": 1}}) is None
    assert parse_write_scope({"paths": ("src/**",)}) is None  # 严格 list[str]


@pytest.mark.parametrize("bad", [1, None, b"src", True, ["src", ""]])
def test_parse_rejects_bad_path_elements(bad):
    assert parse_write_scope({"paths": [bad] if not isinstance(bad, list) else bad}) is None


def test_parse_rejects_empty_string_element():
    assert parse_write_scope({"paths": ["src/**", ""]}) is None


def test_parse_rejects_too_many_patterns():
    assert parse_write_scope({"paths": [f"p{i}" for i in range(MAX_PATTERNS + 1)]}) is None
    ok = parse_write_scope({"paths": [f"p{i}" for i in range(MAX_PATTERNS)]})
    assert ok is not None and len(ok.paths) == MAX_PATTERNS


def test_parse_rejects_overlong_pattern():
    assert parse_write_scope({"paths": ["a" * (MAX_PATTERN_LEN + 1)]}) is None
    ok = parse_write_scope({"paths": ["a" * MAX_PATTERN_LEN]})
    assert ok is not None


@pytest.mark.parametrize("bad_mode", ["read", "ALLOW", "", 1, True, None])
def test_parse_rejects_invalid_mode(bad_mode):
    assert parse_write_scope({"paths": ["src/**"], "mode": bad_mode}) is None


def test_parse_valid_allow_and_deny():
    ws = parse_write_scope({"paths": ["src/**", "docs/*.md"]})
    assert ws == WriteScope(paths=("src/**", "docs/*.md"), mode="allow", declared=True)
    deny = parse_write_scope({"paths": ["secrets/**"], "mode": "deny"})
    assert deny == WriteScope(paths=("secrets/**",), mode="deny", declared=True)
    # 未知键忽略（向前兼容）
    assert parse_write_scope({"paths": ["a"], "mode": "allow", "extra": 1}) is not None


def test_parse_empty_paths_is_readonly_declared():
    """paths=[] -> declared=True 且 paths 为空（只读语义，FR-4）."""
    ws = parse_write_scope({"paths": []})
    assert ws == WriteScope(paths=(), mode="allow", declared=True)
    assert parse_write_scope({"paths": [], "mode": "allow"}) == ws


def test_parse_missing_paths_key_means_inherit():
    """dict 内不含 paths 键 -> declared=False（键不存在 = 继承父，FR-3）."""
    assert parse_write_scope({}) == WriteScope(paths=(), mode="allow", declared=False)
    assert parse_write_scope({"mode": "allow"}) == WriteScope(paths=(), mode="allow", declared=False)


def test_write_scope_defaults():
    ws = WriteScope(("src",))
    assert ws.mode == "allow" and ws.declared is True and ws.deny_paths == ()


# ── scope_allows：四类 reason ────────────────────────────────────────────────


@pytest.fixture()
def ws_root(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return root


def test_allows_full_when_scope_none(ws_root):
    assert scope_allows(None, str(ws_root / "any/x.py"), str(ws_root)) == (True, "")
    # declared=False 同样按「未声明」归一 = 全量
    assert scope_allows(WriteScope((), declared=False), str(ws_root / "x"), str(ws_root)) == (True, "")


def test_allow_hit_and_miss(ws_root):
    scope = WriteScope(paths=("src/**",))
    assert scope_allows(scope, str(ws_root / "src" / "a" / "b.py"), str(ws_root)) == (True, "")
    ok, reason = scope_allows(scope, str(ws_root / "docs" / "x.md"), str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")


def test_readonly_scope_denies_everything(ws_root):
    scope = parse_write_scope({"paths": []})
    ok, reason = scope_allows(scope, str(ws_root / "src" / "a.py"), str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")


def test_glob_boundary_separator(ws_root):
    # "src/**" 命中 "src/a/b.py"；"src*" 不得命中 "srcevil/x.py"（分隔符边界）
    assert scope_allows(WriteScope(("src/**",)), str(ws_root / "src" / "a" / "b.py"), str(ws_root)) == (True, "")
    ok, reason = scope_allows(WriteScope(("src*",)), str(ws_root / "srcevil" / "x.py"), str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")
    # "src*" 允许根下单段（srcfoo 是文件名，非目录前缀误命中）
    assert scope_allows(WriteScope(("src*",)), str(ws_root / "srcfoo"), str(ws_root)) == (True, "")
    # 单段 * 不跨目录
    assert scope_allows(WriteScope(("src/*",)), str(ws_root / "src" / "a.py"), str(ws_root)) == (True, "")
    assert scope_allows(WriteScope(("src/*",)), str(ws_root / "src" / "a" / "b.py"), str(ws_root)) == (False, "not_in_allow_list")


def test_glob_double_star_variants(ws_root):
    assert scope_allows(WriteScope(("**",)), str(ws_root / "a" / "b" / "c"), str(ws_root)) == (True, "")
    assert scope_allows(WriteScope(("**/x.py",)), str(ws_root / "a" / "b" / "x.py"), str(ws_root)) == (True, "")
    assert scope_allows(WriteScope(("**/x.py",)), str(ws_root / "x.py"), str(ws_root)) == (True, "")
    assert scope_allows(WriteScope(("a/**/b",)), str(ws_root / "a" / "c" / "b"), str(ws_root)) == (True, "")
    assert scope_allows(WriteScope(("a/**/b",)), str(ws_root / "a" / "b"), str(ws_root)) == (True, "")


def test_deny_mode_and_deny_paths_priority(ws_root):
    deny_scope = WriteScope(paths=("secrets/**",), mode="deny")
    ok, reason = scope_allows(deny_scope, str(ws_root / "secrets" / "k"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    assert scope_allows(deny_scope, str(ws_root / "src" / "a.py"), str(ws_root)) == (True, "")
    # deny_paths 叠加集优先于 allow 集
    layered = WriteScope(paths=("src/**",), deny_paths=("src/forbidden.py",))
    ok, reason = scope_allows(layered, str(ws_root / "src" / "forbidden.py"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    assert scope_allows(layered, str(ws_root / "src" / "ok.py"), str(ws_root)) == (True, "")


def test_outside_scope_absolute(ws_root, tmp_path):
    other = tmp_path / "other-ws"
    other.mkdir()
    (other / "x.py").write_text("x")
    ok, reason = scope_allows(WriteScope(("**",)), str(other / "x.py"), str(ws_root))
    assert (ok, reason) == (False, "outside_scope")


def test_dotdot_traversal_rejected(ws_root, tmp_path):
    escape = os.path.join(str(ws_root), "sub", "..", "..", "escape.txt")
    ok, reason = scope_allows(WriteScope(("**",)), escape, str(ws_root))
    assert (ok, reason) == (False, "outside_scope")
    # root 内部的 ".." 折叠后仍在 root 内但不在 allow 集 → not_in_allow_list
    inside = os.path.join(str(ws_root), "docs", "..", "secrets", "x")
    ok, reason = scope_allows(WriteScope(("docs/**",)), inside, str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")


def test_symlink_escape_rejected(ws_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = ws_root / "lnk"
    link.symlink_to(outside)
    ok, reason = scope_allows(WriteScope(("lnk/**",)), str(link / "x.txt"), str(ws_root))
    assert (ok, reason) == (False, "outside_scope")


def test_symlink_inside_root_normalizes(ws_root):
    src = ws_root / "src"
    src.mkdir()
    alias = ws_root / "alias"
    alias.symlink_to(src)
    scope = WriteScope(paths=("src/**",))
    assert scope_allows(scope, str(alias / "a.py"), str(ws_root)) == (True, "")


def test_relative_path_resolved_against_workspace_root(ws_root):
    ok, reason = scope_allows(WriteScope(("src/**",)), "src/a.py", str(ws_root))
    assert (ok, reason) == (True, "")
    ok, reason = scope_allows(WriteScope(("src/**",)), "docs/a.md", str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")


@pytest.mark.skipif(sys.platform != "darwin", reason="darwin 大小写不敏感文件系统口径")
def test_casefold_on_darwin(ws_root):
    ok, reason = scope_allows(WriteScope(("src/**",)), str(ws_root / "SRC" / "a.py"), str(ws_root))
    assert (ok, reason) == (True, "")


# ── intersect_write_scope：继承 / 全量 / 越界拒绝 / 覆盖 / deny 叠加 ─────────


def test_intersect_child_undeclared_inherits_parent():
    parent = WriteScope(paths=("src/**",))
    assert intersect_write_scope(parent, None) == (parent, "")
    assert intersect_write_scope(parent, WriteScope((), declared=False)) == (parent, "")


def test_intersect_parent_full_child_effective():
    child = WriteScope(paths=("src/**",))
    assert intersect_write_scope(None, child) == (child, "")
    assert intersect_write_scope(WriteScope((), declared=False), child) == (child, "")


def test_intersect_child_out_of_parent_refused_with_detail():
    parent = WriteScope(paths=("src/**",))
    child = WriteScope(paths=("src/**", "secrets/**", "docs/x.md"))
    effective, detail = intersect_write_scope(parent, child)
    assert effective is None
    assert detail.startswith("write_scope 声明超出父 scope")
    assert "secrets/**" in detail and "docs/x.md" in detail
    assert "src/**" not in detail  # 已覆盖项不进越界列表


def test_intersect_parent_allow_covers_child_allow():
    parent = WriteScope(paths=("src/**", "docs"))
    child = WriteScope(paths=("src/llm_loop/**",))
    effective, detail = intersect_write_scope(parent, child)
    assert detail == ""
    assert effective == WriteScope(paths=("src/llm_loop/**",), mode="allow", declared=True)
    # 目录前缀覆盖：q 是 p 的目录前缀（q + "/" 是 p 前缀）
    eff2, _ = intersect_write_scope(parent, WriteScope(paths=("docs/x.md",)))
    assert eff2 is not None


def test_intersect_coverage_is_conservative():
    # "src/*" 覆盖不了 "src/a"（glob-in-glob 不可证明 → fail-closed 拒绝）
    parent = WriteScope(paths=("src/*",))
    effective, detail = intersect_write_scope(parent, WriteScope(paths=("src/a",)))
    assert effective is None and "src/a" in detail
    # 父 "src/**" 覆盖子裸目录 "src"（p == q[:-3] 目录本身，路径级合取成立）
    effective, detail = intersect_write_scope(
        WriteScope(paths=("src/**",)), WriteScope(paths=("src",))
    )
    assert detail == "" and effective is not None and effective.paths == ("src",)
    # 分隔符边界：父 "src/**" 不覆盖 "srcevil/x"（合取原则，防前缀误认）
    effective, detail = intersect_write_scope(
        WriteScope(paths=("src/**",)), WriteScope(paths=("srcevil/x",))
    )
    assert effective is None and "srcevil/x" in detail


def test_intersect_deny_child_stacks_deny():
    parent = WriteScope(paths=("src/**",), deny_paths=("src/old.py",))
    child = WriteScope(paths=("src/tmp/**",), mode="deny")
    effective, detail = intersect_write_scope(parent, child)
    assert detail == ""
    assert effective is not None
    assert effective.paths == ("src/**",)
    assert effective.mode == "allow"
    assert effective.deny_paths == ("src/old.py", "src/tmp/**")


def test_intersect_parent_deny_mode_conjoins_as_predicates(ws_root):
    # 父 deny 模式：子 allow 生效但父排除集必须保留（路径谓词合取，不是集合运算）
    parent = WriteScope(paths=("secrets/**",), mode="deny")
    child = WriteScope(paths=("src/**",))
    effective, detail = intersect_write_scope(parent, child)
    assert detail == ""
    assert effective is not None
    assert effective.paths == ("src/**",)
    assert "secrets/**" in effective.deny_paths
    ok, reason = scope_allows(effective, str(ws_root / "secrets" / "k"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    assert scope_allows(effective, str(ws_root / "src" / "a.py"), str(ws_root)) == (True, "")


def test_intersect_effective_enforcement_semantics(ws_root):
    # 求交结果对单路径判定等价于交集：父 src/** ∩ 子 src/llm_loop/** → 子集生效
    parent = WriteScope(paths=("src/**",))
    child = WriteScope(paths=("src/llm_loop/**",))
    effective, _ = intersect_write_scope(parent, child)
    assert scope_allows(effective, str(ws_root / "src" / "llm_loop" / "x.py"), str(ws_root)) == (True, "")
    ok, reason = scope_allows(effective, str(ws_root / "src" / "other" / "x.py"), str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")


# ── 审计（进程内；跨进程丢失为 P0 已知边界）──────────────────────────────────


def test_audit_record_and_snapshot():
    write_scope_audit_record_write("/ws/src/a.py")
    write_scope_audit_record_write("/ws/src/b.py")
    write_scope_audit_record_violation("/ws/secrets/k", "not_in_allow_list")
    snap = write_scope_audit_snapshot()
    assert snap["written_paths"] == ["/ws/src/a.py", "/ws/src/b.py"]
    assert snap["violations"] == [{"path": "/ws/secrets/k", "reason": "not_in_allow_list"}]
    assert snap["violation_count"] == 1
    # 快照是拷贝，持有后继续记录不受影响
    write_scope_audit_record_write("/ws/src/c.py")
    assert snap["written_paths"] == ["/ws/src/a.py", "/ws/src/b.py"]


def test_audit_thread_visibility():
    import threading

    errs: list[str] = []

    def worker():
        try:
            write_scope_audit_record_write("/ws/t/x")
            write_scope_audit_record_violation("/ws/t/y", "outside_scope")
        except Exception as exc:  # pragma: no cover
            errs.append(repr(exc))

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert not errs
    snap = write_scope_audit_snapshot()
    assert snap["written_paths"] == ["/ws/t/x"] and snap["violation_count"] == 1


# ── SurfaceRequirements 接线（execution_surface.py 小改）────────────────────


def test_from_kwargs_without_write_scope_zero_regression():
    reqs = SurfaceRequirements.from_kwargs({"tools": ["read_file"], "network": True})
    assert reqs is not None
    assert reqs.write_scope is None
    assert reqs.declared() is True
    empty = SurfaceRequirements.from_kwargs({})
    assert empty is not None and empty.write_scope is None and empty.declared() is False


def test_from_kwargs_parses_valid_write_scope():
    reqs = SurfaceRequirements.from_kwargs({"write_scope": {"paths": ["src/**"]}})
    assert reqs is not None
    assert reqs.write_scope == WriteScope(paths=("src/**",), mode="allow", declared=True)
    assert reqs.declared() is True  # 显式声明（含只读）计为 declared


def test_from_kwargs_readonly_write_scope_counts_declared():
    reqs = SurfaceRequirements.from_kwargs({"write_scope": {"paths": []}})
    assert reqs is not None
    assert reqs.write_scope is not None and reqs.write_scope.declared is True
    assert reqs.declared() is True


def test_from_kwargs_undeclared_write_scope_not_counted():
    reqs = SurfaceRequirements.from_kwargs({"write_scope": {}})  # 无 paths 键 = 继承
    assert reqs is not None
    assert reqs.write_scope == WriteScope(paths=(), mode="allow", declared=False)
    assert reqs.declared() is False


@pytest.mark.parametrize(
    "raw",
    [
        {"write_scope": "src/**"},
        {"write_scope": {"paths": "src/**"}},
        {"write_scope": {"paths": ["src/**", ""]}},
        {"write_scope": {"paths": ["src/**"], "mode": "read"}},
        {"write_scope": None},
        {"write_scope": 5},
    ],
)
def test_from_kwargs_invalid_write_scope_returns_none(raw):
    assert SurfaceRequirements.from_kwargs(raw) is None


# ── run_context 注入点 ───────────────────────────────────────────────────────


def test_current_write_scope_defaults_to_none():
    assert current_write_scope.get() is None  # 默认 None = 全量（零回归）
    token = current_write_scope.set(WriteScope(paths=("src/**",)))
    try:
        assert current_write_scope.get() == WriteScope(paths=("src/**",))
    finally:
        current_write_scope.reset(token)
    assert current_write_scope.get() is None


# ── 返修新增（P1-1 / P2-1 / P2-6）：deny∩deny 求交 / 空 paths+deny 非法 /
#    pattern 归一 ────────────────────────────────────────────────────────────


def test_intersect_deny_deny_allows_public_and_denies_union(ws_root):
    """P1-1：deny ∩ deny 的正确语义 = 「除 P∪C 之外都允许」（路径谓词合取）.

    语义依据：parent 谓词 = ¬P，child 谓词 = ¬C，合取 = ¬(P∪C)，恰是 deny
    模式的原生形态（paths=排除集）。修复采用「结果用既有 deny 模式形态表达」
    （任务书方案 A 的 allow_all 字段的等价替代且更小改动）：零新表示法、
    对孙代求交封闭、观测/回执面对 mode=deny 的文案准确（若用 allow 模式 +
    空 allow 集，file_service 预览会误标「空集合=只读执行域」）。
    """
    parent = WriteScope(paths=("secret/**",), mode="deny", declared=True)
    child = WriteScope(paths=("private/**",), mode="deny", declared=True)
    effective, detail = intersect_write_scope(parent, child)
    assert detail == ""
    assert effective is not None
    # 产物是 deny 模式（排除集 = P∪C），不是 allow 模式 + 空 allow 集
    assert effective.mode == "deny"
    assert set(effective.paths) == {"secret/**", "private/**"}
    # public 路径既不在 secret/** 也不在 private/** → 应当允许（修复前被误拒）
    assert scope_allows(effective, str(ws_root / "public" / "x.txt"), str(ws_root)) == (True, "")
    # deny 命中路径拒绝，且原因是 deny 相关——绝不是 not_in_allow_list（修复前的误导原因）
    ok, reason = scope_allows(effective, str(ws_root / "secret" / "x.txt"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    ok, reason = scope_allows(effective, str(ws_root / "private" / "x.txt"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")


def test_intersect_deny_deny_produces_no_empty_allow_trap(ws_root):
    """P1-1 配套：deny∩deny 产物不得落入「空 allow 集拒绝一切」形态.

    （对应任务书第 2 条。本修复未采用 allow_all 字段，等价断言为：产物不是
    allow 模式空 paths——该形态在判定上=只读=拒绝一切——且非排除集路径全部放行。）
    """
    effective, detail = intersect_write_scope(
        WriteScope(paths=("secret/**",), mode="deny"),
        WriteScope(paths=("private/**",), mode="deny"),
    )
    assert detail == "" and effective is not None
    assert not (effective.mode == "allow" and effective.paths == ())
    for rel in ("public/x.txt", "src/a/b.py", "docs/m.md"):
        assert scope_allows(effective, str(ws_root / rel), str(ws_root)) == (True, "")


def test_intersect_deny_deny_result_composes_with_grandchild(ws_root):
    """P1-1：deny∩deny 产物作为父再与孙声明求交（表示法封闭性）.

    - 孙 allow(src/**)：孙 allow 集生效 + 父排除集逐路径保留——与
      parent-deny + child-allow 组合语义一致（见既有
      test_intersect_parent_deny_mode_conjoins_as_predicates）；
    - 孙 deny(tmp/**)：排除集继续并集叠加。
    """
    eff_deny_deny, detail = intersect_write_scope(
        WriteScope(paths=("secret/**",), mode="deny"),
        WriteScope(paths=("private/**",), mode="deny"),
    )
    assert detail == ""
    # 孙代 allow：父（deny 模式）排除集保留，孙 allow 集生效
    eff_allow, detail = intersect_write_scope(eff_deny_deny, WriteScope(paths=("src/**",)))
    assert detail == "" and eff_allow is not None
    assert eff_allow.paths == ("src/**",) and eff_allow.mode == "allow"
    assert set(eff_allow.deny_paths) == {"secret/**", "private/**"}
    assert scope_allows(eff_allow, str(ws_root / "src" / "a.py"), str(ws_root)) == (True, "")
    ok, reason = scope_allows(eff_allow, str(ws_root / "secret" / "k"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    ok, reason = scope_allows(eff_allow, str(ws_root / "public" / "x"), str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")
    # 孙代 deny：排除集并集叠加，仍是「除并集外全允许」
    eff_deny, detail = intersect_write_scope(
        eff_deny_deny, WriteScope(paths=("tmp/**",), mode="deny")
    )
    assert detail == "" and eff_deny is not None
    assert set(eff_deny.paths) == {"secret/**", "private/**", "tmp/**"}
    assert eff_deny.mode == "deny"
    assert scope_allows(eff_deny, str(ws_root / "public" / "x"), str(ws_root)) == (True, "")


def test_parse_rejects_empty_paths_with_deny_mode():
    """P2-1：``{"paths": [], "mode": "deny"}`` 是非法结构 → None.

    语义定义（与 P1-1 修复统一）：allow 模式下 paths=允许集，空=只读（FR-4）；
    deny 模式下 paths=排除集，空=「排除空集=全量放行」——与只读外观方向相反，
    构成「看起来只读、实际全量」的 fail-open 陷阱，解析层确定性拒绝。
    只读写法：``{"paths": []}``；全量写法：不声明 write_scope 或 ``{}``。
    """
    assert parse_write_scope({"paths": [], "mode": "deny"}) is None
    # FR-4 只读语义不回归（allow 模式空集仍合法且 declared）
    assert parse_write_scope({"paths": []}) == WriteScope(paths=(), mode="allow", declared=True)
    assert parse_write_scope({"paths": [], "mode": "allow"}) == WriteScope(
        paths=(), mode="allow", declared=True
    )


def test_spawn_rejects_empty_deny_write_scope_as_param_error():
    """P2-1 端到端：spawn 层对该声明回参数错误（非静默接受、非全量放行）.

    链路：SpawnSubAgentTool.execute → SurfaceRequirements.from_kwargs →
    parse_write_scope 返回 None → from_kwargs 返回 None → 「[参数错误]」回执。
    未修改 spawn_subagent.py；端到端行为依赖 parse 返回 None，既有 spawn
    参数错误链路自动覆盖（本测试用真实工具类钉住这一端到端事实）。
    """
    calls: list[dict] = []

    class RecordingRunner:
        registry = SimpleNamespace(names=lambda: ["read_file", "execute_command", "wait"])

        def start(self, **kwargs):  # pragma: no cover - 参数错误下不应被触达
            calls.append(kwargs)
            return {"accepted": True, "child_id": "c", "state": "running", "depth": 0, "model": ""}

    res = SpawnSubAgentTool(RecordingRunner()).execute(
        task="空排除集 deny 陷阱声明",
        requires={"write_scope": {"paths": [], "mode": "deny"}},
    )
    assert res.status.value == "failure"
    assert "[参数错误]" in res.content
    assert calls == []  # 参数错误发生在进入 runner 之前，未启动任何 child


def test_parse_normalizes_pattern_forms(ws_root):
    """P2-6：pattern 在解析层归一（去前导 ``./``、前导 ``/``、尾部 ``/``）."""
    ws = parse_write_scope({"paths": ["./src/**", "/docs/", "pkg/"]})
    assert ws is not None
    assert ws.paths == ("src/**", "docs", "pkg")
    # 归一后 allow 判定照常：src/** 仍命中 src/a/b.py
    assert scope_allows(ws, str(ws_root / "src" / "a" / "b.py"), str(ws_root)) == (True, "")


def test_intersect_equivalent_pattern_forms_not_false_overflow(ws_root):
    """P2-6：父 ``src/**`` 视为覆盖子 ``./src/a``（形态等价），不再误拒.

    修复前 ``_covered_by`` 比较未归一字符串，``"./src/a"`` 被误判超出父
    ``src/**`` → refused（fail-closed 误伤合法声明）。
    """
    parent = parse_write_scope({"paths": ["src/**"]})
    child = parse_write_scope({"paths": ["./src/a"]})
    effective, detail = intersect_write_scope(parent, child)
    assert detail == ""
    assert effective is not None
    assert effective.paths == ("src/a",)
    assert scope_allows(effective, str(ws_root / "src" / "a"), str(ws_root)) == (True, "")


# ── 返修新增（第二轮 A）：deny 空转排除项 fail-open 边缘 ─────────────────────
#
# 语义决策（选定**选项 3**，与 core/write_scope.py 内注释同步）：
# - deny 模式：归一后为空的根指称形态（""/"."/"./"/"/"/"//"…）或含空段、
#   "."/".." 段的排除项**一律非法结构** → parse 返回 None → 走既有
#   「非法 → 参数错误」链路（与 P2-1 空 paths+deny 同性质、同链路）。理由：
#   该类排除项永不匹配任何路径，单条即等价空排除集 = 全量放行（fail-open）；
#   与其猜意图（选项 2「空 pattern 在 deny 模式匹配一切」反直觉），不如
#   fail-closed 拒绝声明（父代理倾向的选项 1/3 中取 3）。
# - allow 模式：同形态保持合法 = 空转 allow 条目（贡献为空），单条等价
#   ``paths=[]`` 只读（FR-4），方向 fail-closed，无需拒绝。
# 修前实测（父级与本轮双重验证）：``{"paths": ["./"], "mode": "deny"}``
# 解析成功且 ``scope_allows`` 对任意路径 ``(True, "")`` —— 全量放行。


@pytest.mark.parametrize("bad", ["./", "/", "//", "///", "/.", "./.", "././", "."])
def test_parse_rejects_root_denoting_deny_entries(bad):
    """返修 A：根指称形态的 deny 排除项 = 空转排除 = 全量放行陷阱 → None."""
    assert parse_write_scope({"paths": [bad], "mode": "deny"}) is None


@pytest.mark.parametrize(
    "bad", ["a//b", "src/./x", "../x", "..", "x/../y", "secrets//**"]
)
def test_parse_rejects_degenerate_segment_deny_entries(bad):
    """返修 A 同类枚举：空段/``.``/``..`` 段的 deny 排除项永不匹配 → None.

    实测（修前）：deny 模式下这些形态对 workspace 内任意路径 ``(True, "")``
    ——relpath 产物不含空段与 ``.``/``..`` 段，排除项永不命中，单条即全量
    放行。与根指称形态同性质，一并确定性拒绝。
    """
    assert parse_write_scope({"paths": [bad], "mode": "deny"}) is None


def test_parse_rejects_mixed_deny_decl_containing_idle_entry():
    """混合声明混入空转排除项同样整单拒绝（不静默丢弃该条目、不静默放行）.

    修前实测：``{"paths": ["./", "secrets/**"], "mode": "deny"}`` 解析成功、
    secrets/k 仍被拒（有效条目生效）；但空转条目的存在说明声明者对语义有
    误解，静默丢弃会掩盖它——整单 None，让调用方显式改写声明。
    """
    assert parse_write_scope({"paths": ["./", "secrets/**"], "mode": "deny"}) is None
    # 对照：全部条目可用时仍合法（不被本修复误伤）
    ok = parse_write_scope({"paths": ["secrets/**", "private/*"], "mode": "deny"})
    assert ok is not None and ok.mode == "deny" and ok.paths == ("secrets/**", "private/*")


@pytest.mark.parametrize("form", ["./", "/", "//", "."])
def test_root_denoting_allow_entry_is_readonly_not_full_allow(ws_root, form):
    """返修 A：allow 模式根指称 pattern 归一为空串 = 空转 allow 条目 = 只读.

    修前实测：``{"paths": ["./"], "mode": "allow"}`` 已是「全拒 +
    not_in_allow_list」（fail-closed，方向正确，保留）；唯一怪异是 ``"."``
    形态会放行 workspace 根本身（rel=="." 命中 ``\\.``）。修后根指称统一
    归一为 ``""``（永不匹配），root 本身也拒——收紧到纯只读，与
    ``paths=[]``（FR-4）口径完全一致。断言其**不是**全量放行。
    """
    ws = parse_write_scope({"paths": [form], "mode": "allow"})
    assert ws is not None
    assert ws.paths == ("",), form  # 根指称统一存储形态
    for rel in ["src/a/b.py", "docs/x.md", "README.md"]:
        ok, reason = scope_allows(ws, str(ws_root / rel), str(ws_root))
        assert (ok, reason) == (False, "not_in_allow_list"), (form, rel)
    # root 本身也拒（修前 "." 形态此处为 True，统一收紧）；与 paths=[] 同 reason
    assert scope_allows(ws, str(ws_root), str(ws_root)) == (False, "not_in_allow_list")
    readonly = parse_write_scope({"paths": []})
    assert scope_allows(readonly, str(ws_root / "src" / "a.py"), str(ws_root)) == (
        False,
        "not_in_allow_list",
    )


def test_deny_and_glob_semantics_unchanged_after_idle_entry_fix(ws_root):
    """返修 A 回归：正常 pattern / deny 语义零变化（防修复扩成 glob 语义漂移）.

    - ``src/**`` 仍命中 ``src/a/b.py``；``src*`` 仍不命中 ``srcevil/x.py``；
    - ``**/``（尾部 ``/`` 剥离后即 ``**``）不是空转项：deny 模式仍=排除一切，
      allow 模式仍=允许树内一切；
    - deny∩deny（P1-1）仍让 public 放行、secret/private 拒绝。
    """
    assert scope_allows(WriteScope(("src/**",)), str(ws_root / "src" / "a" / "b.py"), str(ws_root)) == (True, "")
    ok, reason = scope_allows(WriteScope(("src*",)), str(ws_root / "srcevil" / "x.py"), str(ws_root))
    assert (ok, reason) == (False, "not_in_allow_list")
    deny_all = parse_write_scope({"paths": ["**/"], "mode": "deny"})
    assert deny_all is not None and deny_all.paths == ("**",)
    ok, reason = scope_allows(deny_all, str(ws_root / "src" / "a.py"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    allow_all = parse_write_scope({"paths": ["**/"], "mode": "allow"})
    assert allow_all is not None
    assert scope_allows(allow_all, str(ws_root / "src" / "a.py"), str(ws_root)) == (True, "")
    eff, detail = intersect_write_scope(
        WriteScope(paths=("secret/**",), mode="deny"),
        WriteScope(paths=("private/**",), mode="deny"),
    )
    assert detail == "" and eff is not None
    assert scope_allows(eff, str(ws_root / "public" / "x.txt"), str(ws_root)) == (True, "")
    ok, reason = scope_allows(eff, str(ws_root / "secret" / "x.txt"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")
    ok, reason = scope_allows(eff, str(ws_root / "private" / "x.txt"), str(ws_root))
    assert (ok, reason) == (False, "denied_by_deny_list")


def test_spawn_rejects_root_denying_deny_write_scope_as_param_error():
    """返修 A 端到端：spawn 对 ``{"paths": ["./"], "mode": "deny"}`` 回参数错误.

    修前实测：该声明解析成功且判定为全量放行（fail-open）。修复后
    parse → None → SurfaceRequirements.from_kwargs → None → 「[参数错误]」
    （与 P2-1 同链路；未修改 spawn_subagent.py）。
    """
    calls: list[dict] = []

    class RecordingRunner:
        registry = SimpleNamespace(names=lambda: ["read_file", "execute_command", "wait"])

        def start(self, **kwargs):  # pragma: no cover - 参数错误下不应被触达
            calls.append(kwargs)
            return {"accepted": True, "child_id": "c", "state": "running", "depth": 0, "model": ""}

    res = SpawnSubAgentTool(RecordingRunner()).execute(
        task="根指称空转排除集声明",
        requires={"write_scope": {"paths": ["./"], "mode": "deny"}},
    )
    assert res.status.value == "failure"
    assert "[参数错误]" in res.content
    assert calls == []  # 参数错误发生在进入 runner 之前，未启动任何 child
