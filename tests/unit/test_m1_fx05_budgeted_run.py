"""Offline tests of M1's actual CAS pre-send reservation extension.

Never makes an API call and never reopens the historical M1 budget root.
"""

from __future__ import annotations

import importlib.util
import json
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import bind_task_budget, exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore


def _runner_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "m1_fx05_budgeted_run.py"
    spec = importlib.util.spec_from_file_location("m1_fx05_budgeted_run", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ATTEMPT_ID = "pattempt:" + "0123456789abcdef" * 2


def _seed_event_store(
    tmp_path: Path,
    *,
    attempt_id: str = ATTEMPT_ID,
    session_id: str = "fx05-test",
    generation: str = "test-generation",
    opened_generation: str | None = None,
    input: int = 1500,
    output: int = 40,
    cached: int = 0,
    settled_count: int = 1,
    projected_bytes: int = 1000,
    max_tokens: int = 128,
    usage: dict | None = None,
    attrs: dict | None = None,
):
    """Real EventStore seeded with synthetic call/transport events.

    Mirrors the exact payload shapes the production settlement journal
    writes (call.opened + transport.opened with prepared controls +
    transport.settled with usage), so settle()/verifier exercise the real
    join code path; reserved is rebuilt from the transport.opened event.
    """
    from llm_loop.event_log.store import EventStore

    store = EventStore(tmp_path / "event_logs")
    call_id = "pcall:" + uuid.uuid4().hex
    store.append(
        session_id,
        "provider.call.opened",
        {
            "call_id": call_id,
            "origin_run_generation": (
                opened_generation if opened_generation is not None else generation
            ),
        },
    )
    store.append(
        session_id,
        "provider.transport.opened",
        {
            "call_id": call_id,
            "attempt_id": attempt_id,
            "provider_id": "glm",
            "model_id": "glm-5.3",
            "prepared": {
                "projected_bytes": projected_bytes,
                "controls": {"max_tokens": max_tokens},
            },
        },
    )
    event_ids: list[str | None] = []
    for _ in range(settled_count):
        payload = {
            "call_id": call_id,
            "attempt_id": attempt_id,
            "provider_id": "glm",
            "model_id": "glm-5.3",
            "outcome": "success",
            "usage_observations": 1,
            "status_code": 200,
            "usage": usage
            if usage is not None
            else {
                "input_tokens": input,
                "output_tokens": output,
                "cached_input_tokens": cached,
            },
        }
        if attrs:
            payload.update(attrs)
        event = store.append(session_id, "provider.transport.settled", payload)
        event_ids.append(event.event_id if event else None)
    return store, event_ids


def _observed_snapshot(
    attempt_id: str = ATTEMPT_ID,
    *,
    input: int = 1500,
    output: int = 40,
    cached: int = 0,
) -> dict:
    return {
        "attempt_id": attempt_id,
        "input": input,
        "output": output,
        "cached_input": cached,
        "provider_event_ref": "",
        "conflict": False,
    }


def _budget(tmp_path: Path, module, *, event_store=None):
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
        policy_version="m1-t1-budgeted-cli-v3",
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
        event_store=event_store,
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


def test_provider_transport_requires_an_explicit_budget_binding() -> None:
    module = _runner_module()
    from llm_loop.llm.client import LLMClient

    original_transport = LLMClient._transport_attempt_scope
    original_usage = LLMClient._observe_transport_usage
    counters = module._install_fail_closed_transport_guard()
    guarded = LLMClient._transport_attempt_scope
    LLMClient._transport_attempt_scope = original_transport
    LLMClient._observe_transport_usage = original_usage
    client = LLMClient(
        api_key="test-only",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3",
        provider="glm",
        max_tokens=128,
        trust_env=False,
    )
    try:
        with pytest.raises(TaskBudgetDeniedError, match="m1_explicit_budget_binding_required"), guarded(
            client,
            model_id="glm-5.3",
            target_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            prepared={"projected_bytes": 1000, "controls": {"max_tokens": 128}},
        ):
            pytest.fail("unbound provider transport reached dispatch")
        assert counters["attempts"] == 0
    finally:
        client.close()


def test_provider_usage_missing_fails_closed_after_one_unknown_reservation(
    tmp_path: Path,
) -> None:
    module = _runner_module()
    from llm_loop.llm.client import LLMClient
    from llm_loop.resources.task_budget_dispatch import bind_task_budget

    budget = _budget(tmp_path, module)
    original_transport = LLMClient._transport_attempt_scope
    original_usage = LLMClient._observe_transport_usage
    counters = module._install_fail_closed_transport_guard()
    guarded = LLMClient._transport_attempt_scope
    LLMClient._transport_attempt_scope = original_transport
    LLMClient._observe_transport_usage = original_usage
    client = LLMClient(
        api_key="test-only",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3",
        provider="glm",
        max_tokens=128,
        trust_env=False,
    )
    try:
        with bind_task_budget(budget), pytest.raises(
            TaskBudgetDeniedError, match="m1_provider_usage_missing"
        ), guarded(
            client,
            model_id="glm-5.3",
            target_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            prepared={"projected_bytes": 1000, "controls": {"max_tokens": 128}},
        ):
            pass  # Simulate a response without a complete usage receipt.
        row = budget.store.read(budget.budget_id)
        assert counters["attempts"] == 1
        assert counters["usage_reports"] == 0
        assert len(row["reservations"]) == 1
        reservation = next(iter(row["reservations"].values()))
        assert reservation["kind"] == "physical_attempts"
        assert reservation["phase"] == "unknown"
        assert reservation["allocations"]["input_tokens"] == 10_000
        # v3: a missing usage receipt must also latch a durable stop (no
        # refund, no further physical attempt), not merely stay "active".
        assert row["phase"] == "stop_requested"
        # A further transport attempt is denied on the stopped root: even
        # rebinding the execution raises local_run_stop_requested.
        with pytest.raises(TaskBudgetDeniedError), bind_task_budget(budget), guarded(
            client,
            model_id="glm-5.3",
            target_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            prepared={"projected_bytes": 1000, "controls": {"max_tokens": 128}},
        ):
            pytest.fail("stopped root admitted a further provider attempt")
    finally:
        client.close()


def _guarded_client(module, attempt_id: str = ATTEMPT_ID):
    """Install the guard, restore class attributes, return (client, guarded, guard_usage, counters).

    The client carries a minimal active-transport capture stub exactly where
    the production ShadowTransportRecorder exposes it
    (``transport_observer._active_transport`` -> ``capture.attempt.attempt_id``),
    so the patched on_usage binds the REAL provider transport attempt id
    instead of a local round ordinal.
    """
    from llm_loop.llm.client import LLMClient

    original_transport = LLMClient._transport_attempt_scope
    original_usage = LLMClient._observe_transport_usage
    counters = module._install_fail_closed_transport_guard()
    guarded = LLMClient._transport_attempt_scope
    guard_usage = LLMClient._observe_transport_usage
    LLMClient._transport_attempt_scope = original_transport
    LLMClient._observe_transport_usage = original_usage
    client = LLMClient(
        api_key="test-only",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3",
        provider="glm",
        max_tokens=128,
        trust_env=False,
    )
    capture_var = ContextVar("test_active_transport")
    capture_var.set(SimpleNamespace(attempt=SimpleNamespace(attempt_id=attempt_id)))
    client.transport_observer = SimpleNamespace(_active_transport=capture_var)
    return client, guarded, guard_usage, counters


def _qualified_transport_call(guarded, client):
    return guarded(
        client,
        model_id="glm-5.3",
        target_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        prepared={"projected_bytes": 1000, "controls": {"max_tokens": 128}},
    )


def test_successful_attempt_settles_with_actual_measures_receipt(tmp_path: Path) -> None:
    """Task B positive path: I2 unknown liability reconciled to settled/success.

    v3.2: the EventStore ``provider.transport.settled`` event is the ONLY
    durable usage authority. receipt_ref is
    ``m1fx05ev:<event_id>:<sha256(canonical)[:16]>`` where the canonical
    digest input is {attempt_id, provider_event_ref:"", observed, reserved
    precharge}. The CAS settlement atomically rewrites the allocations to
    the observed measures and preserves the precharge under
    ``reserved_precharge``; report() reflects real usage with cached input
    included in prompt_tokens and never deducted. No sidecar receipt file
    is written anywhere.
    """
    import hashlib

    module = _runner_module()
    es, [event_id] = _seed_event_store(tmp_path, cached=300)
    budget = _budget(tmp_path, module, event_store=es)
    client, guarded, guard_usage, counters = _guarded_client(module)
    try:
        with bind_task_budget(budget), _qualified_transport_call(guarded, client):
            guard_usage(
                client,
                {
                    "prompt_tokens": 1500,
                    "completion_tokens": 40,
                    "prompt_tokens_details": {"cached_tokens": 300},
                },
                model_id="glm-5.3",
            )
        row = budget.store.read(budget.budget_id)
        assert counters["attempts"] == 1
        assert counters["usage_reports"] == 1
        assert len(row["reservations"]) == 1
        reservation = next(iter(row["reservations"].values()))
        assert reservation["phase"] == "settled"
        assert reservation["outcome"] == "success"
        digest = hashlib.sha256(
            json.dumps(
                {
                    "attempt_id": ATTEMPT_ID,
                    "provider_event_ref": "",
                    "observed": {"input": 1500, "output": 40, "cached_input": 300},
                    "reserved": {
                        "input_tokens": 10_000,
                        "output_tokens": 128,
                        "payload_bytes": 1000,
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[: module.USAGE_DIGEST_HEX]
        assert reservation["receipt_ref"] == f"m1fx05ev:{event_id}:{digest}"
        # Settlement rewrites the reservation allocations to the observed
        # measures (payload_bytes stays the prepared canonical request size);
        # the original precharge stays in the FX05-local envelope map (the
        # shared store schema is untouched) and is what the digest hashed.
        assert reservation["allocations"] == {
            "input_tokens": 1500,
            "output_tokens": 40,
            "payload_bytes": 1000,
            "physical_attempts": 1,
        }
        rid = next(iter(row["reservations"]))
        assert budget._m1_envelopes[rid] == (10_000, 128, 1000)
        report = budget.store.report(budget.budget_id)
        assert report["used_or_reserved"]["input_tokens"] == 1500
        assert report["used_or_reserved"]["output_tokens"] == 40
        assert report["used_or_reserved"]["payload_bytes"] == 1000
        # Cached input (300) is included in prompt_tokens (1500), never
        # deducted: 1500, not 1200.
        assert row["phase"] == "active"
        # v3.2: NO second persistent usage ledger exists anywhere.
        assert not list(tmp_path.rglob("*usage-receipts*"))
    finally:
        client.close()


def test_usage_exceeding_precharge_stays_unknown_and_stops(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    client, guarded, guard_usage, counters = _guarded_client(module)
    try:
        with bind_task_budget(budget), pytest.raises(
            TaskBudgetDeniedError, match="m1_provider_usage_exceeded_reserved_proxy"
        ), _qualified_transport_call(guarded, client):
            guard_usage(
                client,
                {"prompt_tokens": 10_001, "completion_tokens": 40},
                model_id="glm-5.3",
            )
        row = budget.store.read(budget.budget_id)
        reservation = next(iter(row["reservations"].values()))
        assert reservation["phase"] == "unknown"
        # UNKNOWN keeps the original precharge allocations (no refund); the
        # store report still shows the precharge, not any observed figure.
        assert reservation["allocations"]["input_tokens"] == 10_000
        assert (
            budget.store.report(budget.budget_id)["used_or_reserved"]["input_tokens"]
            == 10_000
        )
        # v3.2: no sidecar usage receipt exists — the only durable usage
        # authority is the EventStore (not seeded here: the over-precharge
        # failure happens before the EventStore join).
        assert not list(tmp_path.rglob("*usage-receipts*"))
        # The I2 default dispatch receipt is written, never a reconciled
        # m1fx05 receipt_ref in the store.
        assert reservation["receipt_ref"].startswith("dispatch-receipt-")
        assert row["phase"] == "stop_requested"
        # usage_reports advanced before the raise, so the attempts !=
        # usage_reports gate would pass; the durable stop must deny instead.
        assert counters["attempts"] == 1
        assert counters["usage_reports"] == 1
        with pytest.raises(TaskBudgetDeniedError), bind_task_budget(budget), _qualified_transport_call(
            guarded, client
        ):
            pytest.fail("exceeded root admitted a further provider attempt")
    finally:
        client.close()


def test_conflicting_repeated_usage_and_duplicate_settle_fail_closed(
    tmp_path: Path,
) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    client, guarded, guard_usage, counters = _guarded_client(module)
    try:
        with bind_task_budget(budget), _qualified_transport_call(guarded, client):
            guard_usage(
                client,
                {"prompt_tokens": 1500, "completion_tokens": 40},
                model_id="glm-5.3",
            )
            # Same attempt reports a different input figure: unreconcilable.
            guard_usage(
                client,
                {"prompt_tokens": 1600, "completion_tokens": 40},
                model_id="glm-5.3",
            )
        row = budget.store.read(budget.budget_id)
        reservation = next(iter(row["reservations"].values()))
        assert reservation["phase"] == "unknown"
        assert row["phase"] == "stop_requested"
        # The unreconciled UNKNOWN liability cannot be upgraded afterwards:
        # replaying settle with complete=True is denied (only dispatched work
        # can be settled), and the store treats an identical replay as a
        # no-op rather than a new settlement.
        rid = next(iter(row["reservations"]))
        with pytest.raises(TaskBudgetDeniedError):
            budget.settle(rid, outcome="success", complete=True)
        budget.settle(rid, outcome="success", complete=False)  # idempotent no-op
        assert budget.store.read(budget.budget_id)["reservations"][rid]["phase"] == "unknown"
        assert counters["usage_reports"] == 1
    finally:
        client.close()


def test_provider_timeout_keeps_unknown_and_blocks_next_attempt(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    client, guarded, guard_usage, counters = _guarded_client(module)
    try:
        with bind_task_budget(budget), pytest.raises(TimeoutError), _qualified_transport_call(
            guarded, client
        ):
            raise TimeoutError("simulated provider timeout before any usage")
        row = budget.store.read(budget.budget_id)
        reservation = next(iter(row["reservations"].values()))
        assert reservation["phase"] == "unknown"
        assert reservation["outcome"] == "failure"
        assert counters["attempts"] == 1
        assert counters["usage_reports"] == 0
        # Unknown liability from the timed-out attempt blocks the next send.
        with bind_task_budget(budget), pytest.raises(
            TaskBudgetDeniedError, match="m1_previous_provider_usage_unknown"
        ), _qualified_transport_call(guarded, client):
            pytest.fail("unknown-liability root admitted a further provider attempt")
        assert len(budget.store.read(budget.budget_id)["reservations"]) == 1
    finally:
        client.close()


def test_four_attempt_precharge_fits_model_ceiling() -> None:
    """Task A/C arithmetic: 4 rounds * proxy(88k in + 3k out) = 364k <= 400k."""
    module = _runner_module()
    assert module.ATTEMPTS == 4
    assert module.MAX_JSON_BYTES == 40_000
    assert module.MAX_OUTPUT_TOKENS == 3_000
    per_attempt_input = 2 * module.MAX_JSON_BYTES + module.INPUT_PROXY_CONST
    assert per_attempt_input == 88_000
    assert module.ATTEMPTS * per_attempt_input <= module.MODEL_TOTAL_TOKEN_CEILING
    assert (
        module.ATTEMPTS * (per_attempt_input + module.MAX_OUTPUT_TOKENS)
        == 364_000
        <= module.MODEL_TOTAL_TOKEN_CEILING
        == 400_000
    )


def _manual_dispatch(module, budget, envelope=(10_000, 128, 1000)):
    """Reserve one physical dispatch with a hand-set pre-send envelope."""
    token = module._PRE_SEND_ENVELOPE.set(tuple(envelope))
    try:
        rid = budget.reserve(module.BudgetDimension.PHYSICAL_ATTEMPTS)
    finally:
        module._PRE_SEND_ENVELOPE.reset(token)
    return rid


def test_envelope_ledger_drift_fails_closed(tmp_path: Path) -> None:
    # The reconciliation envelope must come from the authoritative store
    # record; a drifted local cache may never authorize a settlement.
    module = _runner_module()
    budget = _budget(tmp_path, module)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = {
        "attempt_id": "ptx:01TESTMANUAL0000000000000000",
        "input": 1500,
        "output": 40,
        "cached_input": 300,
        "provider_event_ref": "chatcmpl-drift-1",
        "conflict": False,
    }
    budget._m1_envelopes[rid] = (11_111, 222, 999)  # drifted local cache
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 10_000  # no refund
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")  # durable stop gate


def test_ownership_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reservation whose authoritative record belongs to another member (or
    # run_generation) must never be upgraded authoritatively, even with a
    # matching envelope and a valid observed snapshot.
    module = _runner_module()
    budget = _budget(tmp_path, module)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = {
        "attempt_id": "ptx:01TESTMANUAL0000000000000000",
        "input": 1500,
        "output": 40,
        "cached_input": 0,
        "provider_event_ref": "",
        "conflict": False,
    }
    real_read = budget.store.read

    def forged_read(budget_id):
        row = dict(real_read(budget_id))
        row["reservations"] = dict(row["reservations"])
        row["reservations"][rid] = dict(row["reservations"][rid])
        row["reservations"][rid]["member_id"] = "rogue-member-id"
        return row

    monkeypatch.setattr(budget.store, "read", forged_read)
    budget.settle(rid, outcome="success", complete=False)
    monkeypatch.undo()
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"  # never upgraded authoritatively
    assert reservation["allocations"]["input_tokens"] == 10_000  # no refund
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")


def test_observed_invalid_negative_or_cache_over_input_fails_closed(
    tmp_path: Path,
) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = {
        "attempt_id": "ptx:01TESTMANUAL0000000000000000",
        "input": 1500,
        "output": 40,
        "cached_input": 9_999,  # cached > input: impossible observation
        "provider_event_ref": "",
        "conflict": False,
    }
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")

    # Negative observed measures are equally invalid (separate budget root).
    budget2 = _budget(tmp_path, module)
    rid2 = _manual_dispatch(module, budget2)
    budget2._m1_observed[rid2] = {
        "attempt_id": "ptx:01TESTMANUAL0000000000000000",
        "input": -5,
        "output": 40,
        "cached_input": 0,
        "provider_event_ref": "",
        "conflict": False,
    }
    budget2.settle(rid2, outcome="success", complete=False)
    assert (
        budget2.store.read(budget2.budget_id)["reservations"][rid2]["phase"]
        == "unknown"
    )
    # v3.2: both failures latch a durable stop and write no receipt file.
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")


def test_settle_replay_is_idempotent_and_keeps_single_history_line(
    tmp_path: Path,
) -> None:
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    client, guarded, guard_usage, counters = _guarded_client(module)
    try:
        with bind_task_budget(budget), _qualified_transport_call(guarded, client):
            guard_usage(
                client,
                {"prompt_tokens": 1500, "completion_tokens": 40},
                model_id="glm-5.3",
            )
        rid = next(iter(budget.store.read(budget.budget_id)["reservations"]))
        first = budget.store.read(budget.budget_id)
        # Replay the terminal settlement: same receipt_ref is an idempotent
        # no-op in the CAS store (replay re-joins the same EventStore event
        # and recomputes the identical evidence-bound receipt_ref).
        budget.settle(rid, outcome="success", complete=False)
        second = budget.store.read(budget.budget_id)
        assert second["reservations"][rid]["phase"] == "settled"
        assert (
            second["reservations"][rid]["receipt_ref"]
            == first["reservations"][rid]["receipt_ref"]
        )
        assert second["revision"] == first["revision"]  # same CAS snapshot
        # v3.2: no sidecar receipt ledger exists to duplicate.
        assert not list(tmp_path.rglob("*usage-receipts*"))
    finally:
        client.close()


def test_stop_latch_blocks_provider_and_tool_together(tmp_path: Path) -> None:
    module = _runner_module()
    budget = _budget(tmp_path, module)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = {
        "attempt_id": "ptx:01TESTMANUAL0000000000000000",
        "input": 20_000,  # exceeds the 10_000 reserved input
        "output": 40,
        "cached_input": 0,
        "provider_event_ref": "",
        "conflict": False,
    }
    budget.settle(rid, outcome="success", complete=False)
    assert (
        budget.store.read(budget.budget_id)["reservations"][rid]["phase"]
        == "unknown"
    )
    # Provider side: a new physical dispatch must be refused outright.
    with pytest.raises(TaskBudgetDeniedError):
        _manual_dispatch(module, budget)
    # Tool side: the persisted stop must refuse allowed tools too.
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")


def test_settle_without_event_store_fails_closed(tmp_path: Path) -> None:
    """v3.2: no EventStore means no settlement — the usage authority is gone.

    The former sidecar sink (and its unwritable-path failure mode) is
    removed entirely: there is no second persistent ledger. Without an
    EventStore to join, the observed usage cannot be verified against the
    durable authority, so the reservation stays UNKNOWN, the root latches
    a durable stop, and no receipt file is created anywhere.
    """
    module = _runner_module()
    budget = _budget(tmp_path, module)  # no event_store bound
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"  # settlement not claimed
    assert reservation["allocations"]["input_tokens"] == 10_000  # precharge kept
    assert reservation["receipt_ref"].startswith("dispatch-receipt-")
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"
    assert not list(tmp_path.rglob("*usage-receipts*"))
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")


def test_refuse_overwrite_prior_fx05_target(tmp_path: Path) -> None:
    module = _runner_module()
    (tmp_path / "prior-draft.md").write_text("# prior FX05 draft (2026-11-27)\n")
    # The historical draft path is never writable under --execute, even with
    # an attestation; the guard fires before any disk read.
    with pytest.raises(TaskBudgetDeniedError, match="m1_refuse_overwrite"):
        module._refuse_existing_target(
            tmp_path, module.TARGET_PATH, execute=True, prepared_target_sha256="x"
        )
    # An existing non-historical target without an attestation is refused.
    with pytest.raises(TaskBudgetDeniedError, match="m1_target_requires_prepared"):
        module._refuse_existing_target(tmp_path, "prior-draft.md", execute=True)
    # A mismatched attestation is refused.
    with pytest.raises(TaskBudgetDeniedError, match="m1_target_sha_mismatch"):
        module._refuse_existing_target(
            tmp_path, "prior-draft.md", execute=True, prepared_target_sha256="00"
        )
    # A missing target cannot be executed (read_file->edit_file needs it).
    with pytest.raises(TaskBudgetDeniedError, match="m1_execute_requires_prepared"):
        module._refuse_existing_target(
            tmp_path, "brand-new-draft.md", execute=True, prepared_target_sha256="00"
        )
    # The only admissible execute path: fresh fixture + exact sha256 match.
    import hashlib as _hashlib

    sha = _hashlib.sha256((tmp_path / "prior-draft.md").read_bytes()).hexdigest()
    module._refuse_existing_target(
        tmp_path, "prior-draft.md", execute=True, prepared_target_sha256=sha
    )
    # Non-execute modes stay allowed regardless of attestation or history.
    module._refuse_existing_target(tmp_path, "prior-draft.md", execute=False)
    module._refuse_existing_target(tmp_path, module.TARGET_PATH, execute=False)


def test_ledger_alignment_classifies_tool_vs_physical_reservations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Alignment by reservation.kind: tool reservations close under dispatch
    receipts (no provider usage exists to join); physical reservations must
    join exactly one EventStore settled event with a recomputable digest.
    A missing event fails as ``missing``; no EventStore at all fails as
    ``unavailable`` (never a claim of completed reconciliation)."""
    module = _runner_module()
    es, [event_id] = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    rid_tool = budget.reserve(
        module.BudgetDimension.TOOL_INVOCATIONS, tool_id="read_file"
    )
    rid_phys = _manual_dispatch(module, budget)
    # Dispatch-layer closure for the tool reservation (no provider usage).
    rev = budget.store.read(budget.budget_id)["revision"]
    budget.store.mark_dispatched(budget.budget_id, rid_tool, expected_revision=rev)
    rev = budget.store.read(budget.budget_id)["revision"]
    budget.store.settle(
        budget.budget_id,
        rid_tool,
        expected_revision=rev,
        receipt_ref=f"dispatch-receipt-{rid_tool}",
        outcome="success",
        usage_complete=True,
    )
    # Physical reservation: settle through the real EventStore join path.
    budget._m1_observed[rid_phys] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid_phys, outcome="success", complete=False)
    assert budget.store.read(budget.budget_id)["reservations"][rid_phys][
        "phase"
    ] == "settled"
    assert module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"}
    assert per_res[rid_tool]["aligned"] is True
    assert per_res[rid_tool]["event_store_join"] == "not_required"
    assert per_res[rid_phys]["aligned"] is True
    assert per_res[rid_phys]["event_store_join"] == "joined"
    assert per_res[rid_phys]["attempt_id"] == ATTEMPT_ID
    assert per_res[rid_phys]["event_store_event_id"] == event_id
    assert [r for r in lines if r["event"] == "ledger_alignment"][0]["aligned"] is True

    # A settled physical reservation WITHOUT its EventStore event fails.
    rid2 = _manual_dispatch(module, budget)
    budget._m1_settle_with_actual_allocations(
        rid2,
        receipt_ref=(
            "m1fx05ev:00000000-0000-4000-8000-000000000000:0123456789abcdef"
        ),
        observed_input=900,
        observed_output=10,
        payload_bytes=1000,
    )
    assert not module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"}
    assert per_res[rid2]["aligned"] is False
    assert per_res[rid2]["event_store_join"] == "missing"
    assert [r for r in lines if r["event"] == "ledger_alignment"][0]["aligned"] is False

    # No EventStore at all: physical alignment is honestly "unavailable"
    # and FAILS — the reconciliation cannot be claimed complete.
    assert not module._verify_ledger_alignment(budget.store, budget.budget_id)
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"}
    assert per_res[rid_phys]["event_store_join"] == "unavailable"
    assert per_res[rid_phys]["aligned"] is False


def test_usage_without_real_provider_attempt_id_fails_closed(tmp_path: Path) -> None:
    """Cross-review fix 2: no local ordinal may impersonate an attempt id.

    When the transport observer exposes no active transport capture (journal
    disabled, scope exited, or id missing), on_usage must refuse settlement
    outright: the root fail-closes with the reservation kept as an UNKNOWN
    precharge liability and no receipt line may claim a settlement.
    """
    module = _runner_module()
    budget = _budget(tmp_path, module)
    client, guarded, guard_usage, counters = _guarded_client(module)
    # Simulate the observer with NO active capture, exactly as the production
    # recorder looks when no transport scope (or journal) is active.
    client.transport_observer = SimpleNamespace(
        _active_transport=ContextVar("test_no_active_transport", default=None)
    )
    try:
        with bind_task_budget(budget), pytest.raises(
            TaskBudgetDeniedError, match="m1_provider_attempt_id_unavailable"
        ), _qualified_transport_call(guarded, client):
            guard_usage(
                client,
                {"prompt_tokens": 1500, "completion_tokens": 40},
                model_id="glm-5.3",
            )
        row = budget.store.read(budget.budget_id)
        reservation = next(iter(row["reservations"].values()))
        assert reservation["phase"] == "unknown"
        assert reservation["allocations"]["input_tokens"] == 10_000  # precharge kept
        assert row["phase"] == "stop_requested"
        assert counters["attempts"] == 1
        assert counters["usage_reports"] == 0
        # No receipt line may exist: nothing was settled authoritatively.
        assert not (tmp_path / "usage-receipts.jsonl").exists()
        with pytest.raises(TaskBudgetDeniedError):
            budget.assert_tool_allowed("read_file")
    finally:
        client.close()


def test_actual_allocations_settlement_is_atomic_single_writer(tmp_path: Path) -> None:
    """Cross-review fix 1: the FX05-only CAS settlement rewrite semantics.

    One _m1_settle_with_actual_allocations call rewrites allocations to the
    observed measures and marks settled/success atomically; over-reservation
    actuals are denied against the authoritative row; changed evidence
    against a settled row is a conflict; an identical replay is an
    idempotent no-op (no revision bump); report() reflects real usage.
    """
    module = _runner_module()
    budget = _budget(tmp_path, module)
    rid = _manual_dispatch(module, budget)
    receipt_ref = "m1fx05u:ptx:01TESTCAS00000000000000000:0123456789abcdef"
    budget._m1_settle_with_actual_allocations(
        rid,
        receipt_ref=receipt_ref,
        observed_input=1500,
        observed_output=40,
        payload_bytes=1000,
    )
    entry = budget.store.read(budget.budget_id)["reservations"][rid]
    assert entry["phase"] == "settled"
    assert entry["outcome"] == "success"
    assert entry["receipt_ref"] == receipt_ref
    assert entry["allocations"] == {
        "input_tokens": 1500,
        "output_tokens": 40,
        "payload_bytes": 1000,
        "physical_attempts": 1,
    }
    # Over-reservation actuals are denied against the authoritative row and
    # never rewrite anything (precharge would also be exceeded here).
    with pytest.raises(TaskBudgetDeniedError):
        budget._m1_settle_with_actual_allocations(
            rid,
            receipt_ref="m1fx05u:ptx:02TESTCAS00000000000000000:ffffffffffffffff",
            observed_input=10_001,
            observed_output=40,
            payload_bytes=1000,
        )
    # Changed evidence against the settled row is a conflict (no rewrite).
    with pytest.raises(module.TaskBudgetConflictError):
        budget._m1_settle_with_actual_allocations(
            rid,
            receipt_ref="m1fx05u:ptx:01TESTCAS00000000000000000:ffffffffffffffff",
            observed_input=1500,
            observed_output=40,
            payload_bytes=1000,
        )
    assert budget.store.read(budget.budget_id)["reservations"][rid]["receipt_ref"] == receipt_ref
    # Identical replay: idempotent no-op, no revision bump.
    revision = budget.store.read(budget.budget_id)["revision"]
    budget._m1_settle_with_actual_allocations(
        rid,
        receipt_ref=receipt_ref,
        observed_input=1500,
        observed_output=40,
        payload_bytes=1000,
    )
    assert budget.store.read(budget.budget_id)["revision"] == revision
    # A payload drift against the prepared canonical size is refused too.
    with pytest.raises(TaskBudgetDeniedError):
        budget._m1_settle_with_actual_allocations(
            rid,
            receipt_ref="m1fx05u:ptx:03TESTCAS00000000000000000:0123456789abcdef",
            observed_input=1500,
            observed_output=40,
            payload_bytes=999,
        )
    report = budget.store.report(budget.budget_id)
    assert report["used_or_reserved"]["input_tokens"] == 1500
    assert report["used_or_reserved"]["output_tokens"] == 40
    assert report["used_or_reserved"]["payload_bytes"] == 1000


def test_settle_fails_closed_when_event_missing(tmp_path: Path) -> None:
    """EventStore join: no settled event for the attempt -> UNKNOWN + stop."""
    module = _runner_module()
    es, _ = _seed_event_store(
        tmp_path, attempt_id="pattempt:" + "ffffffffffffffff" * 2
    )
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 10_000  # precharge kept
    assert reservation["receipt_ref"].startswith("dispatch-receipt-")
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")


def test_settle_fails_closed_when_event_duplicated(tmp_path: Path) -> None:
    """EventStore join: two settled events for one attempt -> UNKNOWN + stop."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path, settled_count=2)
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"


def test_settle_fails_closed_when_generation_mismatches(tmp_path: Path) -> None:
    """EventStore join: call.opened bound to another run generation."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path, opened_generation="another-generation")
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"


def test_settle_fails_closed_when_event_usage_tampered(tmp_path: Path) -> None:
    """EventStore join: event usage differs from the observed snapshot."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path, input=9_999)  # != observed 1500
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 10_000  # no refund
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"


def test_settle_fails_closed_when_envelope_diverges_from_opened_event(
    tmp_path: Path,
) -> None:
    """The durable transport.opened reserved triple must re-derive the local
    pre-send envelope EXACTLY; a diverging per-request output limit (here
    200 in the event vs 128 in the guard envelope) refuses settlement."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path, max_tokens=200)  # guard envelope: 128
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 10_000  # precharge kept
    assert reservation["receipt_ref"].startswith("dispatch-receipt-")
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"


def test_settle_cas_conflict_keeps_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAS conflict: the ONLY settlement commit point is the budget store CAS.

    When the CAS mutation cannot commit (persistent stale-revision
    contention), the ledger row keeps its precharge as an UNKNOWN
    liability, the root latches a durable stop, and no second ledger
    anywhere claims "settled" (there is no sidecar to contradict it).
    """
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)

    def conflicting_mutate(*args: object, **kwargs: object) -> object:
        # Exhaust exactly the FX05 settlement CAS retries with stale-
        # revision conflicts, then let later mutations through so the I2
        # super().settle inside the except branch can still record the
        # UNKNOWN liability (the shared store.settle also routes through
        # _mutate — a permanent patch would break that fail-closed write).
        conflicting_mutate.calls += 1
        if conflicting_mutate.calls <= module._MAX_CAS_RETRIES:
            raise module.TaskBudgetConflictError(
                "stale budget revision CAS: injected conflict"
            )
        return real_mutate(*args, **kwargs)

    conflicting_mutate.calls = 0
    real_mutate = budget.store._mutate
    monkeypatch.setattr(budget.store, "_mutate", conflicting_mutate)
    budget.settle(rid, outcome="success", complete=False)
    monkeypatch.undo()
    reservation = budget.store.read(budget.budget_id)["reservations"][rid]
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 10_000  # precharge kept
    assert reservation["receipt_ref"].startswith("dispatch-receipt-")
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"
    # No second persistent ledger exists that could claim "settled".
    assert not list(tmp_path.rglob("*usage-receipts*"))
    with pytest.raises(TaskBudgetDeniedError):
        budget.assert_tool_allowed("read_file")


def test_ledger_alignment_rejects_receipt_ref_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifier recomputes the receipt_ref digest; a one-character tamper of
    any segment (prefix / event_id / digest) fails the alignment."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    real_ref = budget.store.read(budget.budget_id)["reservations"][rid][
        "receipt_ref"
    ]
    prefix, token, digest = real_ref.split(":")
    flipped = "0" if digest[0] != "0" else "1"
    tampered = f"{prefix}:{token}:{flipped}{digest[1:]}"
    assert tampered != real_ref
    real_read = budget.store.read

    def forged_read(budget_id):
        forged = dict(real_read(budget_id))
        forged["reservations"] = dict(forged["reservations"])
        forged["reservations"][rid] = dict(forged["reservations"][rid])
        forged["reservations"][rid]["receipt_ref"] = tampered
        return forged

    monkeypatch.setattr(budget.store, "read", forged_read)
    assert not module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"}
    assert per_res[rid]["aligned"] is False


def test_ledger_alignment_rejects_usage_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifier joins EventStore usage with ledger allocations: a rewritten
    allocation figure no longer matches the authoritative event and fails."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    real_read = budget.store.read

    def forged_read(budget_id):
        forged = dict(real_read(budget_id))
        forged["reservations"] = dict(forged["reservations"])
        forged["reservations"][rid] = dict(forged["reservations"][rid])
        allocations = dict(forged["reservations"][rid]["allocations"])
        allocations["input_tokens"] = 42  # tampered: event says 1500
        forged["reservations"][rid]["allocations"] = allocations
        return forged

    monkeypatch.setattr(budget.store, "read", forged_read)
    assert not module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"}
    assert per_res[rid]["aligned"] is False


def test_ledger_alignment_rejects_extra_unjoined_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Extra settled events not bound by any physical reservation fail."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)  # the joined attempt
    # A second, never-bound attempt event in the SAME session file.
    _seed_event_store(
        tmp_path, attempt_id="pattempt:" + "aaaaaaaaaaaaaaaa" * 2
    )
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    assert not module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    summary = [r for r in lines if r["event"] == "ledger_alignment"][0]
    assert summary["extra_unjoined_events"] == [
        "pattempt:" + "aaaaaaaaaaaaaaaa" * 2
    ]
    assert summary["aligned"] is False


def test_ledger_alignment_unknown_kind_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A settled reservation of an unrecognized kind fails fail-closed."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    real_read = budget.store.read

    def forged_read(budget_id):
        forged = dict(real_read(budget_id))
        forged["reservations"] = dict(forged["reservations"])
        forged["reservations"][rid] = dict(forged["reservations"][rid])
        forged["reservations"][rid]["kind"] = "mystery_dimension"
        return forged

    monkeypatch.setattr(budget.store, "read", forged_read)
    assert not module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"}
    assert per_res[rid]["event_store_join"] == "unknown_kind"
    assert per_res[rid]["aligned"] is False


def test_verifier_fail_closed_on_forged_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Parent-side FakeStore matrix: three forged rows that previously
    returned aligned=true must now fail closed.

      1. unknown kind in an UNKNOWN phase (never reclassified as a mere
         receipt-prefix row);
      2. a settled tool reservation for a tool OUTSIDE the FX05 runner
         allowlist (exec_command — exact receipt is not enough);
      3. an UNKNOWN tool row whose receipt merely starts with
         dispatch-receipt- but is not EXACTLY dispatch-receipt-<rid>.
    """
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    rid = "dispatch-forgedrow0000000000000000000"
    cases = [
        (
            "unknown_kind_unknown_phase",
            {
                "kind": "mystery_dimension",
                "phase": "unknown",
                "outcome": "unknown",
                "receipt_ref": "dispatch-receipt-anything",
                "allocations": {},
            },
            "unknown_kind",
        ),
        (
            "tool_outside_allowlist",
            {
                "kind": "tool_invocations",
                "tool_id": "exec_command",
                "phase": "settled",
                "outcome": "success",
                "receipt_ref": f"dispatch-receipt-{rid}",
            },
            "tool_not_allowed",
        ),
        (
            "unknown_tool_receipt_not_exact",
            {
                "kind": "tool_invocations",
                "tool_id": "read_file",
                "phase": "unknown",
                "outcome": "failure",
                "receipt_ref": "dispatch-receipt-unrelated",
            },
            "n/a",
        ),
    ]
    for name, forged_entry, expected_status in cases:
        row = {
            "reservations": {rid: forged_entry},
            "grant": {"session_id": "fx05-test"},
        }
        fake_store = SimpleNamespace(read=lambda budget_id, _row=row: _row)
        assert not module._verify_ledger_alignment(
            fake_store, "m1fx05-forged", event_store=es
        ), name
        lines = [
            json.loads(ln)
            for ln in capsys.readouterr().out.splitlines()
            if ln.strip()
        ]
        per_res = {
            r["reservation_id"]: r
            for r in lines
            if r["event"] == "ledger_reservation"
        }
        assert per_res[rid]["aligned"] is False, name
        assert per_res[rid]["event_store_join"] == expected_status, name


def test_settle_and_verifier_reject_cross_call_opened_splice(tmp_path: Path) -> None:
    """The transport.opened event must belong to the SAME provider call as
    the settled event: a cross-call splice (attempt id matches, call ids
    differ) fails the settle join AND the post-run verifier."""
    from llm_loop.event_log.store import EventStore

    module = _runner_module()
    es = EventStore(tmp_path / "event_logs")
    session = "fx05-test"
    es.append(session, "provider.call.opened", {
        "call_id": "pcall:legit000000000000000000000000000",
        "origin_run_generation": "test-generation",
    })
    es.append(session, "provider.transport.opened", {
        "call_id": "pcall:legit000000000000000000000000000",
        "attempt_id": ATTEMPT_ID,
        "provider_id": "glm", "model_id": "glm-5.3",
        "prepared": {"projected_bytes": 1000, "controls": {"max_tokens": 128}},
    })
    # Spliced settled event: same attempt id, DIFFERENT call.
    es.append(session, "provider.transport.settled", {
        "call_id": "pcall:other0000000000000000000000000000",
        "attempt_id": ATTEMPT_ID,
        "provider_id": "glm", "model_id": "glm-5.3",
        "outcome": "success", "usage_observations": 1, "status_code": 200,
        "usage": {"input_tokens": 1500, "output_tokens": 40, "cached_input_tokens": 0},
    })
    budget = _budget(tmp_path, module, event_store=es)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID)
    budget.settle(rid, outcome="success", complete=False)
    assert budget.store.read(budget.budget_id)["reservations"][rid]["phase"] == "unknown"
    assert budget.store.read(budget.budget_id)["phase"] == "stop_requested"


def test_verifier_rejects_cached_out_of_bounds_and_over_precharge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Event internal consistency: cached outside [0, input] fails, and a
    settled allocation exceeding the opened-rebuilt precharge fails."""
    module = _runner_module()
    # cached > input: the settle join itself refuses (fail-closed before
    # any ledger upgrade).
    es_bad, _ = _seed_event_store(
        tmp_path, usage={"input_tokens": 1500, "output_tokens": 40,
                         "cached_input_tokens": 9999}
    )
    budget = _budget(tmp_path, module, event_store=es_bad)
    rid = _manual_dispatch(module, budget)
    budget._m1_observed[rid] = _observed_snapshot(ATTEMPT_ID, cached=9999)
    budget.settle(rid, outcome="success", complete=False)
    assert budget.store.read(budget.budget_id)["reservations"][rid]["phase"] == "unknown"

    # Over-precharge settled row: allocations exceed the opened-rebuilt
    # reserved triple (input proxy 2*1000+8000=10000) — verifier fails.
    es, _ = _seed_event_store(tmp_path / "ok")
    budget2 = _budget(tmp_path / "ok", module, event_store=es)
    rid2 = _manual_dispatch(module, budget2)
    budget2._m1_observed[rid2] = _observed_snapshot(ATTEMPT_ID)
    budget2.settle(rid2, outcome="success", complete=False)
    real_read = budget2.store.read

    def inflated_read(budget_id):
        forged = dict(real_read(budget_id))
        forged["reservations"] = dict(forged["reservations"])
        forged["reservations"][rid2] = dict(forged["reservations"][rid2])
        allocations = dict(forged["reservations"][rid2]["allocations"])
        allocations["input_tokens"] = 99_999  # far over the 10_000 precharge
        forged["reservations"][rid2]["allocations"] = allocations
        return forged

    import pytest as _pytest  # noqa: F401  (local monkeypatch via fixture-free path)

    original_read = budget2.store.read
    budget2.store.read = inflated_read  # type: ignore[method-assign]
    try:
        assert not module._verify_ledger_alignment(
            budget2.store, budget2.budget_id, event_store=es
        )
    finally:
        budget2.store.read = original_read  # type: ignore[method-assign]


def test_settle_normalizes_missing_cached_from_event_store(tmp_path: Path) -> None:
    """A usage stream that omits cached_tokens settles with the cached
    figure NORMALIZED from the authoritative EventStore event (never
    fabricated, never null), and the receipt digest recomputes identically
    on the verifier side from durable events alone."""
    import hashlib

    module = _runner_module()
    es, [event_id] = _seed_event_store(tmp_path, cached=0)
    budget = _budget(tmp_path, module, event_store=es)
    client, guarded, guard_usage, counters = _guarded_client(module)
    try:
        with bind_task_budget(budget), _qualified_transport_call(guarded, client):
            # No prompt_tokens_details: observed cached_input is None.
            guard_usage(
                client,
                {"prompt_tokens": 1500, "completion_tokens": 40},
                model_id="glm-5.3",
            )
        reservation = next(
            iter(budget.store.read(budget.budget_id)["reservations"].values())
        )
        assert reservation["phase"] == "settled"
        digest = hashlib.sha256(
            json.dumps(
                {
                    "attempt_id": ATTEMPT_ID,
                    "provider_event_ref": "",
                    "observed": {"input": 1500, "output": 40, "cached_input": 0},
                    "reserved": {
                        "input_tokens": 10_000,
                        "output_tokens": 128,
                        "payload_bytes": 1000,
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[: module.USAGE_DIGEST_HEX]
        assert reservation["receipt_ref"] == f"m1fx05ev:{event_id}:{digest}"
        assert module._verify_ledger_alignment(
            budget.store, budget.budget_id, event_store=es
        )
    finally:
        client.close()


def test_verifier_unknown_tool_row_requires_allowlisted_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Parent-side reproduced miss (final same-family leak): an UNKNOWN
    tool reservation whose tool_id is NOT in FX05_ALLOWED_TOOLS (e.g.
    exec_command) but whose receipt_ref is the EXACT dispatch receipt
    must still fail alignment — the UNKNOWN branch checks both the exact
    receipt and the tool allowlist, not the receipt alone."""
    module = _runner_module()
    es, _ = _seed_event_store(tmp_path)
    budget = _budget(tmp_path, module, event_store=es)
    real_read = budget.store.read

    def forged_read(budget_id, tool_id="exec_command"):
        row = dict(real_read(budget_id))
        row["reservations"] = dict(row["reservations"])
        row["reservations"]["dispatch-forge0000000000000000000000dead"] = {
            "reservation_id": "dispatch-forge0000000000000000000000dead",
            "member_id": budget.member.member_id,
            "run_generation": budget.member.run_generation,
            "ingress_ref": "cli",
            "kind": "tool_invocations",
            "tool_id": tool_id,
            "allocations": {"tool_invocations": 1},
            "phase": "unknown",
            "outcome": "unknown",
            "receipt_ref": "dispatch-receipt-dispatch-forge0000000000000000000000dead",
            "policy_generation": 1,
        }
        return row

    monkeypatch.setattr(
        budget.store, "read", lambda budget_id: forged_read(budget_id)
    )
    assert not module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
    lines = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()
    ]
    per_res = {
        r["reservation_id"]: r for r in lines if r["event"] == "ledger_reservation"
    }
    forged = per_res["dispatch-forge0000000000000000000000dead"]
    assert forged["aligned"] is False
    assert forged["event_store_join"] == "tool_not_allowed"

    # Control: the SAME forged-exact receipt with an allowlisted tool_id
    # passes the UNKNOWN branch (receipt + allowlist both satisfied).
    monkeypatch.setattr(
        budget.store,
        "read",
        lambda budget_id: forged_read(budget_id, tool_id="read_file"),
    )
    assert module._verify_ledger_alignment(
        budget.store, budget.budget_id, event_store=es
    )
