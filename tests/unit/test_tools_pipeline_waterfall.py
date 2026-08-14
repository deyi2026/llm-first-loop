"""post hook waterfall 测试（EVO-20260814-39a10097: accept/block/replace 结果门禁）.

覆盖: 观察者零回归 / replace 结果替换 / block 短路失败 / hook 异常 fail-open / 链式顺序.
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.pipeline import (
    BlockResultError,
    ImmutableResult,
    PipelineConfig,
    ToolExecutionPipeline,
)
from llm_loop.tools.registry import ToolRegistry


class _FakeTool:
    name = "fake_tool"
    description = "fake"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return "ok"


def _make_registry(pipeline=None):
    reg = ToolRegistry()
    reg._tools["fake_tool"] = _FakeTool()
    if pipeline is not None:
        reg.set_pipeline(pipeline)
    return reg


def _call(name="fake_tool", args=None):
    return ToolCall(id="t1", name=name, arguments=args or {})


def test_post_hook_observer_zero_regression():
    """返回 None 的 hook = 观察者，结果不变（零回归）."""
    seen = []
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))
    p.add_post_hook(lambda snap: (seen.append(snap.content), None)[1])
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.SUCCESS
    assert "ok" in r.content
    assert seen  # hook 被调用（观察）


def test_post_hook_replace_rewrites_result():
    """hook 返回新 ImmutableResult → replace 回写 content."""
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))

    def replacer(snap: ImmutableResult) -> ImmutableResult:
        return ImmutableResult(
            tool_name=snap.tool_name,
            status="failure",
            content="replaced-by-hook",
            duration_ms=snap.duration_ms,
        )

    p.add_post_hook(replacer)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.content == "replaced-by-hook"
    assert r.status == ToolResultStatus.FAILURE  # status 随 replace 回写


def test_post_hook_block_short_circuits():
    """hook 抛 BlockResultError → block，结果 BLOCKED + 门禁原因."""
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))

    def blocker(snap):
        raise BlockResultError("输出含疑似密钥 sk-xxx")

    p.add_post_hook(blocker)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.BLOCKED
    assert "sk-xxx" in r.content


def test_post_hook_block_stops_later_hooks():
    """block 短路：后续 hook 不再执行."""
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))
    later = []

    def blocker(snap):
        raise BlockResultError("拒绝")

    def later_hook(snap):
        later.append("ran")

    p.add_post_hook(blocker)
    p.add_post_hook(later_hook)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.BLOCKED
    assert later == []  # 短路，未执行


def test_post_hook_exception_fail_open():
    """hook 抛普通异常 → fail-open，结果不变（防御模式 #5）."""
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))

    def bad(snap):
        raise RuntimeError("hook 内部炸了")

    p.add_post_hook(bad)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.SUCCESS  # 主流程不受影响
    assert "ok" in r.content


def test_post_hooks_chain_in_order():
    """多个 replace hook 依序链式传递."""
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))
    order = []

    def h1(snap):
        order.append("h1")
        return ImmutableResult(tool_name=snap.tool_name, status=snap.status,
                               content="stage1", duration_ms=snap.duration_ms)

    def h2(snap):
        order.append("h2")
        return ImmutableResult(tool_name=snap.tool_name, status=snap.status,
                               content=snap.content + "+stage2", duration_ms=snap.duration_ms)

    p.add_post_hook(h1)
    p.add_post_hook(h2)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert order == ["h1", "h2"]
    assert r.content == "stage1+stage2"
