from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from llm_loop.core.loop.engine_services.termination_controller import TerminationController
from llm_loop.llm.errors import LLMError, LLMRequestTooLargeError


class _Engine:
    def __init__(self):
        self.state = SimpleNamespace(overflow_reinject_count=0)
        self._overflow_shrink_factor = None
        self.actions = []

    def _run_state(self):
        return self.state

    def _record_action(self, *args):
        self.actions.append(args)

    def _current_context_limit(self, model_used):  # noqa: ARG002
        return 1000


def test_overflow_compacts_without_prompt_reinjection():
    eng: Any = _Engine()
    ctl = TerminationController(eng)
    sess = SimpleNamespace(messages=[])
    action, final = ctl._handle_overflow(
        LLMError("maximum context length exceeded"), sess, "model"
    )
    assert action == "reinject" and final is None
    assert sess.messages == []
    assert eng.state.overflow_reinject_count == 1
    assert eng._overflow_shrink_factor == 0.5
    assert any(a[:2] == ("overflow.compact", "budget_shrunk") for a in eng.actions)
    detail = next(
        a[2] for a in eng.actions if a[:2] == ("overflow.compact", "budget_shrunk")
    )
    assert "source=provider_overflow" in detail


def test_request_envelope_overflow_shrinks_proportionally_instead_of_halving():
    eng: Any = _Engine()
    ctl = TerminationController(eng)
    sess = SimpleNamespace(messages=[])
    exc = LLMRequestTooLargeError(
        "request_too_large",
        observed_chars=152_847,
        limit_chars=150_000,
        provider="chatgpt-web",
    )

    action, final = ctl._handle_overflow(exc, sess, "chatgpt-web/web-gpt")

    assert action == "reinject" and final is None
    expected = (150_000 / 152_847) * 0.97
    assert eng._overflow_shrink_factor == pytest.approx(expected)
    assert 0.94 < eng._overflow_shrink_factor < 0.97
    detail = next(
        a[2] for a in eng.actions if a[:2] == ("overflow.compact", "budget_shrunk")
    )
    assert "source=request_envelope" in detail
    assert "observed_chars=152847" in detail
    assert "limit_chars=150000" in detail


def test_request_envelope_overflow_factor_has_bounded_floor_for_extreme_overshoot():
    eng: Any = _Engine()
    ctl = TerminationController(eng)
    exc = LLMRequestTooLargeError(
        "request_too_large",
        observed_chars=2_000_000,
        limit_chars=150_000,
        provider="chatgpt-web",
    )

    action, final = ctl._handle_overflow(
        exc, SimpleNamespace(messages=[]), "chatgpt-web/web-gpt"
    )

    assert action == "reinject" and final is None
    assert eng._overflow_shrink_factor == 0.10


def test_request_envelope_terminal_is_classified_as_text_ingress_not_token_window():
    eng: Any = _Engine()
    eng.state.overflow_reinject_count = 1
    ctl = TerminationController(eng)
    exc = LLMRequestTooLargeError(
        "request_too_large",
        observed_chars=163_443,
        limit_chars=150_000,
        provider="chatgpt-web",
    )

    action, final = ctl._handle_overflow(
        exc,
        SimpleNamespace(messages=[]),
        "chatgpt-web/web-gpt",
        model_window={"label": "chatgpt-web/web-gpt", "context": 262_144},
    )

    assert action == "end"
    assert final is not None and final.startswith("[文本入口超限]")
    assert "163443 chars" in final and "150000 chars" in final
    assert "262144 tokens" in final
    assert "不是由该 token 窗口直接触发" in final


def test_generic_provider_overflow_terminal_is_classified_as_context_window():
    eng: Any = _Engine()
    eng.state.overflow_reinject_count = 1
    ctl = TerminationController(eng)

    action, final = ctl._handle_overflow(
        LLMError("maximum context length exceeded"),
        SimpleNamespace(messages=[]),
        "model",
        model_window={"label": "model", "context": 8192},
    )

    assert action == "end"
    assert final is not None and final.startswith("[上下文窗口超限]")
    assert "窗口 8192" in final


def test_mandatory_request_envelope_overflow_has_explicit_cannot_fit_fact():
    eng: Any = _Engine()
    ctl = TerminationController(eng)
    exc = LLMRequestTooLargeError(
        "request_too_large",
        observed_chars=151_234,
        limit_chars=150_000,
        provider="chatgpt-web",
    )

    action, final = ctl._handle_overflow(
        exc,
        SimpleNamespace(messages=[]),
        "chatgpt-web/web-gpt",
        model_window={"label": "chatgpt-web/web-gpt", "context": 262_144},
        projection_mandatory_only=True,
    )

    assert action == "cannot_fit"
    assert final is not None and final.startswith("[文本入口超限]")
    assert "mandatory_projection_cannot_fit" in final
    assert "151234 chars" in final and "150000 chars" in final
