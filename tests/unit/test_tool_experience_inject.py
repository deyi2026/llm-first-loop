"""EVO-20260816-62977206: 工具执行后经验提示注入（tool_exec._inject_experience_tips）.

覆盖: 命中注入 / 无命中不注入 / 开关关不注入 / 目录不存在 fail-open 不抛。
mixin 桩: 提供 settings(mixin 访问) + messages/events(注入落点) + _append_message_event。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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

_SKILL_MD = """---
name: cache-hit-debug
description: LLM 前缀缓存命中排查技能——缓存命中率异常低时使用；三实验法定位根因。触发工具: architecture_status/execute_command/search_records/search_archive。
---
# 缓存排查
"""


class _Stub(_ToolExecMixin):
    """LoopEngine 最小桩（mixin 方法所需属性；继承 mixin 获得 _match_skills）."""

    def __init__(self, enabled: bool, exp_dir: str | Path, skills_dir: str | Path = "nonexistent_skills") -> None:
        self.settings = SimpleNamespace(
            tool_experience_inject=enabled,
            experiences_dir=str(exp_dir),
            skills_dir=str(skills_dir),
        )
        self.messages = []
        self.events = []
        # 重置类级 skill 缓存（跨测试隔离）
        type(self)._skills_cache = (0.0, [])

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


def _make_skills_dir(tmp_path: Path, name: str = "cache-hit-debug") -> Path:
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    return tmp_path / "skills"


def test_skill_inject_hit(tmp_path):
    """EVO-20260816-ec8c36bb: 工具名命中 skill → 注入 '可用 skill' 行."""
    d = _make_exp_dir(tmp_path)  # 经验库为空命中
    sd = _make_skills_dir(tmp_path)
    stub = _Stub(True, d, sd)
    _ToolExecMixin._inject_experience_tips(stub, stub, ["architecture_status"])
    # 经验库无 architecture_status 命中 → 走 skill 匹配（kw_pool 含 cache/debug）
    assert len(stub.messages) == 1
    msg = stub.messages[0]
    assert "[经验提示]" in msg.content
    assert "cache-hit-debug" in msg.content
    assert "skill_load" in msg.content


def test_skill_no_dir_no_inject(tmp_path):
    """skills 目录不存在: fail-open 不抛、不注入."""
    d = _make_exp_dir(tmp_path)
    stub = _Stub(True, d)  # skills_dir 默认 nonexistent_skills
    _ToolExecMixin._inject_experience_tips(stub, stub, ["architecture_status"])
    assert stub.messages == []


def test_skill_unmatched_no_inject(tmp_path):
    """无 skill 匹配关键词: 不注入."""
    d = _make_exp_dir(tmp_path)
    sd = _make_skills_dir(tmp_path)
    stub = _Stub(True, d, sd)
    _ToolExecMixin._inject_experience_tips(stub, stub, ["zzz_unrelated_tool"])
    assert stub.messages == []
