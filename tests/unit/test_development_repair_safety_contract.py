from __future__ import annotations

import re
from pathlib import Path

from llm_loop.introspection.rule_index import RuleIndex

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "docs" / "DEVELOPMENT_REPAIR_SAFETY.md"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_canonical_development_repair_contract_keeps_six_hard_questions() -> None:
    text = CANON.read_text(encoding="utf-8")
    required = (
        "开发/修复前六问硬门",
        "完整事实源还在吗",
        "模型以后真的找得到并读得回来吗",
        "模型所谓“忘了/重复/变笨/空响应”",
        "当前 runtime",
        "程序是不是开始替模型做语义判断",
        "最终 candidate",
        "先取证，再开发",
    )
    for marker in required:
        assert marker in text, marker


def test_third_party_agent_entrypoints_point_to_one_canonical_contract() -> None:
    root_agents = _read("AGENTS.md")
    contributing = _read("CONTRIBUTING.md")
    for text in (root_agents, contributing):
        assert "docs/DEVELOPMENT_REPAIR_SAFETY.md" in text
    assert "RULE-AI-24" in root_agents
    assert "RULE-AI-24" in contributing


def test_lfl_rule_sot_exposes_rule24_exactly_without_prompt_injection() -> None:
    index = RuleIndex(ROOT / "docs" / "ai_rules.md")
    rows = index.search("RULE-AI-24", limit=3)
    assert len(rows) == 1
    row = rows[0]
    assert row["rule_ref"] == "RULE-AI-24"
    assert row["representation"] == "full_rule"
    assert row["projection_complete"] is True
    assert row["authority"] == "rule_sot"
    assert "docs/DEVELOPMENT_REPAIR_SAFETY.md" in row["content"]
    assert "完整事实源仍在吗" in row["content"]
    assert "staged candidate" in row["content"]

    # Discovery by maintenance-language keywords must return the rule card as well.
    cards = index.search("开发 修复 防退化", limit=5)
    assert cards and cards[0]["rule_ref"] == "RULE-AI-24"
    assert cards[0]["representation"] == "rule_card"

    prompt = _read("src/llm_loop/core/prompt.py")
    assert "RULE-AI-24" not in prompt
    assert "DEVELOPMENT_REPAIR_SAFETY" not in prompt


def test_lite_playbooks_are_v15_and_keep_compact_maintenance_contracts() -> None:
    zh = _read("docs/ai_rules.lite.md")
    en = _read("docs/ai_rules.lite.en.md")
    for text in (zh, en):
        first = text.splitlines()[0]
        assert re.search(r"version=15\b", first)
        assert "RULE-AI-24" in text
        assert "docs/DEVELOPMENT_REPAIR_SAFETY.md" in text
        assert "merge" in text.lower()
        assert "-s ours" in text
    assert len(zh) < 3000
