"""P2-A Rule-first: repeated-call / empty-search factual observability tests.

Program code may report exact repeated calls and consecutive empty search receipts, but it
must not merge semantically different calls, persist a deny state, block tools, or end a run.
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.loop.tool_exec import _STAGNATION_REMIND_AT


class _Sess:
    def __init__(self):
        self.messages = []


class _StubEngine(ToolCycleService):
    def __init__(self):
        self._host = self
        self._run_state_mgr = RunStateManager()
        self.events = []
        self.actions = []

    def _run_state(self):
        return self._run_state_mgr.bucket()

    def _append_message_event(self, sess, msg):
        self.events.append(msg)

    def _record_action(self, phase, action, detail):
        self.actions.append((phase, action, detail))


def _tc(name="read_file", **arguments):
    return SimpleNamespace(name=name, arguments=arguments)


def _empty_result(content="未找到匹配 'x' 的记录（不伪造结果）。"):
    return SimpleNamespace(status=SimpleNamespace(value="success"), content=content)


def _nonempty_result(content="[状态: success] 找到 1 条"):
    return SimpleNamespace(status=SimpleNamespace(value="success"), content=content)


def test_below_threshold_no_repeat_event():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(_STAGNATION_REMIND_AT - 1):
        eng._track_tool_observation(_tc(path="/a.py"), sess, [])
    assert eng.actions == []
    assert eng._run_state().stagnation_state["count"] == _STAGNATION_REMIND_AT - 1


def test_exact_repeat_observed_once_at_threshold():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(_STAGNATION_REMIND_AT + 2):
        eng._track_tool_observation(_tc(path="/a.py"), sess, [])
    events = [a for a in eng.actions if a[0] == "tool.repeat_observed"]
    assert events == [
        (
            "tool.repeat_observed",
            "observed",
            f"tool=read_file; exact_call_count={_STAGNATION_REMIND_AT}; prompt_chars=0",
        )
    ]
    assert sess.messages == []


def test_argument_change_resets_repeat_count():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(2):
        eng._track_tool_observation(_tc(path="/a.py"), sess, [])
    eng._track_tool_observation(_tc(path="/b.py"), sess, [])
    assert eng._run_state().stagnation_state["count"] == 1


def test_search_different_roots_are_different_exact_calls():
    """P2-A regression: program must not collapse root/depth/options into a semantic target."""
    eng, sess = _StubEngine(), _Sess()
    a = _tc(name="search_files", pattern="*.md", root="/a")
    b = _tc(name="search_files", pattern="*.md", root="/b", max_results=50)
    assert eng._stagnation_fingerprint(a) != eng._stagnation_fingerprint(b)
    eng._track_tool_observation(a, sess, [])
    eng._track_tool_observation(b, sess, [])
    assert eng._run_state().stagnation_state["count"] == 1


def test_empty_search_observed_once_at_threshold():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(4):
        eng._track_tool_observation(
            _tc(name="search_records", kind="memory", query="x"),
            sess,
            [],
            result=_empty_result(),
        )
    events = [a for a in eng.actions if a[0] == "tool.empty_search_observed"]
    assert len(events) == 1
    assert events[0][1] == "observed"
    assert "consecutive_empty=2" in events[0][2]
    assert sess.messages == []


def test_nonempty_search_resets_empty_count():
    eng, sess = _StubEngine(), _Sess()
    eng._track_tool_observation(
        _tc(name="search_files", pattern="*.py"), sess, [], result=_empty_result()
    )
    eng._track_tool_observation(
        _tc(name="search_files", pattern="*.py"), sess, [], result=_nonempty_result()
    )
    assert eng._run_state().stagnation_state["empty_count"] == 0


def test_empty_search_never_writes_path_registry(monkeypatch):
    """A search miss is not a filesystem non-existence fact."""
    from llm_loop.tools import path_registry as pr

    writes: list[tuple[str, str]] = []

    def _spy(path: str, *, source: str = "tool") -> None:
        writes.append((path, source))

    monkeypatch.setattr(pr, "register_missing", _spy)
    eng, sess = _StubEngine(), _Sess()
    for command in (
        "find wkdir -name ANALYSIS-2026*.md",
        "find wkdir -maxdepth 3 -name ANALYSIS-2026*.md",
    ):
        eng._track_tool_observation(
            _tc(name="execute_command", command=command),
            sess,
            [],
            result=_empty_result("（命令执行成功，无输出）"),
        )
    assert writes == []
    assert any(a[0] == "tool.empty_search_observed" for a in eng.actions)


def test_non_search_empty_command_not_counted():
    eng, sess = _StubEngine(), _Sess()
    eng._track_tool_observation(
        _tc(name="execute_command", command="python3 -c 'print()'"),
        sess,
        [],
        result=_empty_result("（无输出）"),
    )
    assert eng._run_state().stagnation_state["empty_count"] == 0
