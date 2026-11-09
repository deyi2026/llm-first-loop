"""T05 单测：sandbox_argv writable_roots 透传 + compile_scope_roots 三分类纯编译.

覆盖（任务书 C 项）：
- 判定表全部 5 类：equivalent（X/**、X/Y/**、./X/** 归一）/ amplifying（裸 X、
  字面 X/Y、X/**/Y、X/*）/ unverifiable（**/Y、*abc、**、字面前缀为空的根指称
  形态 "."、"/"）/ deny 模式 → not_supported；
- 额外 fail-closed 边界：deny_paths 非空 → not_supported、未声明（None /
  declared=False）→ not_supported、显式只读（paths=[]）→ ok 且 roots 空；
- 「裸目录名放大」前提的交叉验证：scope_allows 对 docs/a.md 拒绝（父级实测事实）；
- sandbox_argv 默认 writable_roots=() 时 sandbox-exec argv 与既有产物**逐元素相等**
  （= 改动前 sandbox_exec_argv(command, workdir) 的字节等价形态）；显式传参时
  追加根进入 profile；bwrap/docker/none 对该参数零效果（argv/note 不变）。
"""

from __future__ import annotations

import os
import sys

import pytest

from llm_loop.core.write_scope import (
    SCOPE_ROOT_AMPLIFYING,
    SCOPE_ROOT_EQUIVALENT,
    SCOPE_ROOT_UNVERIFIABLE,
    WriteScope,
    compile_scope_roots,
    parse_write_scope,
    scope_allows,
)
from llm_loop.tools import sandbox as sbx
from tests import env_channel

WS = "/tmp/ws-t05"  # 判定用 workspace_root：realpath 不要求存在，无需真实建目录


def _base() -> str:
    """与实现同口径的 root 基准：realpath(expanduser(workspace_root))."""
    return os.path.realpath(os.path.expanduser(WS))


# ── compile_scope_roots：判定表（B）─────────────────────────────────────────


@pytest.mark.parametrize(
    "pattern,sub",
    [("src/**", "src"), ("docs/img/**", "docs/img"), ("./src/**", "src")],
)
def test_compile_tail_doublestar_equivalent(pattern, sub):
    """判定表 1：通配仅在尾部 → equivalent，subpath=去尾 ** 的字面前缀."""
    scope = parse_write_scope({"paths": [pattern]})
    assert scope is not None
    result = compile_scope_roots(scope, WS)
    assert result.status == "ok"
    (root,) = result.roots
    assert root.pattern == sub + "/**"  # 归一形态（./src/** ≡ src/**）
    assert root.classification == SCOPE_ROOT_EQUIVALENT
    assert root.subpath == sub
    assert root.root == os.path.join(_base(), sub)


def test_compile_bare_dirname_amplifying():
    """判定表 2：裸目录名 → amplifying（LFL 子路径零命中，内核 subpath 放行子树）."""
    scope = parse_write_scope({"paths": ["docs"]})
    result = compile_scope_roots(scope, WS)
    assert result.status == "ok"
    (root,) = result.roots
    assert root.classification == SCOPE_ROOT_AMPLIFYING
    assert root.subpath == "docs"
    assert root.root == os.path.join(_base(), "docs")
    assert root.detail  # 必须带说明（单列 + 放大原因）
    assert "放大" in root.detail
    # 放大前提交叉验证（父级实测）：裸目录名在 LFL 层对子路径零命中（fail-closed）
    allowed, reason = scope_allows(scope, os.path.join(WS, "docs", "a.md"), WS)
    assert allowed is False
    assert reason == "not_in_allow_list"


def test_compile_literal_multiseg_amplifying():
    """判定表 2 同类：字面多段路径 X/Y（无通配）→ amplifying."""
    scope = parse_write_scope({"paths": ["docs/img"]})
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_AMPLIFYING
    assert root.subpath == "docs/img"
    assert "放大" in root.detail


@pytest.mark.parametrize(
    "pattern,sub",
    [("src/**/tmp", "src"), ("assets/*", "assets"), ("a/**/b/**", "a")],
)
def test_compile_mid_wildcard_amplifying(pattern, sub):
    """判定表 3：中段通配（X/**/Y 及 X/* 等形态）→ amplifying，subpath=字面前缀."""
    scope = parse_write_scope({"paths": [pattern]})
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_AMPLIFYING
    assert root.subpath == sub
    assert root.root == os.path.join(_base(), sub)
    assert "放大" in root.detail


