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
