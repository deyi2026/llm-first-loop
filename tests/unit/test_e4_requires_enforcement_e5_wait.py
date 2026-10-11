"""E4/E5 演进专项测试（EVO-20261012-bb3022f4 / EVO-20261012-65475c5a）.

E4: spawn requires.tools 声明即程序级强制白名单（child 发现面+执行面截断；
    声明超父 scope 拒绝；spawn_subagent 默认剔除，CHILD_SPAWN_GRANT 授予例外）。
E5: wait 只读墙钟等待原语（参数校验/累计预算/取消唤醒 ≤0.5s）。
"""

from __future__ import annotations

import re
import threading
import time
from unittest import mock

import pytest

from llm_loop.core import run_context as rc
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.wait import (
    MAX_SINGLE_WAIT_S,
    MAX_TOTAL_WAIT_S,
    WaitTool,
)
from llm_loop.tools.registry import ToolRegistry


class _FakeRegistry:
    def names(self):
        return [
            "execute_command",
            "web_search",
            "web_fetch",
            "read_file",
            "spawn_subagent",
            "wait",
        ]


@pytest.fixture()
def bare_runner():
    r = SubAgentRunner.__new__(SubAgentRunner)
    r.registry = _FakeRegistry()
    return r


def _grant(runner, value: str):
    return mock.patch(
        "llm_loop.config.load_settings",
        **{"return_value.child_spawn_grant": value},
    )


class TestComputeChildToolScope:
    def setup_method(self):
        self._tokens = []

    def teardown_method(self):
        for t in reversed(self._tokens):
            rc.current_tool_discovery_scope.reset(t)

    def _set_scope(self, scope):
        self._tokens.append(rc.current_tool_discovery_scope.set(scope))

    def test_default_full_plane_excludes_spawn_subagent(self, bare_runner):
        with _grant(bare_runner, ""):
            self._set_scope(None)
            scope, refusal = bare_runner._compute_child_tool_scope(None)
        assert refusal == ""
        assert scope is not None
        assert "spawn_subagent" not in scope
        assert {"web_search", "execute_command", "wait"} <= scope

    def test_declared_tools_become_whitelist(self, bare_runner):
        with _grant(bare_runner, ""):
            self._set_scope(None)
            scope, refusal = bare_runner._compute_child_tool_scope(["web_search"])
        assert refusal == ""
        assert scope == frozenset({"web_search"})

    def test_declaration_beyond_parent_scope_refused(self, bare_runner):
        with _grant(bare_runner, ""):
            self._set_scope(frozenset({"web_search", "read_file"}))
            scope, refusal = bare_runner._compute_child_tool_scope(
                ["web_search", "execute_command"]
            )
        assert scope is None
        assert "超出父执行域" in refusal
        assert "execute_command" in refusal

    def test_parent_restricted_inherited_when_undeclared(self, bare_runner):
        with _grant(bare_runner, ""):
            self._set_scope(frozenset({"web_search", "read_file"}))
            scope, refusal = bare_runner._compute_child_tool_scope(None)
        assert refusal == ""
        assert scope == frozenset({"web_search", "read_file"})

    def test_declaring_spawn_subagent_stripped_without_grant(self, bare_runner):
        with _grant(bare_runner, ""):
            self._set_scope(None)
            scope, refusal = bare_runner._compute_child_tool_scope(
                ["web_search", "spawn_subagent"]
            )
        assert refusal == ""
        assert scope == frozenset({"web_search"})

    def test_grant_star_keeps_full_none_plane(self, bare_runner):
        with _grant(bare_runner, "*"):
            self._set_scope(None)
            scope, refusal = bare_runner._compute_child_tool_scope(None)
        assert refusal == ""
        assert scope is None

    def test_grant_mismatched_session_still_stripped(self, bare_runner):
        with _grant(bare_runner, "sess-123"):
            self._set_scope(None)
            scope, refusal = bare_runner._compute_child_tool_scope(None)
        assert refusal == ""
        assert "spawn_subagent" not in scope


