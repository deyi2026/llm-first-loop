"""单元测试: 故障自愈 FaultClassifier + SelfHealBudget（T49 / FR-AUTO-SELFHEAL）."""

from __future__ import annotations

from llm_loop.feedback.fault_classifier import FaultClassifier
from llm_loop.feedback.selfheal_budget import SelfHealBudget
from llm_loop.llm.errors import LLMNetworkError, LLMTimeoutError


def test_classify_transient_healable():
    """瞬态超时 → 可自愈 + 建议动作."""
    c = FaultClassifier()
    r = c.classify("llm", LLMTimeoutError("timeout"))
    assert r.healable is True
    assert "retry_tool" in r.suggested_actions


def test_classify_data_corruption_not_healable():
    """数据损坏 → 不可自愈 + note 如实说明."""
    c = FaultClassifier()
    r = c.classify("memory", __import__("json").JSONDecodeError("x", "d", 0))
    assert r.healable is False
    assert r.note and "人工" in r.note


def test_classify_unknown_fallback():
    """未命中 → 默认不可自愈 + 如实标注（不误导）."""
    c = FaultClassifier()
    r = c.classify("unknown_comp", ValueError("x"))
    assert r.healable is False
    assert r.category == "unknown"
    assert "无法判定" in r.note


def test_budget_attempts():
    """单故障次数上限."""
    b = SelfHealBudget(max_attempts=3, max_per_round=10)
    assert b.can_attempt("llm", "LLMTimeoutError") is True
    assert b.can_attempt("llm", "LLMTimeoutError") is True
    assert b.can_attempt("llm", "LLMTimeoutError") is True
    assert b.can_attempt("llm", "LLMTimeoutError") is False  # 超限
    assert b.remaining("llm", "LLMTimeoutError") == 0


def test_budget_per_round():
    """单轮动作上限."""
    b = SelfHealBudget(max_attempts=10, max_per_round=2)
    assert b.can_attempt("a", "E1") is True
    assert b.can_attempt("b", "E2") is True
    assert b.can_attempt("c", "E3") is False  # 单轮超限
    b.reset_round()
    assert b.can_attempt("c", "E3") is True  # 新轮重置


def test_budget_reset_all():
    b = SelfHealBudget(max_attempts=2, max_per_round=10)
    b.can_attempt("x", "E")
    b.can_attempt("x", "E")
    assert b.can_attempt("x", "E") is False
    b.reset_all()
    assert b.can_attempt("x", "E") is True


def test_program_error_message_enhanced():
    """program_error_message 含可自愈性与建议（M12 增强）."""
    from llm_loop.feedback.fault_classifier import FaultClassifier
    from llm_loop.feedback.honesty import program_error_message

    cls = FaultClassifier().classify("llm", LLMNetworkError("net"))
    msg = program_error_message(
        "llm",
        LLMNetworkError("net"),
        classification=cls,
        healable=True,
        suggested_actions=("retry_tool",),
    )
    assert "可自愈性" in msg.content
    assert "可修复行动建议" in msg.content
    assert "retry_tool" in msg.content
