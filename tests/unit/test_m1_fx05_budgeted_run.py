"""Offline tests of M1's actual CAS pre-send reservation extension.

Never makes an API call and never reopens the historical M1 budget root.
"""

from __future__ import annotations

import importlib.util
import time
import uuid
from pathlib import Path

import pytest

from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore


def _runner_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "m1_fx05_budgeted_run.py"
    spec = importlib.util.spec_from_file_location("m1_fx05_budgeted_run", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _budget(tmp_path: Path, module):
    root_id = "m1fx05-" + uuid.uuid4().hex
    workspace = exact_workspace_scope(str(tmp_path))
    grant = TaskBudgetGrant(
        budget_id=root_id,
        issuer="test-owner",
        authority_source="test-authority",
        workspace_scope=workspace,
        session_id="fx05-test",
        human_turn_ref="authorized-test",
        surface="cli-test_harness",
        profile=module.PROFILE,
        policy_version="m1-t1-budgeted-cli-v2",
        deadline_epoch_s=time.time() + 120,
        limits=TaskBudgetLimits(
            physical_attempts=2,
            tool_invocations=2,
            input_tokens=100_000,
            output_tokens=10_000,
            payload_bytes=5_000,
        ),
        capabilities=TaskBudgetCapabilities(
            allowed_tools=frozenset({"read_file", "edit_file"}),
        ),
    )
    store = TaskBudgetStore(tmp_path / "budgets")
    row = store.issue_root(grant, root_run_generation="test-generation", ingress_kind="cli")
    row = store.activate(root_id, expected_revision=row["revision"])
    execution = module.FX05BudgetExecution(
        store=store, budget_id=root_id,
        member=TaskBudgetMember.from_dict(row["members"][root_id]),
    )
    return execution


def test_unqualified_provider_send_fails_before_reservation(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    with pytest.raises(TaskBudgetDeniedError, match="m1_physical_send_without_bound_envelope"):
        budget.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    assert not budget.store.read(budget.budget_id)["reservations"]


def test_atomic_precharge_is_physical_dispatch_fact(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    token = module._PRE_SEND_ENVELOPE.set((3_000, 600, 1_100))
    try:
        rid = budget.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    finally:
        module._PRE_SEND_ENVELOPE.reset(token)
    row = budget.store.read(budget.budget_id)
    assert row["reservations"][rid]["phase"] == "dispatched"
    assert row["reservations"][rid]["allocations"] == {
        "input_tokens": 3_000,
        "output_tokens": 600,
        "payload_bytes": 1_100,
        "physical_attempts": 1,
    }
    with pytest.raises(TaskBudgetDeniedError, match="m1_physical_send_without_bound_envelope"):
        budget.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    assert len(budget.store.read(budget.budget_id)["reservations"]) == 1


def test_budget_ceiling_denies_pre_send(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    token = module._PRE_SEND_ENVELOPE.set((100_001, 500, 1_000))
    try:
        with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:input_tokens"):
            budget.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    finally:
        module._PRE_SEND_ENVELOPE.reset(token)
    assert not budget.store.read(budget.budget_id)["reservations"]


def test_tool_allowlist_and_persisted_stop_are_hard(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    with pytest.raises(TaskBudgetDeniedError, match="tool_not_allowed"):
        budget.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="execute_command")
    assert not budget.store.read(budget.budget_id)["reservations"]
    budget.request_stop(reason="owner_revoked")
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"
    token = module._PRE_SEND_ENVELOPE.set((1_000, 500, 1_000))
    try:
        with pytest.raises(TaskBudgetDeniedError):
            budget.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    finally:
        module._PRE_SEND_ENVELOPE.reset(token)
