"""工具执行瀑布升级单测（EVO-20260813-9ced1f4c P0-P4）.

覆盖: 深冻结不可变 / 单调守卫 fail-closed / 物化拒绝非法 / 管线执行顺序.
"""

from __future__ import annotations

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.tools.pipeline import (
    GuardViolationError,
    ImmutableResult,
    MaterializationError,
    MonotonicGuard,
    PermissionEntry,
    PipelineConfig,
    ToolExecutionPipeline,
    deep_freeze,
    materialize_and_freeze,
    materialize_lossless_json,
)


# ── 1. 深冻结不可变 ──────────────────────────────────────────────
def test_deep_freeze_dict_immutable():
    frozen = deep_freeze({"a": {"b": [1, 2]}, "c": "x"})
    with pytest.raises(TypeError):
        frozen["a"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["a"]["b"] = []  # type: ignore[index]


def test_materialize_lossless_roundtrip():
    args = {"path": "a/b", "n": 1, "list": [1, 2, 3], "nested": {"k": "v"}}
    out = materialize_lossless_json(args)
    assert out == args
    # 独立性：修改副本不影响原参数
    out["path"] = "changed"
    assert args["path"] == "a/b"


def test_materialize_rejects_unserializable():
    with pytest.raises(MaterializationError):
        materialize_lossless_json({"bad": object()})
    with pytest.raises(MaterializationError):
        materialize_and_freeze({"bad": lambda: 1})


# ── 2. 单调守卫 fail-closed ─────────────────────────────────────
def test_guard_add_deny_blocks():
    g = MonotonicGuard()
    g.add_deny("execute_command", "测试收紧")
    assert g.check("execute_command") == "测试收紧"
    assert not g.is_allowed("execute_command")


def test_guard_add_allow_on_denied_raises():
    g = MonotonicGuard()
    g.add_deny("rm_tool")
    with pytest.raises(GuardViolationError):
        g.add_allow("rm_tool")  # 对已 deny 的加 allow = 放松 → 拒绝


def test_guard_kernel_auto_injected():
    """内核最小安全集合自动注入为基线 deny（fail-closed 保障）."""
    kernel = {PermissionEntry(tool="execute_command", action="deny", reason="内核")}
    g = MonotonicGuard(kernel_minimal=kernel)
    assert g.check("execute_command") == "内核"  # 无需手动 add，构造即注入


def test_guard_kernel_cannot_be_relaxed():
    """内核 deny 不可被 allow 放松（fail-closed 核心）."""
    kernel = {PermissionEntry(tool="execute_command", action="deny", reason="内核")}
    g = MonotonicGuard(kernel_minimal=kernel)
    with pytest.raises(GuardViolationError):
        g.add_allow("execute_command")  # 对内核 deny 加 allow = 放松 → 拒绝
    assert g.check("execute_command") == "内核"  # 仍被拒


# ── 3. 管线执行顺序 + 不可变 result ─────────────────────────────
def _fake_tool(call: ToolCall) -> ImmutableResult:
    return ImmutableResult(tool_name=call.name, status="success", content="ok")


def test_pipeline_executes_pre_hooks_in_order():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))
    order: list[str] = []
    p.add_pre_hook(lambda c: order.append("pre1"))
    p.add_pre_hook(lambda c: order.append("pre2"))
    p.execute(_fake_tool, ToolCall(id="1", name="t", arguments={}), invoke=lambda t, c: _fake_tool(c))
    assert order == ["pre1", "pre2"]


def test_pipeline_materialize_frozen():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True, materialize=True))
    seen: dict = {}
    def invoke(tool, call):
        seen["args"] = call.arguments
        return _fake_tool(call)

    p.execute(_fake_tool, ToolCall(id="1", name="t", arguments={"x": [1, 2]}), invoke=invoke)
    assert seen["args"] == {"x": [1, 2]}  # 物化副本与原始一致


def test_pipeline_guard_blocks():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True, guard=True))
    g = MonotonicGuard()
    g.add_deny("execute_command", "测试拒绝")
    p.set_guard(g)
    with pytest.raises(GuardViolationError):
        p.execute(
            _fake_tool,
            ToolCall(id="1", name="execute_command", arguments={}),
            invoke=lambda t, c: _fake_tool(c),
        )


def test_pipeline_materialize_rejects_bad_args():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True, materialize=True))
    with pytest.raises(MaterializationError):
        p.execute(
            _fake_tool,
            ToolCall(id="1", name="t", arguments={"bad": object()}),
            invoke=lambda t, c: _fake_tool(c),
        )


def test_pipeline_result_immutable_snapshot():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))
    result = p.execute(
        _fake_tool, ToolCall(id="1", name="t", arguments={}),
        invoke=lambda t, c: _fake_tool(c),
    )
    assert isinstance(result, ImmutableResult)
    assert result.status == "success"
    assert result.tool_name == "t"
