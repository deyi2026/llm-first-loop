"""Task browser mutation must not treat model scope_ref as a Host app identity."""

from __future__ import annotations

from llm_loop.core.run_context import current_task_execution
from tests.unit.test_smc_browser_action_v01 import (
    FIXTURES,
    _click_action,
    _stack,
)


def test_task_browser_requires_host_cdp_process_binding_before_any_dispatch(tmp_path):
    perception, receipts, backend, actuator, action = _stack(
        tmp_path,
        [FIXTURES["base"]],
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    command = _click_action(first, action_id="task-action")
    # Even a model-invented bundle-looking scope_ref cannot mint app authority.
    command["scope_ref"] = "com.google.Chrome"
    token = current_task_execution.set(object())
    try:
        receipt = action.execute("s1", command)
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_browser_host_binding_unavailable"
    assert len(receipts.list_action("s1", "task-action")) == 1
    assert backend.calls == 0
    assert actuator.calls == []


def test_legacy_browser_action_keeps_existing_dispatch_contract(tmp_path):
    perception, _receipts, backend, actuator, action = _stack(
        tmp_path,
        [FIXTURES["base"]],
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    assert current_task_execution.get() is None
    receipt = action.execute("s1", _click_action(first, action_id="legacy-action"))
    assert receipt["status"] == "ok"
    assert backend.calls == 2
    assert len(actuator.calls) == 1
