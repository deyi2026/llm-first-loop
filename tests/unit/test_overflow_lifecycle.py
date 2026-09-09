from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from llm_loop.core.loop.engine_services.termination_controller import TerminationController
from llm_loop.llm.errors import LLMError


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
    action, final = ctl._handle_overflow(LLMError("maximum context length exceeded"), sess, "model")
    assert action == "reinject" and final is None
    assert sess.messages == []
    assert eng.state.overflow_reinject_count == 1
    assert eng._overflow_shrink_factor is not None
    assert any(a[:2] == ("overflow.compact", "budget_shrunk") for a in eng.actions)
