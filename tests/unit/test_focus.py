"""focus 模块（任务聚焦）单测——纯函数/状态类，不依赖 engine 实例.

覆盖: 简单任务判定（复杂动词/工具历史/长输入）、单向切换锁定、任务锚点提取、
注入统一包装。2026-08-22 独立模块化后补测。
"""

from __future__ import annotations

from llm_loop.core.loop.focus import (
    TaskFocusState,
    build_task_anchor,
    is_simple_task,
    wrap_injection,
)


class _M:
    def __init__(self, role, content=""):
        self.role = role
        self.content = content


class _Sess:
    def __init__(self, messages):
        self.messages = messages


def test_is_simple_task_complex_verb():
    """复杂任务动词（配置/修改等）→ False（不切快模型）."""
    assert is_simple_task([{"role": "user", "content": "给镜像LFL配置飞书"}]) is False
    assert is_simple_task([{"role": "user", "content": "帮我修改 .env 配置"}]) is False
    assert is_simple_task([{"role": "user", "content": "部署新版本"}]) is False


def test_is_simple_task_simple_question():
    """简单问题 → True（切快模型）."""
    assert is_simple_task([{"role": "user", "content": "1+1=?"}]) is True
    assert is_simple_task([{"role": "user", "content": "什么是缓存命中？"}]) is True


def test_is_simple_task_tool_history():
    """有工具调用历史 → False（复杂任务信号）."""
    msgs = [{"role": "user", "content": "1+1=?"}, {"role": "tool", "content": "ok"}]
    assert is_simple_task(msgs) is False
    msgs2 = [{"role": "user", "content": "1+1=?"}, {"role": "assistant", "tool_calls": [{"id": "1"}]}]
    assert is_simple_task(msgs2) is False


def test_is_simple_task_long_input():
    """长输入 → False."""
    msgs = [{"role": "user", "content": "请详细说明" * 101}]  # 505 字符 > 500
    assert is_simple_task(msgs) is False


def test_task_focus_state_oneway_lock():
    """单向切换锁定: 判复杂 → mark_escalated → escalated=True; reset 恢复."""
    st = TaskFocusState()
    assert st.escalated is False
    st.mark_escalated()
    assert st.escalated is True
    st.reset()
    assert st.escalated is False


def test_build_task_anchor():
    """任务锚点: 提取最近用户指令 + 最近工具动作."""
    sess = _Sess([
        _M("user", "给镜像LFL配置飞书"),
        _M("assistant", "收到，先查配置"),
        _M("tool", "[命令] grep feishu .env 输出 13 行"),
    ])
    anchor = build_task_anchor(sess)
    assert "配置飞书" in anchor
    assert "grep feishu" in anchor


def test_build_task_anchor_empty():
    """无会话/空消息 → 空串（fail-open）."""
    assert build_task_anchor(None) == ""
    assert build_task_anchor(_Sess([])) == ""


def test_wrap_injection():
    """注入统一包装: 前缀 + 锚点 + 原内容; 已包装不重复."""
    wrapped = wrap_injection("[模型切换感知] ...", "当前任务: 配置飞书")
    assert wrapped.startswith("[上下文注入·非新指令]")
    assert "配置飞书" in wrapped
    assert "[模型切换感知]" in wrapped
    # 已包装 → 原样返回
    assert wrap_injection(wrapped) == wrapped
    # 无内容 → 原样
    assert wrap_injection("") == ""


def test_wrap_injection_no_anchor():
    """无锚点时包装仍带前缀."""
    wrapped = wrap_injection("[经验提示] ...")
    assert wrapped.startswith("[上下文注入·非新指令]")
    assert "[经验提示]" in wrapped
