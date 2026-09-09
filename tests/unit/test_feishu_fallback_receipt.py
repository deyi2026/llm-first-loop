"""Feishu renders structured model fallback as a current-run delivery fact only."""

from types import SimpleNamespace

from llm_loop.feishu.handlers import _fallback_receipt_line


def test_fallback_receipt_line_renders_structured_fact() -> None:
    result = SimpleNamespace(fallback_receipt={"from": "p/a", "to": "p/b", "reason": "rate_limit"})
    assert _fallback_receipt_line(result) == "\n[模型降级: p/a→p/b, 原因: rate_limit]"


def test_fallback_receipt_line_is_empty_without_real_receipt() -> None:
    assert _fallback_receipt_line(SimpleNamespace(fallback_receipt=None)) == ""
    assert _fallback_receipt_line(SimpleNamespace(fallback_receipt={})) == ""
    assert _fallback_receipt_line(SimpleNamespace()) == ""
