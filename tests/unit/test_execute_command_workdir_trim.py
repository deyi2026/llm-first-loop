"""execute_command workdir/environment factual behavior tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool


def _tool() -> ExecuteCommandTool:
    return ExecuteCommandTool(timeout_s=15)


def test_workdir_applies_to_subprocess():
    """指定 workdir 后 pwd 输出 = workdir."""
    with tempfile.TemporaryDirectory() as d:
        r = _tool().execute(command="pwd", workdir=d)
        assert r.status.name == "SUCCESS", f"status={r.status}, content={r.content}"
        # 2026-08-21 摘要前置: 输出 = 元信息行 + 实际输出（取末行）
        out = r.content.strip().splitlines()[-1]
        # macOS /var → /private/var 符号链接，用 resolve 归一
        assert Path(out) == Path(d).resolve(), f"pwd 应为 {d}, 实际 {r.content}"


def test_workdir_missing_returns_failure():
    """workdir 不存在 → 如实失败回执."""
    r = _tool().execute(command="pwd", workdir="/nonexistent/definitely-not-here")
    assert r.status.name == "FAILURE", f"应失败, 实际 {r.status}"
    assert "不是有效目录" in r.content


def test_no_workdir_defaults_cwd():
    """未指定 workdir → 继承进程 cwd（零回归）."""
    r = _tool().execute(command="pwd")
    assert r.status.name == "SUCCESS"
    out = r.content.strip().splitlines()[-1]
    assert out == os.getcwd()


def test_llm_exec_cwd_injected():
    """LLM_EXEC_CWD 环境事实注入子进程."""
    r = _tool().execute(command="echo $LLM_EXEC_CWD")
    assert r.status.name == "SUCCESS"
    # 2026-08-21 摘要前置: 元信息行后为实际输出
    assert os.getcwd() in r.content


# ── EVO-20261105-64a037d9: 相对 workdir 的解析基准 ─────────────────────
# 缺陷：相对 workdir 按**进程 cwd** 解析，而子代理 fs_isolation 的进程 cwd 仍是
# 父仓库、工作区根才是隔离树——于是 workdir="." 静默落到父仓库，隔离失效且
# 回执不显示真实落点。下面两个断言锁住"基准=工作区根"与"回执回显绝对 cwd"。


def test_relative_dot_write_lands_in_workspace_root_not_parent_repo():
    """缺陷本体：workdir="." 的写入必须落在工作区根（隔离树），不能落到进程 cwd（父仓库）."""
    from llm_loop.core.run_context import current_workspace_root

    marker = "lfl-isolation-probe.tmp"
    repo_marker = Path(os.getcwd()) / marker
    with tempfile.TemporaryDirectory() as ws:
        root = Path(ws).resolve()
        tok = current_workspace_root.set(str(root))
        try:
            r = _tool().execute(command=f"echo probe > {marker}", workdir=".")
        finally:
            current_workspace_root.reset(tok)
        assert r.status.name == "SUCCESS", f"content={r.content}"
        assert (root / marker).exists(), "写入应落在工作区根"
        assert not repo_marker.exists(), "写入不得泄漏到进程 cwd（父仓库）"


def test_relative_dot_resolves_to_workspace_root_not_process_cwd():
    from llm_loop.core.run_context import current_workspace_root

    with tempfile.TemporaryDirectory() as ws:
        root = Path(ws).resolve()
        (root / "pkg").mkdir()
        tok = current_workspace_root.set(str(root))
        try:
            r = _tool().execute(command="pwd", workdir=".")
        finally:
            current_workspace_root.reset(tok)
        assert r.status.name == "SUCCESS", f"content={r.content}"
        out = r.content.strip().splitlines()[-1]
        assert Path(out) == root, f"'.' 应解析到工作区根 {root}, 实际 {out}"
        assert Path(out) != Path(os.getcwd()), "不应落到进程 cwd（父仓库）"


def test_relative_subdir_resolves_against_workspace_root():
    from llm_loop.core.run_context import current_workspace_root

    with tempfile.TemporaryDirectory() as ws:
        root = Path(ws).resolve()
        (root / "pkg").mkdir()
        tok = current_workspace_root.set(str(root))
        try:
            r = _tool().execute(command="pwd", workdir="pkg")
        finally:
            current_workspace_root.reset(tok)
        assert r.status.name == "SUCCESS", f"content={r.content}"
        assert Path(r.content.strip().splitlines()[-1]) == root / "pkg"


def test_explicit_workdir_is_echoed_as_absolute_cwd():
    """显式 workdir → 回执回显解析后的绝对 cwd（越界可被即时发现）."""
    with tempfile.TemporaryDirectory() as d:
        r = _tool().execute(command="pwd", workdir=d)
        assert r.status.name == "SUCCESS"
        assert f"[cwd {Path(d).resolve()}]" in r.content


def test_default_workdir_emits_no_cwd_line():
    """未指定 workdir → 不回显 cwd 行（默认路径零噪音）."""
    r = _tool().execute(command="pwd")
    assert r.status.name == "SUCCESS"
    assert "[cwd " not in r.content
