"""EVO-20260814-aab7eb0b P2: 循环实时停滞检测测试（3 提醒 / 5 熔断）."""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.tool_exec import (
    _STAGNATION_BREAK_AT,
    _STAGNATION_REMIND_AT,
    _ToolExecMixin,
)
from llm_loop.feedback.honesty import stagnation_feedback, stagnation_reminder_message


class _Sess:
    def __init__(self):
        self.messages = []


class _StubEngine(_ToolExecMixin):
    """最小引擎替身：仅实现 _track_stagnation 依赖的两个钩子."""

    def __init__(self):
        self._stagnation_state = {"fp": None, "count": 0, "reminded": False}
        self._current_turn_ref = 11
        self.events = []
        self.actions = []

    def _append_message_event(self, sess, msg):
        self.events.append(msg)

    def _record_action(self, phase, action, detail):
        self.actions.append((phase, action, detail))


def _tc(name="read_file", **arguments):
    return SimpleNamespace(name=name, arguments=arguments)


def test_below_threshold_no_reminder():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(_STAGNATION_REMIND_AT - 1):
        eng._track_stagnation(_tc(path="/a.py"), sess, [])
    assert sess.messages == []
    assert eng._stagnation_state["count"] == _STAGNATION_REMIND_AT - 1


def test_reminder_injected_once_at_threshold():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(_STAGNATION_REMIND_AT + 1):  # 第 3 次提醒，第 4 次不重复
        eng._track_stagnation(_tc(path="/a.py"), sess, [])
    reminders = [m for m in sess.messages if "[停滞提醒]" in m.content]
    assert len(reminders) == 1  # 只提醒一次
    assert "read_file" in reminders[0].content
    assert reminders[0].metadata.get("prompt_lifecycle") == "current_turn"
    assert reminders[0].metadata.get("turn_ref") == 11
    assert eng.actions and eng.actions[0][0] == "stagnation.reminder"


def test_fingerprint_change_resets_streak():
    eng, sess = _StubEngine(), _Sess()
    for _ in range(2):
        eng._track_stagnation(_tc(path="/a.py"), sess, [])
    eng._track_stagnation(_tc(path="/b.py"), sess, [])  # 参数变了 → 指纹变 → 重置
    assert eng._stagnation_state["count"] == 1
    assert sess.messages == []


def test_should_break_only_at_break_threshold():
    eng, sess = _StubEngine(), _Sess()
    for i in range(1, _STAGNATION_BREAK_AT + 1):
        eng._track_stagnation(_tc(name="execute_command", command="ls"), sess, [])
        should, name, streak = eng._stagnation_should_break()
        if i < _STAGNATION_BREAK_AT:
            assert not should
        else:
            assert should and name == "execute_command" and streak == _STAGNATION_BREAK_AT


def test_feedback_messages_honest_format():
    r = stagnation_reminder_message("read_file", 3)
    assert "事实" in r.content and "建议" in r.content and "read_file" in r.content
    b = stagnation_feedback("read_file", 5, ["read_file"] * 5)
    assert "[停滞熔断]" in b.content and "如实终止" in b.content


# ── EVO-20260823-9bb27899: 搜索类工具目标级指纹 + 空结果计数 ──

def _empty_result(content="未找到匹配 'x' 的记录（不伪造结果）。"):
    return SimpleNamespace(status=SimpleNamespace(value="success"), content=content)


def _nonempty_result(content="[状态: success] 找到 1 条"):
    return SimpleNamespace(status=SimpleNamespace(value="success"), content=content)


def test_search_target_fingerprint_ignores_detail_params():
    """同目标不同细节参数（limit/root 变化）→ 同一目标指纹 → 计数累计."""
    eng, sess = _StubEngine(), _Sess()
    eng._track_stagnation(
        _tc(name="search_files", pattern="*.md", root="/a"), sess, []
    )
    eng._track_stagnation(
        _tc(name="search_files", pattern="*.md", root="/b", max_results=50), sess, []
    )
    assert eng._stagnation_state["count"] == 2  # 目标均为 pattern=*.md → 连续累计
    assert eng._stagnation_state["fp"] == "search_files|{\"pattern\": \"*.md\"}"


