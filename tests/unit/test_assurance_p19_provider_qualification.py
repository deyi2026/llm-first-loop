"""P1.9 current TaskBudget/Fleet/STOP compatibility, zero Provider calls."""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from pathlib import Path

import pytest

from llm_loop.assurance.p16_host_broker import (
    BrokerDeniedError,
    OfflineHostReviewBroker,
    OfflineReviewRequest,
    OnceOnlyBrokerJournal,
    OwnerEvidenceCatalog,
)
from llm_loop.assurance.p19_provider_qualification import (
    P19_EXTERNAL_ISSUER,
    P19_POLICY,
    P19_PROFILE,
    P19_SURFACE,
    ReviewerProviderQualification,
)
from llm_loop.assurance.task_control_store import LeaseRef, TaskControlStore
from llm_loop.fleet.store import FleetStore
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import TaskBudgetExecution
from llm_loop.resources.task_budget_store import TaskBudgetStore

CANDIDATE_SHA = hashlib.sha256(b"frozen review candidate").hexdigest()
ACCEPTANCE_SHA = hashlib.sha256(b"frozen reviewed acceptance").hexdigest()


@pytest.fixture
def work(tmp_path: Path):
    root = tmp_path / "assurance-p19-root"
    control = TaskControlStore(root / "control")
    control.create_once(
        "task_review_01", "owner_01", CANDIDATE_SHA,
        ACCEPTANCE_SHA, "budget_reviewer_01",
    )
    fleet = FleetStore(root / "fleet")
    fleet.create_project("project_01")
    ws = fleet.create_workspace("project_01", str(root / "synthetic"), CANDIDATE_SHA)
    lease = fleet.acquire_lease(
        "project_01", ws.workspace_id,
        owner_id="owner_01", worker_id="worker_01", ttl_seconds=20,
    )
    ref = LeaseRef(
        ws.workspace_id, lease.lease_id, lease.generation,
        lease.worker_id, "generation_1",
    )

    def verify(_: LeaseRef):
        return fleet.lease_is_current(lease)

    prepared = control.prepare_binding_cas(
        "task_review_01", "owner_01", 0, ref, verify,
    )
    task = control.commit_binding_cas(
        "task_review_01", "owner_01", prepared.revision, ref, verify,
    )
    broker = OfflineHostReviewBroker(
        control, fleet, OwnerEvidenceCatalog([]),
        OnceOnlyBrokerJournal(root / "review_calls"),
    )
    req = OfflineReviewRequest(
        "review_compatibility", "task_review_01", "owner_01",
        "budget_reviewer_01", task.control_epoch, task.revision,
        CANDIDATE_SHA, (), lease, ref,
    )
    gate = ReviewerProviderQualification(broker)

    def issue(*, profile=P19_PROFILE, policy=P19_POLICY, surface=P19_SURFACE,
              authority=P19_EXTERNAL_ISSUER, tools=frozenset(),
              physical_attempts=1, session_id=req.task_id,
              run_generation=req.lease_ref.run_generation,
              budget_id=req.grant_ref):
        # Synthetic unsigned test root: this ONLY tests contract structure.
        # A production issuer cannot mint P19 authorization via this helper.
        ledger = TaskBudgetStore(root / ("budget_" + profile))
        grant = TaskBudgetGrant(
            budget_id=budget_id,
            issuer="test-only-not-a-signed-operator",
            authority_source=authority,
            workspace_scope="ws-p19-test",
            session_id=session_id,
            human_turn_ref="synthetic-review-event",
            surface=surface,
            profile=profile,
            policy_version=policy,
            deadline_epoch_s=time.time() + 90,
            limits=TaskBudgetLimits(
                physical_attempts=physical_attempts, tool_invocations=0,
            ),
            capabilities=TaskBudgetCapabilities(
                allowed_tools=tools, allow_wake=False, allow_subagents=False,
            ),
            provider_identity="glm", exact_model_ref="glm-5.3",
        )
        issued = ledger.issue_root(
            grant, root_run_generation=run_generation,
            ingress_kind="synthetic:review",
        )
        ledger.activate(budget_id, expected_revision=issued["revision"])
        member = TaskBudgetMember.from_dict(
            ledger.read(budget_id)["members"][budget_id]
        )
        return TaskBudgetExecution(ledger, budget_id, member)

    return control, fleet, gate, req, issue


