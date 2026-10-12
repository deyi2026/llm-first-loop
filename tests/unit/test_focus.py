"""Factual task-anchor and legacy appendix rendering helpers.

Program-side task-complexity/model-routing policy is deliberately retired.
"""

from __future__ import annotations

from llm_loop.core.injection_labels import (
    PROGRAM_APPENDIX_NOTICE,
    REFERENCE_LABEL,
    STATUS_LABEL,
)
from llm_loop.core.loop.focus import build_task_anchor, wrap_injection


class _M:
    def __init__(self, role, content=""):
        self.role = role
        self.content = content


class _Sess:
    def __init__(self, messages):
        self.messages = messages







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
    assert wrapped.startswith(PROGRAM_APPENDIX_NOTICE)
    assert wrapped.count(PROGRAM_APPENDIX_NOTICE) == 1
    assert STATUS_LABEL in wrapped
    assert "配置飞书" in wrapped
    assert "[模型切换感知]" in wrapped
    # 已包装 → 原样返回
    assert wrap_injection(wrapped) == wrapped
    # 无内容 → 原样
    assert wrap_injection("") == ""


def test_wrap_injection_no_anchor():
    """无锚点时包装仍带前缀."""
    wrapped = wrap_injection("[经验提示] ...")
    assert wrapped.startswith(PROGRAM_APPENDIX_NOTICE)
    assert wrapped.count(PROGRAM_APPENDIX_NOTICE) == 1
    assert REFERENCE_LABEL in wrapped
    assert "[经验提示]" in wrapped
