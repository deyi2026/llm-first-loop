from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from llm_loop.core.loop.engine_services.termination_controller import TerminationController
from llm_loop.llm.errors import LLMError


class _Engine:
    def __init__(self):
        self._run_state().overflow_reinject_count = 0
        self._run_state().current_turn_ref = 9
        self._run_state().last_breakdown = None

    def _current_context_limit(self, model_used):  # noqa: ARG002
        return 1000


def test_overflow_reinject_is_current_turn_only():
    eng: Any = _Engine()
    ctl = TerminationController(eng)
    sess = SimpleNamespace(messages=[])
    action, final = ctl._handle_overflow(
        LLMError("maximum context length exceeded"), sess, "model"
    )
    assert action == "reinject" and final is None
    assert len(sess.messages) == 1
    md = sess.messages[0].metadata
    assert md.get("injection_kind") == "overflow_feedback"
    assert md.get("prompt_lifecycle") == "current_turn"
    assert md.get("turn_ref") == 9
