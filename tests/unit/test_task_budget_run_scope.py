"""I4-A offline intent reaches exact admitted Run and never sends FakeLLM.

No Web endpoint, scheduler, provider, factory or production task can issue
an OfflineBudgetIntent. These tests deliberately invoke the real LoopEngine
with its FakeLLM and isolated tmp_path stores.
"""

from __future__ import annotations

import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from llm_loop.core.run_context import current_run_generation, current_session_id
from llm_loop.core.trace_leak.ingress_token import delegate_ingress, issue_ingress
from llm_loop.llm.client import LLMResponse
from llm_loop.resources.task_budget_dispatch import active_task_budget
from llm_loop.resources.task_budget_run_scope import (
    OfflineBudgetIntent,
    bind_offline_budget_intent,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore


def _intent(
    engine: Any, sid: str, tmp_path: Path, *,
    deadline: float | None = None,
    workspace: str | None = None,
) -> OfflineBudgetIntent:
    root = engine.workspace_root or ""
    return OfflineBudgetIntent(
        store=TaskBudgetStore(tmp_path / "budget-store"),
        session_id=sid,
        workspace_scope=workspace or exact_workspace_scope(root),
        deadline_epoch_s=deadline or (time.time() + 30),
    )


def test_default_off_runs_real_fake_provider_with_no_budget_root(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine([
        LLMResponse(content="ordinary", tool_calls=[], provider="fake")
    ])
    sid = engine.session.create()
    result = engine.run(sid, "hi", ingress=issue_ingress("web"))
    assert result.final_answer == "ordinary"
    assert len(fake.calls) == 1
    assert not (tmp_path / "budget-store").exists()
    assert active_task_budget() is None


def test_exact_offline_web_grant_blocks_fake_provider_before_any_call(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine([
        LLMResponse(content="should-not-send", tool_calls=[], provider="fake")
    ])
    sid = engine.session.create()
    intent = _intent(engine, sid, tmp_path)
    with bind_offline_budget_intent(intent):
        try:
            engine.run(sid, "pytest pytest pytest", ingress=issue_ingress("web"))
        except TaskBudgetDeniedError as exc:
            assert exc.reason == "provider_adapter_unqualified"
    assert len(fake.calls) == 0
    assert active_task_budget() is None
    assert current_session_id.get() == ""
    assert current_run_generation.get() == ""
    budget_files = list(intent.store.directory.glob("budget-*.json"))
    assert len(budget_files) == 1
    import json

    state = json.loads(budget_files[0].read_text())
    assert state["phase"] == "active"
    assert state["grant"]["limits"]["physical_attempts"] == 0
    assert state["grant"]["limits"]["tool_invocations"] == 0
    assert len(state["members"]) == 1
    assert state["reservations"] == {}


@pytest.mark.parametrize("ingress", [None, "web", "forged", "delegate"])
def test_invalid_or_delegated_ingress_denied_before_root_creation(
    build_test_engine: Any, tmp_path: Path, ingress: Any,
) -> None:
    engine, fake = build_test_engine(["would call fake"])
    sid = engine.session.create()
    if ingress == "delegate":
        ingress = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    intent = _intent(engine, sid, tmp_path)
    with bind_offline_budget_intent(intent), pytest.raises(
        TaskBudgetDeniedError, match="no_authorized_human_ingress"
    ):
        engine.run(sid, "hi", ingress=ingress)
    assert len(fake.calls) == 0
    assert not list(intent.store.directory.glob("budget-*.json"))


def test_different_session_cannot_borrow_explicit_intent(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine(["not called"])
    actual_sid = engine.session.create()
    other_sid = engine.session.create()
    intent = _intent(engine, other_sid, tmp_path)
    with bind_offline_budget_intent(intent), pytest.raises(
        TaskBudgetDeniedError, match="offline_budget_scope_mismatch"
    ):
        engine.run(actual_sid, "hi", ingress=issue_ingress("web"))
    assert not fake.calls
    assert not list(intent.store.directory.glob("budget-*.json"))


def test_workspace_mismatch_and_deadline_fail_before_provider(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine(["not called"])
    sid = engine.session.create()
    forged = _intent(engine, sid, tmp_path, workspace="ws-incorrect")
    with bind_offline_budget_intent(forged), pytest.raises(
        TaskBudgetDeniedError, match="offline_budget_scope_mismatch"
    ):
        engine.run(sid, "hi", ingress=issue_ingress("web"))
    expired = _intent(engine, sid, tmp_path, deadline=time.time() - 3)
    with bind_offline_budget_intent(expired), pytest.raises(
        TaskBudgetDeniedError, match="offline_budget_deadline_expired"
    ):
        engine.run(sid, "hi", ingress=issue_ingress("web"))
    assert not fake.calls
    assert not list(expired.store.directory.glob("budget-*.json"))


def test_explicit_intent_is_reset_on_exit_not_inherited_by_later_user_turn(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine([
        LLMResponse(content="normal later turn", tool_calls=[], provider="fake")
    ])
    sid = engine.session.create()
    intent = _intent(engine, sid, tmp_path)
    with bind_offline_budget_intent(intent), suppress(TaskBudgetDeniedError):
        engine.run(sid, "hi", ingress=issue_ingress("web"))
    later = engine.run(sid, "hi again", ingress=issue_ingress("web"))
    assert later.final_answer == "normal later turn"
    assert len(fake.calls) == 1
