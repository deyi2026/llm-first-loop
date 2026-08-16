"""EVO-20260816-62977206: 工具执行后经验提示注入（tool_exec._inject_experience_tips）.

覆盖: 命中注入 / 无命中不注入 / 开关关不注入 / 目录不存在 fail-open 不抛。
mixin 桩: 提供 settings(mixin 访问) + messages/events(注入落点) + _append_message_event。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.loop.tool_exec import _ToolExecMixin

_EXP_MD = """---
title: web_fetch 抓取最短路径
scenario: web_fetch 抓网页失败需换路径
root_cause: 反爬/JS 壳
solution: 用 curl 直取 HTML 再解析
evidence: test
tags: [web_fetch, 抓取]
source: {}
status: active
created_at: "2026-08-16T00:00:00+08:00"
updated_at: "2026-08-16T00:00:00+08:00"
---
"""


class _Stub:
    """LoopEngine 最小桩（mixin 方法所需属性）."""

    def __init__(self, enabled: bool, exp_dir: str | Path) -> None:
        self.settings = SimpleNamespace(
            tool_experience_inject=enabled, experiences_dir=str(exp_dir)
        )
        self.messages = []
        self.events = []

    def _append_message_event(self, sess, msg) -> None:
        self.events.append(msg)


def _make_exp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "experiences"
    d.mkdir()
    (d / "EXPERIENCE-test-web-fetch.md").write_text(_EXP_MD, encoding="utf-8")
    return d


def test_inject_hit(tmp_path):
    """命中: 工具名匹配经验 → 末尾注入 [经验提示] system 消息."""
    d = _make_exp_dir(tmp_path)
    stub = _Stub(True, d)
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    assert len(stub.messages) == 1
    msg = stub.messages[0]
    assert msg.role == "system"
    assert "[经验提示]" in msg.content
    assert "web_fetch" in msg.content
    assert msg.metadata.get("injected_system") is True
    assert len(stub.events) == 1


def test_inject_no_hit_no_inject(tmp_path):
    """无命中: 不注入（零开销原则）."""
    d = _make_exp_dir(tmp_path)
    stub = _Stub(True, d)
    _ToolExecMixin._inject_experience_tips(stub, stub, ["nonexistent_tool"])
    assert stub.messages == []


def test_inject_disabled(tmp_path):
    """开关关: 不注入."""
    d = _make_exp_dir(tmp_path)
    stub = _Stub(False, d)
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    assert stub.messages == []


def test_inject_dir_missing_fail_open(tmp_path):
    """经验目录不存在: fail-open 不抛、不注入."""
    stub = _Stub(True, tmp_path / "no_such_dir")
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    assert stub.messages == []
