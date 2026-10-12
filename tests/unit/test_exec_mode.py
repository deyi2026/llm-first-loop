"""EXEC_MODE 命令分级测试（EVO-20260810-2549e9b6）.

blocked 全禁 / readonly 只读放行+写拦截 / allowlist 前缀白名单 / 非法回退 blocked / 默认空不启用（零回归）。
直接装配 ToolRegistry + ExecuteCommandTool，零真实 LLM、零真实飞书 API。
"""

from llm_loop.config import _env_exec_mode
from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
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


# ── EVO-20260814: fail-closed 覆盖所有破坏性工具（修写文件工具绕过分级）──

class _MockWriteTool:
    """模拟写文件类工具（name 在破坏性集合，execute 恒 SUCCESS，不碰真实文件）."""

    name = "write_file"
    description = "mock 写工具"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, **kwargs) -> "ToolResult":

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="[mock] 写文件成功",
            tool_call_id="",
            tool_name=self.name,
        )


def _make_mock_write(name: str):
    """按工具名生成 mock 写工具（execute 恒 SUCCESS；type() 动态类绕开类体不闭包）."""

    def execute(self, **kwargs) -> "ToolResult":

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[mock] {self.name} 成功",
            tool_call_id="",
            tool_name=self.name,
        )

    cls = type(
        name,
        (),
        {
            "name": name,
            "description": f"mock {name}",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "execute": execute,
        },
    )
    return cls()


def _reg2(exec_mode: str = "", allowlist: str = ""):
    """装配含全部破坏性 mock 工具（write/delete/append/edit）的 Registry."""
    reg = ToolRegistry(exec_mode=exec_mode, exec_allowlist=allowlist)
    for n in ("write_file", "delete_file", "append_file", "edit_file"):
        reg.register(_make_mock_write(n))
    return reg


def _write(reg, name: str = "write_file"):
    return reg.execute(ToolCall(id="c2", name=name, arguments={"path": "/tmp/x.txt"}))


def test_exec_readonly_blocks_write_tool():
    """readonly: 写文件类工具被拦截（fail-closed 覆盖，修此前绕过缺口）."""
    reg = _reg2(exec_mode="readonly")
    result = _write(reg)
    assert result.status == ToolResultStatus.BLOCKED
    assert "readonly" in result.content
    assert "write_file" in result.content


def test_exec_blocked_blocks_write_tool():
    """blocked: 写文件类工具被拦截（此前绕过分级可任意写文件）."""
    reg = _reg2(exec_mode="blocked")
    result = _write(reg)
    assert result.status == ToolResultStatus.BLOCKED
    assert "blocked" in result.content


def test_exec_allowlist_tool_name():
    """allowlist: 工具名在白名单放行、不在拦截."""
    reg = _reg2(exec_mode="allowlist", allowlist="write_file")
    ok = _write(reg)
    assert ok.status == ToolResultStatus.SUCCESS  # write_file 在白名单 → 放行
    reg2 = _reg2(exec_mode="allowlist", allowlist="ls")
    blocked = _write(reg2)
    assert blocked.status == ToolResultStatus.BLOCKED
    assert "白名单" in blocked.content


def test_exec_mode_default_allows_write_tool():
    """默认（未启用分级）: 写文件类工具放行（零回归）."""
    reg = _reg2()
    result = _write(reg)
    assert result.status == ToolResultStatus.SUCCESS


def test_exec_readonly_blocks_all_destructive_tools():
    """readonly: 全部破坏性工具名集合均被拦截（write/delete/append/edit）."""
    reg = _reg2(exec_mode="readonly")
    for name in ("write_file", "delete_file", "append_file", "edit_file"):
        result = _write(reg, name=name)
        assert result.status == ToolResultStatus.BLOCKED, f"{name} 应被 readonly 拦截"
        assert "readonly" in result.content