@pytest.mark.parametrize("pattern", ["**/logs", "*abc", "**", ".", "/", "./"])
def test_compile_wildcard_leading_or_empty_prefix_unverifiable(pattern):
    """判定表 4：通配开头或字面前缀为空（含根指称归一形态）→ unverifiable."""
    scope = parse_write_scope({"paths": [pattern]})
    assert scope is not None
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None
    assert root.root is None
    assert "fail-closed" in root.detail


def test_compile_deny_mode_not_supported():
    """判定表 5：deny 模式 → 整体 not_supported，roots 恒空（绝不编译成内核 allow）."""
    scope = parse_write_scope({"paths": ["src/**"], "mode": "deny"})
    assert scope is not None
    result = compile_scope_roots(scope, WS)
    assert result.status == "not_supported"
    assert result.roots == ()
    assert "deny" in result.detail


def test_compile_deny_paths_not_supported():
    """额外 fail-closed：allow 模式但 deny_paths 非空 → 整体不编译（等价性不可证明）."""
    scope = WriteScope(
        paths=("src/**",),
        mode="allow",
        declared=True,
        deny_paths=("src/secret/**",),
    )
    result = compile_scope_roots(scope, WS)
    assert result.status == "not_supported"
    assert result.roots == ()
    assert "deny_paths" in result.detail


def test_compile_undeclared_scope_not_supported():
    """额外 fail-closed：未声明（None / declared=False=继承父）→ 不纳入内核化."""
    assert compile_scope_roots(None, WS).status == "not_supported"
    undeclared = parse_write_scope({})
    assert undeclared is not None and not undeclared.declared
    assert compile_scope_roots(undeclared, WS).status == "not_supported"


def test_compile_readonly_empty_paths_ok_no_roots():
    """allow 空 paths（显式只读，FR-4）→ ok 且无可编译条目."""
    scope = parse_write_scope({"paths": []})
    result = compile_scope_roots(scope, WS)
    assert result.status == "ok"
    assert result.roots == ()


def test_compile_mixed_classification_preserves_order():
    """混合 scope：三分类各自成立且与 paths 声明同序，detail 含计数汇总."""
    scope = parse_write_scope({"paths": ["src/**", "docs", "**/logs"]})
    result = compile_scope_roots(scope, WS)
    assert result.status == "ok"
    assert [r.classification for r in result.roots] == [
        SCOPE_ROOT_EQUIVALENT,
        SCOPE_ROOT_AMPLIFYING,
        SCOPE_ROOT_UNVERIFIABLE,
    ]
    assert [r.subpath for r in result.roots] == ["src", "docs", None]
    assert "equivalent 1" in result.detail
    assert "amplifying 1" in result.detail
    assert "unverifiable 1" in result.detail


def test_compile_equivalent_matches_scope_allows_semantics():
    """equivalent 的语义抽查：X/** 的 glob 命中集 = X 子树（含 X 本身），不外溢."""
    scope = parse_write_scope({"paths": ["src/**"]})
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_EQUIVALENT
    for rel in ("src", "src/a.py", "src/deep/nested/b.py"):
        allowed, _ = scope_allows(scope, os.path.join(WS, rel), WS)
        assert allowed, rel
    allowed, reason = scope_allows(scope, os.path.join(WS, "srcevil", "x.py"), WS)
    assert not allowed
    assert reason == "not_in_allow_list"


# ── sandbox_argv：writable_roots 透传（A）────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_auto_cache():
    sbx.reset_auto_cache()
    yield
    sbx.reset_auto_cache()


