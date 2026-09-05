"""Minimal universal prompt contract after prompt-authority retirement."""

from __future__ import annotations

from llm_loop.core.prompt import build_system_prompt


def test_prompt_keeps_minimal_agency_root():
    prompt = build_system_prompt()
    assert "llm-first-loop" in prompt
    assert "程序提供工具和运行环境" in prompt
    assert "不替你制定任务策略或完成裁决" in prompt


def test_prompt_has_no_operational_playbook():
    prompt = build_system_prompt()
    for forbidden in (
        "ai_rules.lite", "read_file(full=true)", "rules_version",
        "reasoning_content", "tool_call_id", "search_archive", "search_records",
        "[[memory]]", "失败如实说明并调整后重试一次", "最终回答前对照本轮工具回执",
    ):
        assert forbidden not in prompt


def test_prompt_is_small_static_contract():
    first = build_system_prompt()
    second = build_system_prompt()
    assert first == second
    assert len(first) == 64
    assert build_system_prompt("ignored-policy") == first
