"""EVO-20260914-1eb26afa: 执行面能力矩阵 + spawn/step 启动前早失败校验.

回归防线:
- 显式声明缺口 → child/workflow 启动前零成本拒绝（含替代执行面提示）
- 不声明 requires → 行为与既有完全一致（零回归）
- codearts 远端定义面: 不可枚举如实提示（不臆断），session_continuity 缺口可拒绝
"""
from __future__ import annotations

import pytest

from llm_loop.core.execution_surface import (
    SurfaceRequirements,
    alternatives_hint,
    codearts_capability,
    local_subagent_capability,
    validate_requirements,
)


class _FakeRegistry:
    def names(self):
        return iter(["read_file", "edit_file", "execute_command", "web_search"])


class _FakeRunner:
    registry = _FakeRegistry()


def _spawn_tool():
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
    return SpawnSubAgentTool(_FakeRunner())


def _workflow_tool():
    from llm_loop.tools.builtin.workflow import WorkflowRunTool
    return WorkflowRunTool(_FakeRunner())


# ── 矩阵派生 ──

def test_local_capability_derived_from_live_registry():
    caps = local_subagent_capability(["read_file", "web_search"])
    assert caps.tool_enumeration == "registry"
    assert caps.allowed_tools == ("read_file", "web_search")
    assert caps.network_egress is True
    assert caps.filesystem_scope == "workspace"
    assert caps.session_continuity is True


def test_local_capability_without_egress_tools():
    caps = local_subagent_capability(["read_file"])
    assert caps.network_egress is False
    assert validate_requirements(
        caps, SurfaceRequirements(network=True)
    ) == ["required network egress: 执行面 local_subagent 无出站网络工具"]


def test_codearts_capability_is_remote_defined_honestly():
    ca = codearts_capability()
    assert ca.allowed_tools is None and ca.tool_enumeration == "remote_defined"
    assert ca.session_continuity is False and ca.filesystem_scope == "remote_sandbox"
    gaps = validate_requirements(ca, SurfaceRequirements(tools=("read_file",), session_continuity=True))
    assert any("远端定义" in g for g in gaps)      # 不可枚举：如实提示，不臆断拒绝
    assert any("session" in g for g in gaps)       # 可断言维度照常拒绝


# ── requires 解析 ──

def test_requirements_parsing_and_invalid():
    assert SurfaceRequirements.from_kwargs(None) is None
    assert SurfaceRequirements.from_kwargs("web_search") is None       # 非对象 → None
    assert SurfaceRequirements.from_kwargs({"tools": "a, b"}).tools == ("a", "b")
    assert SurfaceRequirements.from_kwargs({"tools": ["x"], "network": True}).network is True
    assert SurfaceRequirements.from_kwargs({}).declared() is False     # 空声明不触发比对


def test_alternatives_hint_lists_satisfying_surfaces():
    reqs = SurfaceRequirements(network=True)
    caps_local = local_subagent_capability(["read_file"])              # 无网络
    hint = alternatives_hint(reqs, {"local_subagent": caps_local, "codearts": codearts_capability()})
    assert "codearts" in hint and "local_subagent" not in hint


# ── spawn_subagent 早失败 / 零回归 ──

def test_spawn_rejects_declared_tool_gap_before_start():
    r = _spawn_tool().execute(task="浏览器渲染", requires={"tools": ["playwright_exec"]})
    assert r.status.value == "failure"
    assert "child 未启动" in r.content and "playwright_exec" in r.content


def test_spawn_rejects_invalid_requires_type():
    r = _spawn_tool().execute(task="x", requires="web_search")
    assert r.status.value == "failure" and "参数错误" in r.content


def test_spawn_satisfied_requirements_not_blocked():
    # 声明可满足 → 不被矩阵拦截（FakeRunner.start 缺失走既有 error 路径，而非矩阵拒绝）
    r = _spawn_tool().execute(task="x", requires={"tools": ["read_file"], "network": True, "fs": True})
    assert "缺口" not in r.content


def test_spawn_without_requires_zero_regression():
    r = _spawn_tool().execute(task="x")
    assert "requires" not in r.content and "缺口" not in r.content


# ── workflow 步骤级早失败 ──

def test_workflow_rejects_any_step_gap_before_start():
    r = _workflow_tool().execute(mode="parallel", steps=[
        {"task": "本地读文件", "requires": {"tools": ["read_file"]}},
        {"task": "远端渲染", "executor": "codearts", "requires": {"session_continuity": True}},
    ])
    assert r.status.value == "failure"
    assert "steps[1]" in r.content and "工作流未启动" in r.content
    assert "local_subagent" in r.content            # 替代执行面提示


def test_workflow_without_requires_zero_regression():
    r = _workflow_tool().execute(mode="parallel", steps=[{"task": "x"}])
    assert "矩阵" not in r.content and "缺口" not in r.content
