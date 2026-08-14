"""execute_command 环境清洗测试（EVO-20260814-61a52baf）.

覆盖: 密钥剔除 / 白名单保留 / 非敏感键保留 / 正常命令行为不变.
"""

from __future__ import annotations

import os

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolRegistry


def _run(command: str):
    reg = ToolRegistry()
    reg.register(ExecuteCommandTool())
    return reg.execute(ToolCall(id="c1", name="execute_command", arguments={"command": command}))


def _probe(expr: str) -> str:
    """在子进程内求值 expr，返回 'True/False' 序列."""
    r = _run(f'python3 -c "import os; print({expr})"')
    assert r.status == ToolResultStatus.SUCCESS, r.content
    return r.content.strip()


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
