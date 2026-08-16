"""路径 A 与 ToolRegistry 集成测试（预检拦截/放行/缺省零回归/安全检查仍生效）."""

from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.task_quality.precheck import PreCheckLayer
from llm_loop.tools.registry import ToolRegistry


class _DummyTool:
    name = "dummy"
    description = "测试工具"
    parameters = {
        "type": "object",
        "properties": {"count": {"type": "integer"}, "name": {"type": "string"}},
        "required": ["name"],
    }

    def execute(self, **kwargs):
        from llm_loop.core.message import ToolResult, ToolResultStatus
        return ToolResult(status=ToolResultStatus.SUCCESS, content="ok",
                          tool_call_id="", tool_name=self.name)


def _make_registry(precheck=None):
    reg = ToolRegistry(precheck_layer=precheck)
    reg.register(_DummyTool())
    return reg


def _call(tool_name="dummy", **args):
    return ToolCall(id="t1", name=tool_name, arguments=args)


def test_precheck_intercepts_invalid():
    """预检失败: 拦截不执行，返回字段级引导反馈."""
    reg = _make_registry(PreCheckLayer())
    r = reg.execute(_call(count="abc", name="x"))
    assert r.status.value == "failure"
    assert "参数预检失败" in r.content
    assert "count" in r.content
    assert "expected integer, got str" in r.content


def test_precheck_valid_passes():
    """预检通过: 正常执行."""
    reg = _make_registry(PreCheckLayer())
    r = reg.execute(_call(count=3, name="x"))
    assert r.status.value == "success"
    assert "ok" in r.content


def test_precheck_missing_required():
    """必填缺失: 拦截."""
    reg = _make_registry(PreCheckLayer())
    r = reg.execute(_call(count=3))
    assert r.status.value == "failure"
    assert "required but missing" in r.content


def test_no_precheck_zero_regression():
    """缺省 None: 无预检，行为与既有一致（参数错误由工具容错/LLM 更正）."""
    reg = _make_registry()  # 无 precheck
    r = reg.execute(_call(count="abc", name="x"))
    assert r.status.value == "success"  # 工具自身容错执行
    assert "ok" in r.content


def test_precheck_does_not_bypass_safety():
    """预检不替代安全检查: 灾难性动作仍被拦截（blocked）."""
    # 用 EXEC_MODE=blocked 验证: 预检开启不绕过命令分级（安全检查仍生效）
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
    reg2 = ToolRegistry(precheck_layer=PreCheckLayer(), exec_mode="blocked")
    reg2.register(ExecuteCommandTool(timeout_s=5))
    r = reg2.execute(_call(tool_name="execute_command", command="echo hi"))
    assert r.status.value == "blocked"
