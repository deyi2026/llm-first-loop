"""P1.9 existing-TaskBudget/Task/Fleet Reviewer admission preflight.

This is a *non-sending*, read-only eligibility probe. In particular, a
TaskBudgetStore root is not itself a cryptographically verified operator
approval: anyone who can write the test store may fabricate such a row.
Current LFL issuers authorize Web human turns, not independent reviewers.

No implementation path in this module returns a production send permit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_loop.assurance.p16_host_broker import (
    BrokerDeniedError,
    OfflineHostReviewBroker,
    OfflineReviewRequest,
)
from llm_loop.resources.task_budget_dispatch import TaskBudgetExecution

P19_PROFILE = "dual-agent-reviewer-glm5.3-v1"
P19_POLICY = "dual-agent-reviewer-independent-operator-v1"
P19_SURFACE = "dual-agent-reviewer"
P19_PROVIDER = "glm"
P19_MODEL = "glm-5.3"
P19_EXTERNAL_ISSUER = "independent-reviewer-operator-service/v1"


@dataclass(frozen=True)
class ReviewerProviderReadiness:
    task_fleet_current: bool
    budget_contract_matches: bool
    physical_attempts_remaining: int | None
    blockers: tuple[str, ...]
    # Do not add success from a self-claimed ledger grant. True operator
    # signature, trusted OCI/SBOM, physical Stop and live issuer are absent.
    independently_authorized: bool = False
    may_open_provider_transport: bool = False
    may_release_review_or_effect: bool = False


def _budget_contract_check(
    request: OfflineReviewRequest, execution: TaskBudgetExecution,
) -> tuple[bool, int | None, list[str]]:
    reasons: list[str] = []
    try:
        snapshot = execution._get_validated()
        grant: dict[str, Any] = snapshot["grant"]
        member = execution.member
        if (
            execution.budget_id != request.grant_ref
            or grant["budget_id"] != execution.budget_id
        ):
            reasons.append("GRANT_REF_NOT_BOUND_TO_TASK")
        if member.session_id != request.task_id:
            reasons.append("SESSION_NOT_REVIEW_TASK")
        if member.run_generation != request.lease_ref.run_generation:
            reasons.append("RUN_GENERATION_NOT_FLEET_BOUND")
        if grant["workspace_scope"] != member.workspace_scope:
            reasons.append("WORKSPACE_SCOPE_MISMATCH")
        if (
            grant["profile"] != P19_PROFILE
            or grant["policy_version"] != P19_POLICY
            or grant["surface"] != P19_SURFACE
            or grant["authority_source"] != P19_EXTERNAL_ISSUER
        ):
            reasons.append("NO_DEDICATED_REVIEWER_ISSUANCE_PROFILE")
        if (
            grant["provider_identity"] != P19_PROVIDER
            or grant["exact_model_ref"] != P19_MODEL
        ):
            reasons.append("REVIEWER_PROVIDER_TARGET_MISMATCH")
        limits = grant["limits"]
        capabilities = grant["capabilities"]
        if (
            limits["physical_attempts"] != 1
            or limits["tool_invocations"] != 0
            or capabilities["allowed_tools"] != []
            or capabilities["allow_wake"] is not False
            or capabilities["allow_subagents"] is not False
        ):
            reasons.append("REVIEWER_PHYSICAL_OR_TOOL_LIMIT_UNQUALIFIED")
        report = execution.store.report(execution.budget_id)
        if (
            report["phase"] != "active"
            or report["generation"] != grant["generation"]
            or report["outstanding_or_unknown"]
            or report["over_limit_dimensions"]
        ):
            reasons.append("REVIEWER_BUDGET_UNKNOWN_OR_NOT_ACTIVE")
        used = report["used_or_reserved"]["physical_attempts"]
        remaining = max(0, 1 - used)
        if used != 0:
            reasons.append("PHYSICAL_ATTEMPT_ALREADY_OPENED_OR_UNKNOWN")
        return not reasons, remaining, reasons
    except Exception:  # noqa: BLE001 - invalid/unreadable budget refuses admission
        return False, None, ["REVIEWER_BUDGET_MISSING_INVALID_OR_STOPPED"]


class ReviewerProviderQualification:
    """Read-only proof-of-compatibility: never sends, reserves or signs."""

    def __init__(self, broker: OfflineHostReviewBroker) -> None:
        self.broker = broker

    def inspect(
        self, request: OfflineReviewRequest, *,
        execution: TaskBudgetExecution | None,
    ) -> ReviewerProviderReadiness:
        reasons: list[str] = []
        current = self.broker._guard(request)
        if not current:
            reasons.append("TASK_STOP_OR_FLEET_FENCED")
        matched = False
        remaining: int | None = None
        if execution is None:
            reasons.append("NO_TRUSTED_REVIEWER_BUDGET")
        elif not isinstance(execution, TaskBudgetExecution):
            reasons.append("INVALID_REVIEWER_BUDGET_TYPE")
        else:
            matched, remaining, issues = _budget_contract_check(
                request, execution,
            )
            reasons.extend(issues)
        # These are *actual missing authorities*, not untrusted request
        # booleans. The only current signed issuers are Web-run scoped.
        reasons.extend((
            "REVIEWER_OPERATOR_ISSUER_NOT_INSTALLED",
            "INDEPENDENT_OCI_SECURITY_SIGNOFF_MISSING",
            "REVIEWER_PHYSICAL_STOP_AND_EFFECT_FENCE_NOT_WIRED",
        ))
        return ReviewerProviderReadiness(
            task_fleet_current=current,
            budget_contract_matches=matched,
            physical_attempts_remaining=remaining,
            blockers=tuple(dict.fromkeys(reasons)),
        )

    def require_provider_send_permit(
        self, request: OfflineReviewRequest, *,
        execution: TaskBudgetExecution | None,
    ) -> None:
        outcome = self.inspect(request, execution=execution)
        raise BrokerDeniedError(
            "P1.9 production GLM reviewer transport unauthorized: "
            + ",".join(outcome.blockers)
        )
