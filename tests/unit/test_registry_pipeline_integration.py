"""主链路接入测试（EVO-20260813-9ced1f4c P3 接入 registry.execute）.

验证:
1. 默认无 pipeline → 行为完全不变（零回归）
2. 装配 pipeline(materialize) → 参数物化替换防篡改
3. 装配 pipeline(guard) → 守卫拒绝返回 BLOCKED
4. post 钩子快照触发
"""

from __future__ import annotations

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.pipeline import (
    GuardViolation,
    MonotonicGuard,
    PipelineConfig,
    ToolExecutionPipeline,
)
from llm_loop.tools.registry import ToolRegistry


class _FakeTool:
    """最小工具协议（execute 接受 kwargs，返回字符串）."""

    name = "fake_tool"
    description = "fake"
    parameters = {"type": "object", "properties": {}}

    def __init__(self):
        self.seen_args = None

    def execute(self, **kwargs):
        self.seen_args = kwargs
        return f"ok:{kwargs}"


def _make_registry(pipeline=None):
    reg = ToolRegistry()
    reg._tools["fake_tool"] = _FakeTool()
    if pipeline is not None:
        reg.set_pipeline(pipeline)
    return reg


def _call(name="fake_tool", args=None):
    return ToolCall(id="t1", name=name, arguments=args or {})


# ── 1. 默认零回归 ────────────────────────────────────────────────
def test_default_no_pipeline_zero_regression():
    reg = _make_registry()  # 无 pipeline
    r = reg.execute(_call(args={"x": 1}))
    assert r.status == ToolResultStatus.SUCCESS
    assert "ok:" in r.content


def test_pipeline_disabled_zero_regression():
    # 装配但 enabled=False → 行为与无 pipeline 一致
    p = ToolExecutionPipeline(PipelineConfig(enabled=False, materialize=True, guard=True))
    reg = _make_registry(p)
    r = reg.execute(_call(args={"x": 1}))
    assert r.status == ToolResultStatus.SUCCESS


# ── 2. 物化边界 ──────────────────────────────────────────────────
def test_materialize_replaces_args():
    tool = _FakeTool()
    reg = _make_registry(ToolExecutionPipeline(PipelineConfig(enabled=True, materialize=True)))
    reg._tools["fake_tool"] = tool
    r = reg.execute(_call(args={"path": "a/b", "nested": {"k": [1, 2]}}))
    assert r.status == ToolResultStatus.SUCCESS
    # 执行收到的是物化副本（内容一致，独立性由 pipeline 单测覆盖）
    assert tool.seen_args == {"path": "a/b", "nested": {"k": [1, 2]}}


def test_materialize_rejects_bad_args_returns_failure():
    reg = _make_registry(ToolExecutionPipeline(PipelineConfig(enabled=True, materialize=True)))
    r = reg.execute(_call(args={"bad": object()}))
    assert r.status == ToolResultStatus.FAILURE
    assert "参数拒绝" in r.content


# ── 3. 单调守卫 ──────────────────────────────────────────────────
def test_guard_blocks_returns_blocked():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True, guard=True))
    g = MonotonicGuard()
    g.add_deny("fake_tool", "测试拒绝")
    p.set_guard(g)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.BLOCKED
    assert "单调守卫" in r.content


def test_guard_allows_non_denied():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True, guard=True))
    g = MonotonicGuard()
    g.add_deny("other_tool", "拒绝别的")
    p.set_guard(g)
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.SUCCESS


# ── 4. post 钩子快照 ─────────────────────────────────────────────
def test_post_hook_snapshot_fires():
    p = ToolExecutionPipeline(PipelineConfig(enabled=True))
    snapshots = []
    p.add_post_hook(lambda snap: snapshots.append(snap))
    reg = _make_registry(p)
    r = reg.execute(_call())
    assert r.status == ToolResultStatus.SUCCESS
    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "fake_tool"
    assert snapshots[0].status == "success"
