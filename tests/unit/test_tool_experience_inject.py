"""R8.15/E08: post-tool generic experience catalog is on-demand only.

The compatibility hook may record observability, but it must not query the
experience/skill stores or append prompt/session messages.
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


class _ExplodingStore:
    def list_active(self, *args, **kwargs):
        raise AssertionError("generic catalog must not query ExperienceStore")


class _Stub(_ToolExecMixin):
    def __init__(
        self, enabled: bool, exp_dir: str | Path, skills_dir: str | Path = "nonexistent_skills"
    ) -> None:
        self.settings = SimpleNamespace(
            tool_experience_inject=enabled,
            experiences_dir=str(exp_dir),
            skills_dir=str(skills_dir),
        )
        self.messages = []
        self.events = []
        self.actions = []
        self._tip_tail_messages = []
        self._exp_store = _ExplodingStore()
        type(self)._skills_cache = (0.0, [])

    def _append_message_event(self, sess, msg) -> None:
        self.events.append(msg)

    def _record_action(self, kind, status, detail) -> None:
        self.actions.append((kind, status, detail))


def _make_exp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "experiences"
    d.mkdir()
    (d / "EXPERIENCE-test-web-fetch.md").write_text(_EXP_MD, encoding="utf-8")
    return d


def test_catalog_hit_is_on_demand_only(tmp_path):
    stub = _Stub(True, _make_exp_dir(tmp_path))
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    assert stub.messages == [] and stub.events == [] and stub._tip_tail_messages == []
    assert stub.actions == [
        ("experience.catalog", "on_demand_only", "tools=web_fetch;prompt_chars=0")
    ]


def test_catalog_does_not_evaluate_hit_or_miss(tmp_path):
    stub = _Stub(True, _make_exp_dir(tmp_path))
    _ToolExecMixin._inject_experience_tips(stub, stub, ["nonexistent_tool"])
    assert stub.messages == [] and stub.events == []
    assert stub.actions == [
        ("experience.catalog", "on_demand_only", "tools=nonexistent_tool;prompt_chars=0")
    ]


def test_catalog_switch_off_is_silent(tmp_path):
    stub = _Stub(False, _make_exp_dir(tmp_path))
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    assert stub.messages == [] and stub.events == [] and stub.actions == []


def test_catalog_missing_dir_never_reads_storage(tmp_path):
    stub = _Stub(True, tmp_path / "no_such_dir")
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch"])
    assert stub.messages == []
    assert stub.actions == [
        ("experience.catalog", "on_demand_only", "tools=web_fetch;prompt_chars=0")
    ]


def test_catalog_deduplicates_tool_names_without_prompt_state(tmp_path):
    stub = _Stub(True, _make_exp_dir(tmp_path))
    _ToolExecMixin._inject_experience_tips(stub, stub, ["web_fetch", "web_fetch", "read_file"])
    assert stub.messages == []
    assert stub.actions == [
        ("experience.catalog", "on_demand_only", "tools=web_fetch,read_file;prompt_chars=0")
    ]


def test_catalog_empty_tool_list_is_zero_work(tmp_path):
    stub = _Stub(True, _make_exp_dir(tmp_path))
    _ToolExecMixin._inject_experience_tips(stub, stub, [])
    assert stub.messages == [] and stub.actions == []
