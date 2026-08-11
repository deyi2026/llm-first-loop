"""EXEC_MODE 命令分级测试（EVO-20260810-2549e9b6）.

blocked 全禁 / readonly 只读放行+写拦截 / allowlist 前缀白名单 / 非法回退 blocked / 默认空不启用（零回归）。
直接装配 ToolRegistry + ExecuteCommandTool，零真实 LLM、零真实飞书 API。
"""

from llm_loop.config import _env_exec_mode
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolRegistry


def _reg(exec_mode: str = "", allowlist: str = ""):
    reg = ToolRegistry(exec_mode=exec_mode, exec_allowlist=allowlist)
    reg.register(ExecuteCommandTool())
    return reg


def _exec(reg, command: str):
    return reg.execute(ToolCall(id="c1", name="execute_command", arguments={"command": command}))


def test_exec_blocked_mode():
    """blocked: 任意命令返回 BLOCKED + 需人工执行."""
    reg = _reg(exec_mode="blocked")
    for cmd in ("ls", "echo hi", "cat file.txt"):
        result = _exec(reg, cmd)
        assert result.status == ToolResultStatus.BLOCKED
        assert "[权限拦截]" in result.content
        assert "需人工执行" in result.content


def test_exec_readonly_allow():
    """readonly: 只读命令放行（真实执行成功，零写副作用）."""
    reg = _reg(exec_mode="readonly")
    result = _exec(reg, "echo hi")
    assert result.status == ToolResultStatus.SUCCESS
    assert "hi" in result.content


def test_exec_readonly_block_write():
    """readonly: 含写标记/写类命令拦截."""
    reg = _reg(exec_mode="readonly")
    for cmd in ("echo x > f.txt", "rm -f f.txt", "pip install requests"):
        result = _exec(reg, cmd)
        assert result.status == ToolResultStatus.BLOCKED
        assert "readonly" in result.content


def test_exec_allowlist():
    """allowlist: 命中前缀放行、未命中拦截."""
    reg = _reg(exec_mode="allowlist", allowlist="ls,cat")
    ok = _exec(reg, "ls -la")
    assert ok.status == ToolResultStatus.SUCCESS
    blocked = _exec(reg, "rm -f f.txt")
    assert blocked.status == ToolResultStatus.BLOCKED
    assert "白名单" in blocked.content


def test_invalid_mode_fallback(monkeypatch):
    """非法 EXEC_MODE → 回退 blocked（安全优先）；未设置 → 空（不启用分级）；大小写归一."""
    monkeypatch.setenv("EXEC_MODE", "weird")
    assert _env_exec_mode("EXEC_MODE") == "blocked"
    monkeypatch.setenv("EXEC_MODE", "READONLY")
    assert _env_exec_mode("EXEC_MODE") == "readonly"
    monkeypatch.delenv("EXEC_MODE", raising=False)
    assert _env_exec_mode("EXEC_MODE") == ""  # 未设置 = 不启用分级（AI 可执行 shell）


def test_exec_mode_default_disabled():
    """默认（未装配 exec_mode）→ 不拦截（既有直接构造 ToolRegistry 零回归）."""
    reg = _reg()  # exec_mode=""
    result = _exec(reg, "echo hi")
    assert result.status == ToolResultStatus.SUCCESS
