"""RULE-AI-28: mandatory model obligation, honest observational tooling."""

from pathlib import Path

from llm_loop.tools.builtin.browser_action import BrowserActionTool
from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS
from llm_loop.tools.review_gate import review_gate_note

ROOT = Path(__file__).resolve().parents[2]


def test_rule28_requires_review_of_current_artifact_before_action() -> None:
    rules = (ROOT / "docs/ai_rules.md").read_text(encoding="utf-8")
    section = rules.split("## 规则二十八：", 1)[1].split("\n## 规则二十九：", 1)[0]
    for phrase in (
        "审查是强制前置义务",
        "覆盖当前产物的有效 PASS 回执",
        "所有需要对外发表的文稿",
        "暂缓该动作",
        "泛化的“继续 / 按建议执行 / 授权发布”不构成免审",
    ):
        assert phrase in section
    assert "**程序角色**：无新增。" not in section
    assert "BLOCK（push 闸专属" not in section


def test_all_review_skills_keep_mandatory_obligation_and_evidence_boundary() -> None:
    for name in ("code", "article", "push"):
        text = (ROOT / f"skills/{name}-review-gate/SKILL.md").read_text(encoding="utf-8")
        assert "强制前置义务" in text
        assert "覆盖当前产物" in text
        assert "暂缓该动作" in text
        assert "只提醒不阻断" not in text


def test_obligation_visible_before_shell_call_in_full_and_compact_contract() -> None:
    for description in (
        ExecuteCommandTool.description,
        _COMPACT_TOOL_DESCRIPTIONS["execute_command"],
    ):
        assert "RULE-AI-28" in description
        assert "独立审查" in description
        assert "当前产物" in description
        assert "PASS" in description


def test_receipt_note_does_not_offer_self_certified_review_or_claim_denial() -> None:
    note = review_gate_note("git_push", "unknown", action_label="git push")
    assert "强制前置义务" in note
    assert "未核验" in note
    for forbidden in ("只提醒不阻断", "自声明", "satisfied /", "动作未执行"):
        assert forbidden not in note


def test_browser_publication_obligation_is_conditional_on_publication() -> None:
    descriptions = [
        BrowserActionTool.description,
        BrowserSemanticOperationTool.description,
        _COMPACT_TOOL_DESCRIPTIONS["browser_action"],
        _COMPACT_TOOL_DESCRIPTIONS["browser_operate"],
    ]
    for description in descriptions:
        assert "文稿" in description and "发表前" in description
        assert "RULE-AI-28" in description and "PASS" in description
