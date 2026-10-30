"""write_scope 声明传递链测试（DESIGN-20261030 §5.3 C2/C3/C5/C5b；T2/T3/T15/T16）.

覆盖两条子代理启动路径（异步 start() 与同步 run()，设计文档 F14）：
- 未声明 write_scope → 继承父 scope；既有 spawn 调用面/回执零变化（FR-3）
- 非法 write_scope 结构 → spawn 参数错误，不静默忽略（FR-1/T1）
- 子声明超出父 scope → refused + detail 含越界项 + 未启动任何 child（FR-2/T2）
- 父全量 + 子有约束 → 以子为准（§5.1）
- 同步 run() 路径同样注入/拒绝（T15）；拒绝后 ContextVar 无泄漏（T16）

写侧强制点（edit_file/FileService 的 C6/C7）不在本文件范围。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest import mock

import pytest

from llm_loop.core.run_context import current_write_scope
from llm_loop.core.write_scope import WriteScope, parse_write_scope
from llm_loop.subagent.runner import SubAgentResult, SubAgentRunner
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool


class _FakeRegistry:
    def names(self):
        return [
            "read_file",
            "edit_file",
            "execute_command",
            "web_search",
            "wait",
            "spawn_subagent",
        ]


def _no_grant():
    """CHILD_SPAWN_GRANT 未授予（child 面剔除 spawn_subagent 的默认面）."""
    return mock.patch(
        "llm_loop.config.load_settings",
        **{"return_value.child_spawn_grant": ""},
    )


class RecordingRunner:
    """工具层测试：记录 start() 派生调用；不启动任何真实 child/线程."""

    def __init__(self, reply: dict | None = None) -> None:
        self.registry = SimpleNamespace(
            names=lambda: ["read_file", "execute_command", "wait"]
        )
        self.calls: list[dict] = []
        self._reply = dict(reply or {})

    def start(self, **kwargs):
        self.calls.append(kwargs)
        merged = {
            "accepted": True,
            "child_id": "child-test-0001",
            "state": "running",
            "depth": kwargs.get("depth", 0),
            "model": "",
        }
        merged.update(self._reply)
        return merged


@pytest.fixture()
def ws_tokens():
    """父 write scope token 登记：测试退出统一恢复，杜绝父值污染其它用例."""
    tokens: list = []
    yield tokens
    for t in reversed(tokens):
        current_write_scope.reset(t)


def _set_parent_scope(scope, tokens) -> None:
    tokens.append(current_write_scope.set(scope))


def _async_probe_runner(record: list):
    """start() 异步路径最小构造：探针记录 worker 线程内看到的 write scope."""
    r = SubAgentRunner.__new__(SubAgentRunner)
    r.registry = _FakeRegistry()
    r.max_depth = 3
    r.llm = object()
    r._llm_resolver = None
    r._project_coordinator = None
    r._children_guard = threading.Lock()
    r._handles = {}

    def _fake_run_reserved_child(**kwargs):
        record.append(current_write_scope.get())
        kwargs["startup_event"].set()
        kwargs["startup_state"].update({"ok": True})
        return SubAgentResult(final_answer="probe done", outcome="completed")

    r._run_reserved_child = _fake_run_reserved_child
    r._finalize_child = mock.Mock(side_effect=lambda sid, parent, result: result)
    sid = "child-wscope-async-0001"
    handle = SimpleNamespace(generation="g1", review_isolated=False, thread=None)
    sess = SimpleNamespace(parent_id="")
    r._reserve_background_child = mock.Mock(
        return_value=(sid, threading.Event(), sess, handle)
    )
    return r, sid


def _sync_probe_runner(record: list):
    """run() 同步路径（workflow local executor 同款入口）最小构造."""
    r = SubAgentRunner.__new__(SubAgentRunner)
    r.max_depth = 3
    r.llm = object()
    r._llm_resolver = None
    r._project_coordinator = None
    # run() finally 兜底清理触碰的活跃拓扑簿记（正常路径为空，仅满足属性在位）
    r._children_guard = threading.Lock()
    r._cancel_events = {}

    def _fake_run_reserved_child(**kwargs):
        record.append(current_write_scope.get())
        return SubAgentResult(final_answer="sync probe done", outcome="completed")

    r._run_reserved_child = _fake_run_reserved_child
    r._finalize_child = mock.Mock(side_effect=lambda sid, parent, result: result)
    sid = "child-wscope-sync-0001"
    r._reserve_child = mock.Mock(
        return_value=(sid, threading.Event(), SimpleNamespace(parent_id=""))
    )
    return r


# ── T3/FR-3: 未声明 → 继承父；既有 spawn 零变化 ──


class TestUndeclaredInherits:
    def test_compute_undeclared_parent_none_is_full(self, ws_tokens):
        r = SubAgentRunner.__new__(SubAgentRunner)
        _set_parent_scope(None, ws_tokens)
        scope, refusal = r._compute_child_write_scope(None)
        assert refusal == ""
        assert scope is None

    def test_compute_undeclared_inherits_parent_object(self, ws_tokens):
        r = SubAgentRunner.__new__(SubAgentRunner)
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        scope, refusal = r._compute_child_write_scope(None)
        assert refusal == ""
        assert scope is parent

    def test_spawn_without_requires_keeps_call_face_and_receipt(self):
        """既有调用面零变化：kwargs 不新增键；回执结构保持现状形态."""
        runner = RecordingRunner()
        tool = SpawnSubAgentTool(runner)
        res = tool.execute(task="普通子任务")
        assert res.status.value == "success", res.content
        assert len(runner.calls) == 1
        # 未声明 write_scope → 不透传该参数（kwargs 面与现状逐键一致）
        assert set(runner.calls[0]) == {
            "task",
            "context",
            "depth",
            "inherit",
            "acceptance",
            "model",
            "required_tools",
            "fs_isolation",
        }
        # 回执字段与现状一致（无 write_scope 相关新增字段）
        assert "child_state=running child_id=child-test-0001" in res.content
        assert "子代理已在后台启动" in res.content
        assert "write_scope" not in res.content

    def test_spawn_with_tools_only_also_no_write_scope_key(self):
        runner = RecordingRunner()
        tool = SpawnSubAgentTool(runner)
        res = tool.execute(task="工具白名单", requires={"tools": ["read_file"]})
        assert res.status.value == "success", res.content
        assert "required_write_scope" not in runner.calls[0]


# ── T1/FR-1: 非法结构 → 参数错误，不静默忽略 ──


class TestIllegalStructureParamError:
    @pytest.mark.parametrize(
        "illegal",
        [
            "not-a-dict",
            ["paths"],
            {"paths": "src/**"},
            {"mode": "bogus"},
            {"paths": ["ok", ""]},
            {"paths": [123]},
            {"paths": [[]]},
            {"paths": ["x" * 513]},
            {"paths": [f"p{i}" for i in range(65)]},
        ],
    )
    def test_illegal_write_scope_rejected_at_spawn(self, illegal):
        runner = RecordingRunner()
        tool = SpawnSubAgentTool(runner)
        res = tool.execute(task="越权子任务", requires={"write_scope": illegal})
        assert res.status.value == "failure"
        assert "[参数错误]" in res.content
        # 参数错误发生在进入 runner 之前 → 未启动任何 child
        assert runner.calls == []

    def test_tool_schema_declares_write_scope(self):
        import json

        ws = SpawnSubAgentTool.parameters["properties"]["requires"]["properties"][
            "write_scope"
        ]
        assert ws["type"] == "object"
        assert ws["additionalProperties"] is False
        assert ws["properties"]["mode"]["enum"] == ["allow", "deny"]
        assert json.dumps(ws, ensure_ascii=False)  # schema 可序列化


# ── T2/FR-2: 子声明超出父 → refused、detail 含越界项、未启动任何 child ──


class TestOverflowRefused:
    def test_start_refuses_before_reserving_child(self, ws_tokens):
        record: list = []
        r, _ = _async_probe_runner(record)
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        child_req = parse_write_scope({"paths": ["src/a/**", "src/b/**"]})
        with _no_grant():
            started = r.start(task="越界", required_write_scope=child_req)
        assert started["accepted"] is False
        assert started["state"] == "refused"
        assert started["child_id"] == ""
        # detail 含越界项（src/b/** 不被父 src/a/** 覆盖），不静默截断
        assert "src/b/**" in started["detail"]
        assert "超出父" in started["detail"]
        # fail-fast：拒绝发生在预留任何 child 资源之前
        r._reserve_background_child.assert_not_called()
        # T16: 拒绝后父 write scope 无泄漏
        assert current_write_scope.get() is parent

    def test_spawn_tool_surfaces_refused_detail(self, ws_tokens):
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)

        class RefusingRunner(RecordingRunner):
            def start(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "accepted": False,
                    "child_id": "",
                    "state": "refused",
                    "depth": kwargs.get("depth", 0),
                    "detail": "write_scope 声明超出父 scope: src/b/**",
                }

        runner = RefusingRunner()
        tool = SpawnSubAgentTool(runner)
        res = tool.execute(
            task="越界子任务",
            requires={"write_scope": {"paths": ["src/b/**"]}},
        )
        assert res.status.value == "failure"
        assert "refused" in res.content
        assert "src/b/**" in res.content
        # 声明被解析为 WriteScope 后原样透传给 runner
        assert isinstance(runner.calls[0]["required_write_scope"], WriteScope)


# ── §5.1: 父全量 + 子有约束 → 以子为准 ──


class TestParentFullChildWins:
    def test_start_child_constraint_effective_async(self, ws_tokens):
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r, sid = _async_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/x/**"]})
        with _no_grant():
            started = r.start(task="受限写", required_write_scope=child_req)
        assert started["accepted"] is True, started
        assert started["child_id"] == sid
        # worker 线程内生效的正是子声明（以子为准）
        assert record and isinstance(record[0], WriteScope)
        assert record[0].paths == ("src/x/**",)
        assert record[0].declared is True
        # 主线程父 scope 不受 child 线程注入影响（copy_context 隔离 + 无泄漏）
        assert current_write_scope.get() is None

    def test_start_undeclared_inherits_parent_async(self, ws_tokens):
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        record: list = []
        r, _ = _async_probe_runner(record)
        with _no_grant():
            started = r.start(task="继承写域")
        assert started["accepted"] is True, started
        assert record and record[0] is parent


# ── T15: 同步 run() 路径（workflow local executor 同款入口）──


class TestSyncRunPath:
    def test_run_injects_child_scope_and_restores(self, ws_tokens):
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r = _sync_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/x/**"]})
        result = r.run(task="同步受限写", required_write_scope=child_req)
        assert result.outcome == "completed"
        # child 运行期间生效的是子声明（以子为准）
        assert record and isinstance(record[0], WriteScope)
        assert record[0].paths == ("src/x/**",)
        # run() 返回后父 write scope 恢复（T16）
        assert current_write_scope.get() is None

    def test_run_undeclared_inherits_parent(self, ws_tokens):
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        record: list = []
        r = _sync_probe_runner(record)
        result = r.run(task="同步继承")
        assert result.outcome == "completed"
        assert record and record[0] is parent
        assert current_write_scope.get() is parent

    def test_run_refuses_overflow_without_starting_child(self, ws_tokens):
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        record: list = []
        r = _sync_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/b/**"]})
        result = r.run(task="同步越界", required_write_scope=child_req)
        assert result.outcome == "refused"
        assert result.refused is True
        assert "未启动任何 child" in result.final_answer
        assert "src/b/**" in result.final_answer
        # 探针未被触发 = child 执行体从未启动
        assert record == []
        # T16: 拒绝后父 write scope 无泄漏
        assert current_write_scope.get() is parent

    def test_run_declared_false_scope_inherits_parent(self, ws_tokens):
        """paths 键不存在（declared=False）= 未声明，按继承处理（§5.2 三分态）."""
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        record: list = []
        r = _sync_probe_runner(record)
        undeclared_like = parse_write_scope({"mode": "allow"})
        result = r.run(
            task="同步继承（declared=False）",
            required_write_scope=undeclared_like,
        )
        assert result.outcome == "completed"
        assert record and record[0] is parent
        assert current_write_scope.get() is parent


# ── P1-a: 受限 write scope 的 child 保留 execute_command 工具面（DESIGN §16）──
# 写侧约束不再由「工具面剔除」承担，而由命令族闸承担（core/command_scope_guard，
# 见 tests/test_command_scope_guard.py）；本类只守「工具面不被收窄」这一条。


def _full_grant():
    """CHILD_SPAWN_GRANT 全量授予（child 面保留 spawn_subagent）。"""
    return mock.patch(
        "llm_loop.config.load_settings",
        **{"return_value.child_spawn_grant": "*"},
    )


def _sync_tool_scope_probe_runner(record: list):
    """run() 同步路径探针：记录 child 执行体内看到的工具面（工具面≠写域）。"""
    from llm_loop.core import run_context as run_ctx

    r = SubAgentRunner.__new__(SubAgentRunner)
    r.registry = _FakeRegistry()
    r.max_depth = 3
    r.llm = object()
    r._llm_resolver = None
    r._project_coordinator = None
    r._children_guard = threading.Lock()
    r._cancel_events = {}

    def _fake_run_reserved_child(**kwargs):
        record.append(run_ctx.current_tool_discovery_scope.get())
        return SubAgentResult(final_answer="sync probe done", outcome="completed")

    r._run_reserved_child = _fake_run_reserved_child
    r._finalize_child = mock.Mock(side_effect=lambda sid, parent, result: result)
    sid = "child-p1b-sync-0001"
    r._reserve_child = mock.Mock(
        return_value=(sid, threading.Event(), SimpleNamespace(parent_id=""))
    )
    return r


def _scope_names(value) -> set:
    """把回执/探针里的工具面读成名字集合（回执是逗号拼接字符串）。"""
    if value is None:
        return set()
    if isinstance(value, str):
        if not value or value.startswith("full("):
            return set()
        return {part for part in value.split(",") if part}
    return set(value)


class TestP1aToolSurface:
    """受限写域 → child 工具面**保留** execute_command（P1-a 口径；P1-b 剔除口径已作废）。"""

    def test_t17_async_start_restricted_child_keeps_execute_command(self, ws_tokens):
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r, sid = _async_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/x/**"]})
        with _no_grant():
            started = r.start(task="受限写", required_write_scope=child_req)
        assert started["accepted"] is True, started
        scope = _scope_names(started["tool_scope"])
        assert "execute_command" in scope, "P1-a：受限 child 保留命令能力"
        assert "read_file" in scope
        assert "write_scope_tool_restriction" not in started
        assert started["write_scope_command_guard"] == "p1a_write_family"

    def test_t18_sync_run_restricted_child_keeps_execute_command(self, ws_tokens):
        """P1-a：写域不得改变 child 工具面——受限与不受限观测到同一工具面。"""
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r = _sync_tool_scope_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/x/**"]})
        result = r.run(task="同步受限写", required_write_scope=child_req)
        assert result.outcome == "completed", result
        assert record, "child 执行体未被触发"
        restricted_scope = record[0]

        record2: list = []
        r2 = _sync_tool_scope_probe_runner(record2)
        result2 = r2.run(task="同步无写域")
        assert result2.outcome == "completed", result2
        assert record2, "未受限 child 执行体未被触发"

        assert restricted_scope == record2[0], "P1-a：写域不得改变 child 工具面"
        names = _scope_names(restricted_scope)
        assert not names or "execute_command" in names, "P1-a：同步路径同样保留命令能力"

    def test_t19_undeclared_write_scope_keeps_execute_command(self, ws_tokens):
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r, _ = _async_probe_runner(record)
        with _no_grant():
            started = r.start(task="未声明写域")
        assert started["accepted"] is True, started
        assert "execute_command" in started["tool_scope"]
        assert "write_scope_tool_restriction" not in started

    def test_t20_parent_declared_child_inherits_and_keeps_execute_command(self, ws_tokens):
        parent = parse_write_scope({"paths": ["src/a/**"]})
        _set_parent_scope(parent, ws_tokens)
        record: list = []
        r, _ = _async_probe_runner(record)
        with _no_grant():
            started = r.start(task="继承父写域")
        assert started["accepted"] is True, started
        assert "execute_command" in started["tool_scope"]

    def test_t21_declared_tools_with_execute_command_is_kept_not_refused(self, ws_tokens):
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r, _ = _async_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/x/**"]})
        with _no_grant():
            started = r.start(
                task="显式要命令",
                required_tools=["read_file", "execute_command"],
                required_write_scope=child_req,
            )
        assert started["accepted"] is True, started
        scope = _scope_names(started["tool_scope"])
        assert "execute_command" in scope
        assert "read_file" in scope

    def test_t22_explicit_readonly_scope_keeps_tool_surface(self, ws_tokens):
        """显式只读写域：工具面保留（命令能力在），写侧由命令族闸拦截。"""
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r, _ = _async_probe_runner(record)
        readonly = parse_write_scope({"paths": [], "mode": "allow"})
        with _no_grant():
            started = r.start(task="显式只读", required_write_scope=readonly)
        assert started["accepted"] is True, started
        assert "execute_command" in started["tool_scope"]

    def test_t23_full_surface_is_materialized_with_execute_command(self, ws_tokens):
        """P1-a：全量面保持全量（含 execute_command），不被写域裁窄。"""
        _set_parent_scope(None, ws_tokens)
        record: list = []
        r, _ = _async_probe_runner(record)
        child_req = parse_write_scope({"paths": ["src/x/**"]})
        with _full_grant():
            started = r.start(task="全量面物化", required_write_scope=child_req)
        assert started["accepted"] is True, started
        tool_scope = started["tool_scope"]
        if isinstance(tool_scope, str) and tool_scope.startswith("full("):
            assert "write_scope_tool_restriction" not in started
        else:
            names = _scope_names(tool_scope)
            assert "execute_command" in names
            assert "read_file" in names and "wait" in names
