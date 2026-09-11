from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from llm_loop.core.prompt import build_system_prompt
from llm_loop.introspection.registry_introspection import _SEARCH_RECORDS_TOOL_DEF
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

RULE_DOC = """# AI Rules

## 规则三：停滞自主调整（RULE-AI-03）

**规则**：重复无进展时主动调整；陌生失败先核对当前 schema/code/docs，再按需查历史。

---

## 规则十八：经验按需复用（RULE-AI-18）

**规则**：经验是历史证据，不是当前策略。当前事实不足时按需检索经验，命中后检查时效和适用性。

**程序角色**：提供稳定 ref、来源和时间事实，不替模型判断 applicability。

---

## 规则二十二：检索时序纪律（RULE-AI-22）

**规则**：先有当前锚点，再聚焦当前窗口，必要时扩展历史；历史命中进入结论前检查时间与当前任务相关性。

---
"""


def _searcher(tmp_path: Path) -> RecordSearcher:
    rule_path = tmp_path / "ai_rules.md"
    rule_path.write_text(RULE_DOC, encoding="utf-8")
    return RecordSearcher(audit_dir=tmp_path / "audit", rule_path=rule_path)


def test_rule_discovery_returns_compact_stable_cards(tmp_path):
    searcher = _searcher(tmp_path)

    rows = searcher.search(kind="rule", query="经验 历史", limit=10)

    assert rows
    row = rows[0]
    assert row["rule_ref"] == "RULE-AI-18"
    assert row["key"] == "RULE-AI-18"
    assert row["authority"] == "rule_sot"
    assert row["representation"] == "rule_card"
    assert row["projection_complete"] is False
    assert row["task_applicability"] == "not_evaluated"
    assert "经验按需复用" in row["summary"]
    assert "完整 section" not in row.get("content", "")


def test_exact_rule_ref_hydrates_complete_section_with_source_version(tmp_path):
    searcher = _searcher(tmp_path)

    rows = searcher.search(kind="rule", query="RULE-AI-18", limit=10)

    assert len(rows) == 1
    row = rows[0]
    assert row["rule_ref"] == "RULE-AI-18"
    assert row["hydrated"] is True
    assert row["representation"] == "full_rule"
    assert row["projection_complete"] is True
    assert row["authority"] == "rule_sot"
    assert row["task_applicability"] == "not_evaluated"
    assert row["source"].endswith("ai_rules.md")
    assert row["source_version_token"] == sha256(RULE_DOC.encode()).hexdigest()
    assert "## 规则十八" in row["content"]
    assert "## 规则二十二" not in row["content"]


def test_empty_rule_query_lists_index_without_hydrating_full_sot(tmp_path):
    searcher = _searcher(tmp_path)

    rows = searcher.search(kind="rule", query="", limit=10)

    assert [r["rule_ref"] for r in rows] == ["RULE-AI-03", "RULE-AI-18", "RULE-AI-22"]
    assert all(r["representation"] == "rule_card" for r in rows)
    assert all(r["projection_complete"] is False for r in rows)
    assert all("content" not in r for r in rows)


def test_search_records_model_receipt_preserves_rule_ref_and_exact_body(tmp_path):
    searcher = _searcher(tmp_path)

    card = run_search_records(
        None,
        searcher.search,
        {"kind": "rule", "query": "经验 历史"},
        lambda: "sid",
    )
    assert card.status.value == "success"
    assert "rule_ref=RULE-AI-18" in card.content
    assert "representation=rule_card" in card.content
    assert "task_applicability=not_evaluated" in card.content
    assert "程序角色" not in card.content

    full = run_search_records(
        None,
        searcher.search,
        {"kind": "rule", "query": "RULE-AI-18"},
        lambda: "sid",
    )
    assert full.status.value == "success"
    assert "rule_ref=RULE-AI-18" in full.content
    assert "representation=full_rule" in full.content
    assert "projection_complete=true" in full.content
    assert "经验是历史证据" in full.content
    assert "程序角色" in full.content


def test_rule_access_extends_existing_tool_without_expanding_universal_prompt():
    kind_enum = _SEARCH_RECORDS_TOOL_DEF["parameters"]["properties"]["kind"]["enum"]
    assert "rule" in kind_enum
    assert "RULE-AI" in _COMPACT_TOOL_DESCRIPTIONS["search_records"]
    prompt = build_system_prompt()
    assert len(prompt) < 400
    assert "RULE-AI" not in prompt
    assert "按需检索已验证经验/方法并核适用性" in prompt