def test_unbound_reviewer_budget_is_explicit_no_go(work):
    _, _, gate, req, _ = work
    result = gate.inspect(req, execution=None)
    assert result.task_fleet_current
    assert not result.budget_contract_matches
    assert "NO_TRUSTED_REVIEWER_BUDGET" in result.blockers
    assert not result.may_open_provider_transport
    with pytest.raises(BrokerDeniedError, match="NO_TRUSTED"):
        gate.require_provider_send_permit(req, execution=None)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("profile", "web-glm-one-physical-attempt-v3", "NO_DEDICATED_REVIEWER_ISSUANCE_PROFILE"),
        ("profile", "web-glm-knowledge-consumption-v1", "NO_DEDICATED_REVIEWER_ISSUANCE_PROFILE"),
        ("policy", "web-operator-once-policy-v1", "NO_DEDICATED_REVIEWER_ISSUANCE_PROFILE"),
        ("surface", "web", "NO_DEDICATED_REVIEWER_ISSUANCE_PROFILE"),
        ("authority", "user-session-cookie", "NO_DEDICATED_REVIEWER_ISSUANCE_PROFILE"),
        ("tools", frozenset({"execute_command"}), "REVIEWER_PHYSICAL_OR_TOOL_LIMIT_UNQUALIFIED"),
        ("physical_attempts", 4, "REVIEWER_PHYSICAL_OR_TOOL_LIMIT_UNQUALIFIED"),
        ("session_id", "web-session", "SESSION_NOT_REVIEW_TASK"),
        ("run_generation", "old-generation", "RUN_GENERATION_NOT_FLEET_BOUND"),
    ],
)
def test_current_web_profile_or_derived_scope_cannot_authorize_review(
    work, field, value, code,
):
    _, _, gate, req, issue = work
    candidate = issue(**{field: value})
    result = gate.inspect(req, execution=candidate)
    assert code in result.blockers
    assert not result.may_open_provider_transport
    assert candidate.store.report(candidate.budget_id)["used_or_reserved"]["physical_attempts"] == 0
    with pytest.raises(BrokerDeniedError):
        gate.require_provider_send_permit(req, execution=candidate)


def test_even_matching_unsigned_synthetic_budget_has_no_external_authority(work):
    _, _, gate, req, issue = work
    execution = issue()
    result = gate.inspect(req, execution=execution)
    assert result.task_fleet_current
    assert result.budget_contract_matches
    assert result.physical_attempts_remaining == 1
    assert result.independently_authorized is False
    assert "REVIEWER_OPERATOR_ISSUER_NOT_INSTALLED" in result.blockers
    assert "INDEPENDENT_OCI_SECURITY_SIGNOFF_MISSING" in result.blockers
    assert not result.may_open_provider_transport
    with pytest.raises(BrokerDeniedError):
        gate.require_provider_send_permit(req, execution=execution)
    assert execution.store.report(execution.budget_id)["used_or_reserved"]["physical_attempts"] == 0


def test_opened_budget_attempt_is_unknown_and_denies_new_send(work):
    _, _, gate, req, issue = work
    execution = issue()
    rid = execution.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    assert rid.startswith("dispatch-")
    result = gate.inspect(req, execution=execution)
    assert result.physical_attempts_remaining == 0
    assert "REVIEWER_BUDGET_UNKNOWN_OR_NOT_ACTIVE" in result.blockers
    assert "PHYSICAL_ATTEMPT_ALREADY_OPENED_OR_UNKNOWN" in result.blockers
    with pytest.raises(BrokerDeniedError):
        gate.require_provider_send_permit(req, execution=execution)
    assert execution.store.report(execution.budget_id)["physical_quiescence_verified"] is False


def test_durable_stop_and_fleet_expiry_override_even_a_matching_budget(work):
    control, fleet, gate, req, issue = work
    execution = issue()
    assert gate.inspect(req, execution=execution).task_fleet_current
    control.append_intent_cas(
        req.task_id, req.owner, req.task_revision,
        "stop_operator", "STOP", CANDIDATE_SHA,
    )
    stopped = gate.inspect(req, execution=execution)
    assert "TASK_STOP_OR_FLEET_FENCED" in stopped.blockers
    assert stopped.may_open_provider_transport is False
    # A separate synthetic budget remains ACTIVE: STOP still wins.
    assert execution.store.read(execution.budget_id)["phase"] == "active"
    with pytest.raises(BrokerDeniedError):
        gate.require_provider_send_permit(req, execution=execution)
    assert fleet.lease_is_current(req.fleet_lease)


def test_changed_budget_grant_reference_or_type_is_not_accepted(work):
    _, _, gate, req, issue = work
    valid = issue()
    invalid = gate.inspect(replace(req, grant_ref="different_budget"), execution=valid)
    assert not invalid.task_fleet_current
    assert "GRANT_REF_NOT_BOUND_TO_TASK" in invalid.blockers
    invalid_type = gate.inspect(req, execution=object())  # type: ignore[arg-type]
    assert "INVALID_REVIEWER_BUDGET_TYPE" in invalid_type.blockers
    assert not invalid_type.may_open_provider_transport