class TestWaitTool:
    def setup_method(self):
        self._tokens = [
            rc.child_wait_budget_used.set(rc.WaitBudget()),
            rc.child_cancel_event.set(None),
        ]

    def teardown_method(self):
        rc.child_cancel_event.reset(self._tokens[1])
        rc.child_wait_budget_used.reset(self._tokens[0])

    def test_rejects_non_numeric(self):
        assert WaitTool().execute(seconds="abc").status.value == "failure"

    def test_rejects_out_of_range(self):
        assert WaitTool().execute(seconds=0.5).status.value == "failure"
        assert WaitTool().execute(seconds=MAX_SINGLE_WAIT_S + 1).status.value == "failure"

    def test_waits_requested_duration_and_tracks_budget(self):
        started = time.monotonic()
        result = WaitTool().execute(seconds=1)
        duration = time.monotonic() - started
        assert result.status.value == "success"
        assert duration >= 1.0
        assert 0.9 <= rc.child_wait_budget_used.get().used <= 5.0

    def test_total_budget_enforced(self):
        rc.child_wait_budget_used.set(rc.WaitBudget(MAX_TOTAL_WAIT_S - 5))
        result = WaitTool().execute(seconds=10)
        assert result.status.value == "blocked"
        assert "预算不足" in result.content

    def test_accumulation_persists_across_direct_calls(self):
        # 同一载体连续两次直调必须累计（载体原位累加语义锚点）
        WaitTool().execute(seconds=1)
        result = WaitTool().execute(seconds=1)
        assert result.status.value == "success"
        assert rc.child_wait_budget_used.get().used == 2.0

    def test_cancel_event_wakes_within_poll_interval(self):
        ev = threading.Event()
        rc.child_cancel_event.set(ev)
        threading.Timer(1.2, ev.set).start()
        started = time.monotonic()
        result = WaitTool().execute(seconds=60)
        duration = time.monotonic() - started
        assert result.status.value == "blocked"
        assert "cancelled" in result.content
        assert duration < 3.0  # 0.5s 轮询 + 1.2s 触发，远小于 60s


class TestWaitBudgetAcrossRegistryDispatch:
    """EVO-20261012-32e89b46 回归：经 registry.execute 真实派发路径验证累计持久.

    registry._run_with_timeout 每次工具派发 copy_context() 拍快照，工具在副本
    context 内执行。旧实现（ContextVar[float] 值语义）的 set() 写入副本即弃，
    该路径下每次调用累计归零——直调 execute() 的单测测不出，必须走派发边界
    （E5 live 失效的系统性盲区）。
    """

    def setup_method(self):
        self._tokens = [
            rc.child_wait_budget_used.set(rc.WaitBudget()),
            rc.child_cancel_event.set(None),
        ]

    def teardown_method(self):
        rc.child_cancel_event.reset(self._tokens[1])
        rc.child_wait_budget_used.reset(self._tokens[0])

    def test_accumulation_survives_dispatch_snapshot(self):
        reg = ToolRegistry()
        reg._tools["wait"] = WaitTool()
        r1 = reg.execute(ToolCall(id="w1", name="wait", arguments={"seconds": 1}))
        r2 = reg.execute(ToolCall(id="w2", name="wait", arguments={"seconds": 1}))
        assert r1.status == ToolResultStatus.SUCCESS
        assert r2.status == ToolResultStatus.SUCCESS
        # 回执累计必须跨调用递增（1s → 2s），而非每次从 0 起算
        assert "本会话累计 1s" in r1.content
        assert "本会话累计 2s" in r2.content
        assert rc.child_wait_budget_used.get().used == 2.0

    def test_budget_enforced_through_dispatch_after_prior_waits(self):
        # 已累计 597s（载体经前序调用累加）后，再请求 10s 应经真实派发路径拒绝
        carrier = rc.child_wait_budget_used.get()
        carrier.used = MAX_TOTAL_WAIT_S - 3
        reg = ToolRegistry()
        reg._tools["wait"] = WaitTool()
        r = reg.execute(ToolCall(id="w3", name="wait", arguments={"seconds": 10}))
        assert r.status == ToolResultStatus.BLOCKED
        assert "预算不足" in r.content
        assert re.search(r"已用 \d+s / 600s", r.content)
