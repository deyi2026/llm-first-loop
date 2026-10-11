"""E4/E5 演进专项测试（EVO-20261012-bb3022f4 / EVO-20261012-65475c5a）.

E4: spawn requires.tools 声明即程序级强制白名单（child 发现面+执行面截断；
    声明超父 scope 拒绝；spawn_subagent 默认剔除，CHILD_SPAWN_GRANT 授予例外）。
E5: wait 只读墙钟等待原语（参数校验/累计预算/取消唤醒 ≤0.5s）。
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from llm_loop.core import run_context as rc
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.wait import (
    MAX_SINGLE_WAIT_S,
    MAX_TOTAL_WAIT_S,
    WaitTool,
)


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
            rc.child_wait_budget_used.set(0.0),
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
        assert 0.9 <= rc.child_wait_budget_used.get() <= 5.0

    def test_total_budget_enforced(self):
        rc.child_wait_budget_used.set(MAX_TOTAL_WAIT_S - 5)
        result = WaitTool().execute(seconds=10)
        assert result.status.value == "blocked"
        assert "预算不足" in result.content

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