def test_search_empty_result_reminder_at_threshold():
    """搜索类工具连续空结果 ≥2 → 注入 [搜索空结果提醒]（一次）."""
    eng, sess = _StubEngine(), _Sess()
    eng._track_stagnation(
        _tc(name="search_records", kind="action_trace", query="x"), sess, [],
        result=_empty_result(),
    )
    eng._track_stagnation(
        _tc(name="search_records", kind="memory", query="x"), sess, [],
        result=_empty_result(),
    )
    reminders = [m for m in sess.messages if "[搜索空结果提醒]" in m.content]
    assert len(reminders) == 1
    assert "search_records" in reminders[0].content
    assert reminders[0].metadata.get("prompt_lifecycle") == "current_turn"
    assert reminders[0].metadata.get("turn_ref") == 11
    assert eng.actions and eng.actions[-1][0] == "empty_search.reminder"


def test_search_empty_result_reminder_single_injection():
    """空结果提醒只注入一次（连续多次不再重复）."""
    eng, sess = _StubEngine(), _Sess()
    for _ in range(5):
        eng._track_stagnation(
            _tc(name="search_archive", query="x"), sess, [],
            result=_empty_result(),
        )
    reminders = [m for m in sess.messages if "[搜索空结果提醒]" in m.content]
    assert len(reminders) == 1


def test_nonempty_result_resets_empty_streak():
    """非空结果重置空结果计数（前提有效时正常推进不受干扰）."""
    eng, sess = _StubEngine(), _Sess()
    eng._track_stagnation(
        _tc(name="search_files", pattern="*.py"), sess, [], result=_empty_result()
    )
    eng._track_stagnation(
        _tc(name="search_files", pattern="*.py"), sess, [], result=_nonempty_result()
    )
    assert eng._stagnation_state["empty_count"] == 0
    assert sess.messages == []


# ── EVO-20260823-12be9cac 边界①: execute_command 搜索命令空结果同样计数 + 登记否定帧 ──

def test_exec_cmd_find_empty_counts_and_registers():
    """execute_command 的 find 空结果 → 计入空结果计数 + 登记否定帧（跨会话防反复搜索）."""
    from llm_loop.tools import path_registry as pr

    pr.reset()
    eng, sess = _StubEngine(), _Sess()
    eng._track_stagnation(
        _tc(name="execute_command", command="find wkdir -name ANALYSIS-2026*.md"),
        sess, [],
        result=_empty_result("（命令执行成功，无输出）"),
    )
    eng._track_stagnation(
        _tc(name="execute_command", command="find wkdir -maxdepth 3 -name ANALYSIS-2026*.md"),
        sess, [],
        result=_empty_result("（命令执行成功，无输出）"),
    )
    # 空结果计数达 2 → 注入 [搜索空结果提醒]（execute_command 变体也被拦截）
    reminders = [m for m in sess.messages if "[搜索空结果提醒]" in m.content]
    assert len(reminders) == 1
    assert eng.actions and eng.actions[-1][0] == "empty_search.reminder"
    # 否定帧已登记（目标键 cmd:...）
    assert pr.check_known_missing("cmd:find wkdir -name ANALYSIS-2026*.md")


def test_exec_cmd_non_search_empty_not_counted():
    """execute_command 非搜索命令（python 正常无输出）不视为搜索空结果（防误判）."""
    eng, sess = _StubEngine(), _Sess()
    eng._track_stagnation(
        _tc(name="execute_command", command="python3 -c 'print()'"), sess, [],
        result=_empty_result("（无输出）"),
    )
    assert eng._stagnation_state["empty_count"] == 0
    assert sess.messages == []