def _enable_sandbox_exec(monkeypatch):
    """hermetic 打开 sandbox-exec 后端（只构造 argv，不真执行任何命令）."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sbx.os.path, "isfile", lambda p: p == sbx._SANDBOX_EXEC)
    monkeypatch.setattr(sbx.os, "access", lambda p, m: True)
    monkeypatch.delenv("EXEC_SANDBOX_MACOS_WRITABLE", raising=False)
    monkeypatch.delenv("EXEC_SANDBOX_STRICT", raising=False)


@pytest.mark.skipif(
    env_channel.nested_sandbox_exec(),
    reason="嵌套 sandbox-exec 内无法自证套用；真实宿主环境照常运行",
)
def test_sandbox_argv_default_roots_identical_to_legacy(monkeypatch):
    """默认 writable_roots=() 与改动前字节等价：产物逐元素等于既有构造公式."""
    _enable_sandbox_exec(monkeypatch)
    argv, note = sbx.sandbox_argv("echo hi", "/w", mode="sandbox-exec")
    # 改动前实现即 sandbox_exec_argv(command, abspath(workdir))（extra=()）：
    # 此处按同一公式重算并逐元素比对（argv 列表断言）
    expected = sbx.sandbox_exec_argv("echo hi", os.path.abspath("/w"))
    assert argv == expected
    assert argv == [
        sbx._SANDBOX_EXEC,
        "-p",
        sbx.sandbox_exec_profile(sbx.macos_writable_roots(os.path.abspath("/w"))),
        "/bin/bash",
        "-lc",
        "echo hi",
    ]
    assert note == sbx._SANDBOX_EXEC_NOTE
    # 显式传空元组 = 不传（字节等价）；默认 profile 不含任何追加根
    explicit, _ = sbx.sandbox_argv(
        "echo hi", "/w", mode="sandbox-exec", writable_roots=()
    )
    assert explicit == argv
    assert "/extra" not in argv[2]


@pytest.mark.skipif(
    env_channel.nested_sandbox_exec(),
    reason="嵌套 sandbox-exec 内无法自证套用；真实宿主环境照常运行",
)
def test_sandbox_argv_passthrough_writable_roots(monkeypatch):
    """显式 writable_roots → 原样透传进 sandbox-exec profile 的 allow subpath."""
    _enable_sandbox_exec(monkeypatch)
    argv, _ = sbx.sandbox_argv(
        "echo hi", "/w", mode="sandbox-exec", writable_roots=("/extra/root",)
    )
    expected_profile = sbx.sandbox_exec_profile(
        sbx.macos_writable_roots("/w", extra=("/extra/root",))
    )
    assert argv == [
        sbx._SANDBOX_EXEC,
        "-p",
        expected_profile,
        "/bin/bash",
        "-lc",
        "echo hi",
    ]
    assert '(allow file-write* (subpath "/extra/root"))' in argv[2]
    # Sequence[str] 契约：list 亦可，多根逐一生效
    argv_list, _ = sbx.sandbox_argv(
        "echo hi", "/w", mode="sandbox-exec", writable_roots=["/r1", "/r2"]
    )
    assert '(allow file-write* (subpath "/r1"))' in argv_list[2]
    assert '(allow file-write* (subpath "/r2"))' in argv_list[2]


@pytest.mark.skipif(
    env_channel.docker_cli_available() or env_channel.nested_sandbox_exec(),
    reason="auto 后端在 docker 存在或嵌套 sandbox 下会解析到 docker/none，非本用例断言路径",
)
def test_sandbox_argv_auto_backend_passthrough(monkeypatch):
    """auto 解析到 sandbox-exec 时同样透传（mode 被改写为 backend 后走同一分支）."""
    _enable_sandbox_exec(monkeypatch)
    argv, _ = sbx.sandbox_argv(
        "echo hi", "/w", mode="auto", writable_roots=("/extra/root",)
    )
    assert argv is not None
    assert '(allow file-write* (subpath "/extra/root"))' in argv[2]


def test_sandbox_argv_other_backends_ignore_writable_roots(monkeypatch):
    """bwrap/docker/none：可写域结构性=工作区，writable_roots 不影响 argv。

    note 口径（T05 审查 P2-2）：bwrap/docker 在 roots 非空时必须**明示**该参数被
    忽略；none 本身无隔离，保持空 note。
    """
    monkeypatch.delenv("EXEC_SANDBOX_STRICT", raising=False)
    monkeypatch.setattr(
        sbx.shutil,
        "which",
        lambda name: {"bwrap": "/usr/bin/bwrap", "docker": "/usr/local/bin/docker"}.get(name),
    )
    for mode in ("none", "bwrap", "docker"):
        with_roots, note_a = sbx.sandbox_argv(
            "echo hi", "/w", mode=mode, writable_roots=("/extra",)
        )
        without_roots, note_b = sbx.sandbox_argv("echo hi", "/w", mode=mode)
        assert with_roots == without_roots, mode
        if mode == "none":
            assert note_a == note_b == "", mode
        else:
            assert note_b in note_a, mode
            assert sbx._DROPPED_ROOTS_NOTE in note_a, mode
    none_argv, none_note = sbx.sandbox_argv(
        "echo hi", "/w", mode="none", writable_roots=("/extra",)
    )
    assert none_argv is None and none_note == ""
