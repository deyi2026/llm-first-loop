from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOT = ROOT / "docs" / "ai_rules.md"
LITE = ROOT / "docs" / "ai_rules.lite.md"
LITE_EN = ROOT / "docs" / "ai_rules.lite.en.md"


def _section(text: str, ref: str) -> str:
    match = re.search(rf"^## .*?{re.escape(ref)}.*?$", text, re.MULTILINE)
    assert match, ref
    nxt = re.search(r"^## ", text[match.end():], re.MULTILINE)
    end = match.end() + nxt.start() if nxt else len(text)
    return text[match.start():end]


def test_rule21_transitional_program_feedback_is_retired_from_lite():
    zh = LITE.read_text(encoding="utf-8")
    en = LITE_EN.read_text(encoding="utf-8")
    assert "21程序反馈语义" not in zh
    assert "过渡属性标注" not in zh
    assert "21Program feedback semantics" not in en
    assert "Transitional note" not in en


def test_rule03_18_22_align_current_first_then_history_on_demand():
    text = SOT.read_text(encoding="utf-8")
    r3 = _section(text, "RULE-AI-03")
    r18 = _section(text, "RULE-AI-18")
    r22 = _section(text, "RULE-AI-22")

    assert "当前 schema/code/docs" in r3
    assert "复用已验证路径" in r18
    assert "陌生失败" in r18
    assert "当前证据不足" in r18
    assert "task_applicability" in r18
    assert "当前 schema/code/docs" in r22
    assert "编号 21" not in r22
    assert "过渡条目" not in r22


def test_operator_urls_and_detailed_dsh_codearts_sop_leave_rule_core():
    sot = SOT.read_text(encoding="utf-8")
    lite = LITE.read_text(encoding="utf-8")
    assert "127.0.0.1:8903" not in sot
    assert "127.0.0.1:8902" not in sot
    assert "127.0.0.1:8903" not in lite
    assert "127.0.0.1:8902" not in lite

    r13 = _section(sot, "RULE-AI-13")
    r15 = _section(sot, "RULE-AI-15")
    assert "具体调用参数/重试/后台执行/日志回放以当前 tool schema 为准" in r13
    assert "具体参数/状态查询/取消/失败处理以当前 tool schema 为准" in r15
    assert "timeout_s" not in r13
    assert "handle_id" not in r15


def test_rule21_migration_pointer_is_closed_not_pending():
    sot = SOT.read_text(encoding="utf-8")
    assert "规则 21 程序反馈语义 | RETIRED" in sot
    assert "规则 21 程序反馈语义 | 过渡期保留" not in sot
