# B-03 命名键规范值键表（M1 TASK-15377274-003，DESIGN v1.1 §3.6/§8 T-10 离线部分）
"""红→绿契约：基线 7ae768519 上逐条失败；修复后全绿。

- key_events_for_chord 的 event.key 必须是 DOM KeyboardEvent.key 规范值：
  Enter/Escape/Tab/Backspace/Delete/Home/End/PageUp/PageDown/Arrow*/F1-F12 与
  code 同形；Space 是字面空格 U+0020；backtick 家族是 ` 字符；单字符键原样。
- 命名键闭集：闭集外多字符键名（如 notakey）策略层 key_not_allowed，
  执行器零 CDP 请求（RULE-AI-35 应拦输入实测）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_browser_m2a_presskey_hover_dialog_download_v01 import _cdp_host, _RecordingWs

from llm_loop.browser.action import press_key_policy_error
from llm_loop.browser.cdp_action_host import _ActuatorContractError, key_events_for_chord

NAMED_EXPECTATIONS = [
    # (token, DOM 规范 key, code, windowsVirtualKeyCode)
    ("Enter", "Enter", "Enter", 13),
    ("escape", "Escape", "Escape", 27),
    ("Tab", "Tab", "Tab", 9),
    ("Space", " ", "Space", 32),
    ("Backspace", "Backspace", "Backspace", 8),
    ("Delete", "Delete", "Delete", 46),
    ("Home", "Home", "Home", 36),
    ("End", "End", "End", 35),
    ("PageUp", "PageUp", "PageUp", 33),
    ("PageDown", "PageDown", "PageDown", 34),
    ("ArrowLeft", "ArrowLeft", "ArrowLeft", 37),
    ("ArrowUp", "ArrowUp", "ArrowUp", 38),
    ("ArrowRight", "ArrowRight", "ArrowRight", 39),
    ("ArrowDown", "ArrowDown", "ArrowDown", 40),
    ("F1", "F1", "F1", 112),
    ("F5", "F5", "F5", 116),
    ("F12", "F12", "F12", 123),
    ("`", "`", "Backquote", 223),
    ("backtick", "`", "Backquote", 223),
]


@pytest.mark.parametrize(
    "token,expected_key,expected_code,expected_vk", NAMED_EXPECTATIONS
)
def test_named_keys_emit_dom_canonical_key(token, expected_key, expected_code, expected_vk):
    """基线（红）：key 字段是小写输入 token（如 "enter"）而非 DOM 规范值。"""
    events = key_events_for_chord(token)
    assert [e["type"] for e in events] == ["keyDown", "keyUp"]
    for event in events:
        assert event["key"] == expected_key
        assert event["code"] == expected_code
        assert event["windowsVirtualKeyCode"] == expected_vk


def test_single_char_keys_unchanged():
    for token in ("a", "1", "z"):
        for event in key_events_for_chord(token):
            assert event["key"] == token


def test_meta_a_modifier_events_unchanged():
    events = key_events_for_chord("Meta+A")
    assert events[0]["key"] == "Meta" and events[0]["modifiers"] == 0
    assert events[1]["key"] == "a" and events[1]["modifiers"] == 4


def test_enter_text_parity_kept():
    events = key_events_for_chord("Enter")
    assert events[0]["text"] == "\r"
    assert "text" not in events[1]


# ── RULE-AI-35：应拦输入实测 ─────────────────────────────────────────

def test_notakey_policy_rejected():
    """闭集外多字符键名：策略层确定性拒绝（基线红：当前返回 None 放行）。"""
    assert press_key_policy_error("notakey") == "key_not_allowed"
    assert press_key_policy_error("Ctrl+notakey") == "key_not_allowed"


def test_notakey_actuator_zero_cdp_requests():
    """应拦输入实测：notakey 到达执行器被拦（契约异常）且零输入派发。

    会话级 setup 请求（attach/enable 等）合法存在；被拦的是
    Input.dispatchKeyEvent——断言没有任何 Input.* 方法被派发。"""
    ws = _RecordingWs()
    host = _cdp_host(ws)
    with pytest.raises(_ActuatorContractError) as excinfo:
        host.dispatch(verb="press_key", physical_target=None, args={"keys": "notakey"})
    assert str(excinfo.value) == "key_not_allowed"
    assert not [r for r in ws.requests if str(r.get("method", "")).startswith("Input.")]


def test_closed_named_tokens_still_pass_policy():
    for keys in ("Enter", "Space", "F1", "Meta+A", "a", "1", "Shift+Tab", "Backtick"):
        assert press_key_policy_error(keys) is None
