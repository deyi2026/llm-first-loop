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
from llm_loop.resources.task_budget_dispatch import (
    active_task_budget,
    bind_task_budget,
    cancel_active_task_budget,
    register_active_task_budget,
    unregister_active_task_budget,
)
from llm_loop.resources.task_budget_run_scope import (
    OfflineBudgetIntent,
    bind_offline_budget_intent,
    exact_workspace_scope,
    prepare_offline_run_budget,
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
    assert state["phase"] == "stop_requested"
    assert state["stop_reason"] == "run_ended"
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


def test_runner_exact_stop_propagates_into_durable_budget_root(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    from llm_loop.core.loop.runner import BackgroundRunner

    engine, fake = build_test_engine(["should never call provider"])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    intent = _intent(engine, sid, tmp_path)
    actual = prepare_offline_run_budget

    def stop_before_budget_registration(**kwargs: Any):
        execution = actual(**kwargs)
        assert runner.is_sync_active(sid)
        assert runner.cancel(sid) is True  # accepted before active budget register
        assert runner.is_cancelled(sid) is True
        return execution

    # RunEntrypoint imports this exact function after acquiring its Session lease.
    from unittest.mock import patch

    from llm_loop.resources import task_budget_run_scope

    with patch.object(
        task_budget_run_scope, "prepare_offline_run_budget",
        side_effect=stop_before_budget_registration,
    ), bind_offline_budget_intent(intent), suppress(TaskBudgetDeniedError):
        engine.run(sid, "offline accepted-stop window", ingress=issue_ingress("web"))

    import json

    files = list(intent.store.directory.glob("budget-*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["phase"] == "stop_requested"
    assert record["stop_reason"] == "user_stop"
    assert fake.calls == []
    assert runner.is_cancelled(sid) is False  # run finally cleanup


def test_budget_stop_registry_requires_exact_session_and_run_and_unregisters(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    intent = _intent(engine, sid, tmp_path)
    with bind_offline_budget_intent(intent):
        execution = prepare_offline_run_budget(
            session_id=sid, workspace_root=engine.workspace_root or "",
            run_generation="manual-run-1", ingress=issue_ingress("web"),
        )
    assert execution is not None
    register_active_task_budget(execution)
    try:
        assert cancel_active_task_budget(sid, "manual-run-2", reason="user_stop") is False
        assert cancel_active_task_budget("other-session", "manual-run-1", reason="user_stop") is False
        assert execution.store.read(execution.budget_id)["phase"] == "active"
        assert cancel_active_task_budget(sid, "manual-run-1", reason="user_stop") is True
        assert execution.store.read(execution.budget_id)["phase"] == "stop_requested"
        with pytest.raises(
            TaskBudgetDeniedError, match="local_run_stop_requested"
        ), bind_task_budget(execution):
            pass
        with bind_task_budget(execution, cleanup_scope=True):
            assert active_task_budget() is execution
            with pytest.raises(TaskBudgetDeniedError, match="local_run_stop_requested"):
                execution._get_validated()
    finally:
        unregister_active_task_budget(execution)
    assert cancel_active_task_budget(sid, "manual-run-1", reason="user_stop") is False


def test_cancel_store_uncertainty_still_blocks_same_run_locally(
    build_test_engine: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    intent = _intent(engine, sid, tmp_path)
    with bind_offline_budget_intent(intent):
        execution = prepare_offline_run_budget(
            session_id=sid, workspace_root=engine.workspace_root or "",
            run_generation="manual-run-3", ingress=issue_ingress("web"),
        )
    assert execution is not None
    register_active_task_budget(execution)
    monkeypatch.setattr(
        execution.store, "request_stop",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected persistence loss")),
    )
    try:
        with pytest.raises(OSError, match="injected persistence loss"):
            cancel_active_task_budget(sid, "manual-run-3", reason="user_stop")
        # Durable phase may still read ACTIVE, but the bound instance refuses
        # provider/tool work; no false claim that the remote has stopped.
        assert execution.store.read(execution.budget_id)["phase"] == "active"
        with pytest.raises(
            TaskBudgetDeniedError, match="local_run_stop_requested"
        ), bind_task_budget(execution):
            pass
    finally:
        unregister_active_task_budget(execution)


def test_run_terminal_seals_stale_worker_budget_and_cleans_registry(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    from unittest.mock import patch

    from llm_loop.resources import task_budget_dispatch

    engine, fake = build_test_engine(["would be unmetered"])
    sid = engine.session.create()
    intent = _intent(engine, sid, tmp_path)
    captured: list[Any] = []
    original_register = task_budget_dispatch.register_active_task_budget

    def capture_and_register(execution: Any) -> None:
        captured.append(execution)
        original_register(execution)

    with (
        patch.object(
            task_budget_dispatch, "register_active_task_budget",
            side_effect=capture_and_register,
        ),
        bind_offline_budget_intent(intent),
        suppress(TaskBudgetDeniedError),
    ):
        engine.run(sid, "offline task ending", ingress=issue_ingress("web"))

    assert len(captured) == 1
    execution = captured[0]
    assert execution.store.read(execution.budget_id)["phase"] == "stop_requested"
    assert execution.store.read(execution.budget_id)["stop_reason"] == "run_ended"
    assert cancel_active_task_budget(
        sid, execution.member.run_generation, reason="user_stop"
    ) is False
    with pytest.raises(
        TaskBudgetDeniedError, match="local_run_stop_requested"
    ), bind_task_budget(execution):
        pass
    assert not fake.calls
