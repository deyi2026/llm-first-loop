"""execute_command 环境清洗测试（EVO-20260814-61a52baf）.

覆盖: 密钥剔除 / 白名单保留 / 非敏感键保留 / 正常命令行为不变.
"""

from __future__ import annotations

import os
from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool, _workspace_python_env
from llm_loop.tools.registry import ToolRegistry


def _run(command: str):
    reg = ToolRegistry()
    reg.register(ExecuteCommandTool())
    return reg.execute(ToolCall(id="c1", name="execute_command", arguments={"command": command}))


def _probe(expr: str) -> str:
    """在子进程内求值 expr，返回 'True/False' 序列."""
    r = _run(f'python3 -c "import os; print({expr})"')
    assert r.status == ToolResultStatus.SUCCESS, r.content
    # execute_command 现在会前置 [命令]/退出码/输出行数元信息；安全断言只取
    # 子进程实际 stdout 最后一行，不能因为可观测性前缀把已生效的环境净化误判失败。
    return r.content.strip().splitlines()[-1]


def _set_env(key: str, value: str):
    """设置测试环境变量并返回恢复函数（避免污染全局环境）."""
    old = os.environ.get(key)
    os.environ[key] = value

    def restore():
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old

    return restore


def test_secret_env_vars_scrubbed():
    """密钥类环境变量（含 API_KEY/SECRET/TOKEN）不出现在子进程环境."""
    restores = [
        _set_env("LLM_API_KEY", "sk-secret-123"),
        _set_env("DEEPSEEK_API_KEY", "sk-ds-456"),
        _set_env("FEISHU_APP_SECRET", "fs-secret"),
        _set_env("ACCESS_TOKEN_XYZ", "tok-abc"),
    ]
    try:
        probe = _probe(
            "'LLM_API_KEY' in os.environ, 'DEEPSEEK_API_KEY' in os.environ, "
            "'FEISHU_APP_SECRET' in os.environ, 'ACCESS_TOKEN_XYZ' in os.environ"
        )
        assert probe == "False False False False", f"密钥泄露: {probe}"
    finally:
        for r in restores:
            r()


def test_whitelist_env_preserved():
    """白名单基础键（PATH 等）在子进程可见."""
    probe = _probe("'PATH' in os.environ")
    assert probe == "True"


def test_nonsecret_env_preserved():
    """非敏感配置键保留（不破坏 git/ssh/代理等正常功能，零回归）."""
    restores = [
        _set_env("LLM_MODEL", "deepseek-v4-flash"),
        _set_env("LLM_BASE_URL", "https://api.example.com/v1"),
    ]
    try:
        probe = _probe("'LLM_MODEL' in os.environ, 'LLM_BASE_URL' in os.environ")
        assert probe == "True True"
    finally:
        for r in restores:
            r()


def test_normal_command_behavior_unchanged():
    """非零退出码仍如实上报（行为零回归）."""
    r = _run("exit 3")
    assert r.status == ToolResultStatus.FAILURE
    assert "3" in r.content


def test_control_plane_env_scrubbed():
    """review R3 P0-1: COG_RUNTIME_ENFORCE_FILE（控制面 capability metadata）不进子进程环境.

    非 secret 但暴露路径即暴露 self-promote 攻击面（同 Unix 用户可写目录）。
    """
    restore = _set_env("COG_RUNTIME_ENFORCE_FILE", "/opt/lfl-test/allowlist")
    try:
        probe = _probe("'COG_RUNTIME_ENFORCE_FILE' in os.environ")
        assert probe == "False", f"控制面路径泄露: {probe}"
    finally:
        restore()


def _make_lfl_tree(root: Path, *, with_venv: bool) -> None:
    (root / "src" / "llm_loop").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "llm-first-loop"\n', encoding="utf-8")
    if with_venv:
        python = root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\n", encoding="utf-8")
        python.chmod(0o755)


def test_lfl_workdir_pins_bare_python_to_project_venv(tmp_path):
    """普通 checkout 内 bare python/python3/pytest 应优先使用项目 venv。"""
    root = tmp_path / "repo"
    _make_lfl_tree(root, with_venv=True)
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "/old/src"}

    pinned = _workspace_python_env(env, str(root / "src"), "python3 -m pytest")

    assert pinned["PATH"].split(os.pathsep)[0] == str(root / ".venv" / "bin")
    assert pinned["PYTHONPATH"].split(os.pathsep)[0] == str(root / "src")
    assert env == {"PATH": "/usr/bin:/bin", "PYTHONPATH": "/old/src"}


def test_linked_worktree_reuses_main_venv_but_runs_worktree_src(tmp_path):
    """linked worktree 无 .venv 时复用主树 venv，但代码身份仍绑定当前 worktree。"""
    main = tmp_path / "repo"
    worktree = main / ".worktrees" / "candidate"
    _make_lfl_tree(main, with_venv=True)
    _make_lfl_tree(worktree, with_venv=False)
    nested = worktree / "tests"
    nested.mkdir()

    pinned = _workspace_python_env({"PATH": "/usr/bin"}, str(nested), "pytest -q")

    assert pinned["PATH"].split(os.pathsep)[0] == str(main / ".venv" / "bin")
    assert pinned["PYTHONPATH"].split(os.pathsep)[0] == str(worktree / "src")


def test_non_lfl_workdir_keeps_host_python_environment(tmp_path):
    """别的项目/临时目录不能被 LFL 的 venv 规则污染。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    env = {"PATH": "/usr/local/bin:/usr/bin", "PYTHONPATH": "/custom"}

    assert _workspace_python_env(env, str(plain), "python3 -c pass") == env


def test_lfl_workdir_does_not_pin_after_shell_cd_or_explicit_python_path(tmp_path):
    """显式跨目录/绝对解释器属于调用者选择，不能被 LFL venv 环境重写。"""
    root = tmp_path / "repo"
    _make_lfl_tree(root, with_venv=True)
    env = {"PATH": "/usr/bin", "PYTHONPATH": "/custom"}

    assert _workspace_python_env(env, str(root), "cd /tmp && python3 -c pass") == env
    assert _workspace_python_env(env, str(root), "/usr/bin/python3 -c pass") == env
