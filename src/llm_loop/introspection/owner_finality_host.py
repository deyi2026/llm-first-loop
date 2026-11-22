"""Trusted local Host query for completed Goal finality; no Engine or Provider.

This is an operator/Host read-only observation, never an approval or a Goal
mutation. All source roots are bound by the Host CLI configuration, not
by model-authored tool arguments.
"""

from __future__ import annotations

import re
from pathlib import Path

from llm_loop.introspection.owner_finality_preflight import (
    OwnerShortRunContract,
    read_owner_short_run,
)

_RULES = ("RULE-AI-01",)
_SKILL_STEPS = (
    "1. Match exact Goal and Owner session.",
    "2. Require terminal Tasks and durable EvidenceRefs.",
    "3. Verify every EvidenceRef in current OwnerScope.",
    "4. Rehydrate RULE-AI-01 and manifest-verified Skill.",
    "5. Return HOLD on any gap; never issue a Host grant.",
)
_SKILLS = {"owner-finality-verify": _SKILL_STEPS}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _receipt(
    *,
    decision: str = "HOLD",
    reason: str = "owner_authority_unavailable",
    goal_status: str = "unknown",
    goal_version: int | None = None,
    tasks_checked: int = 0,
    evidence_refs_checked: int = 0,
    evidence_status: str = "unavailable",
    knowledge_gaps: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "schema": "lfl.owner-finality-host/v1",
        "decision": decision,
        "reason": reason,
        "goal_status": goal_status,
        "goal_version": goal_version,
        "tasks_checked": tasks_checked,
        "evidence_refs_checked": evidence_refs_checked,
        "evidence_status": evidence_status,
        "knowledge_gaps": list(knowledge_gaps),
        "no_write": True,
        "model_calls": 0,
        "host_permission_granted": False,
    }


def check_completed_goal(
    *,
    data_dir: Path,
    workspace: Path,
    asset_root: Path,
    goal_id: str,
    session_id: str,
) -> dict[str, object]:
    """Recheck actual Goal/Task/Evidence/Rule/Skill; HOLD on any missing fact.

    Never build LoopEngine, send a Provider request, create a new session,
    accept a model-supplied EvidenceRef, or authorize a write. The caller
    must bind data/workspace/asset roots from trusted Host configuration.
    """

    if not (_ID_RE.fullmatch(goal_id) and _ID_RE.fullmatch(session_id)):
        return _receipt(reason="invalid_goal_or_session_id")
    try:
        data = Path(data_dir).resolve(strict=True)
        workspace = Path(workspace).resolve(strict=True)
        assets = Path(asset_root).resolve(strict=True)
        audit = data / "audit"
        task_path = audit / "tasks" / f"{goal_id}.jsonl"
        rule_path = assets / "docs" / "ai_rules.md"
        skills_dir = assets / "skills"
        skill_path = skills_dir / "owner-finality-verify" / "SKILL.md"
        manifest = skills_dir / ".manifest.json"
        evidence_root = data / "evidence"

        # Constructors of legacy stores mkdir; never instantiate them
        # against missing roots in a read-only Host query.
        if not data.is_dir() or not workspace.is_dir() or not assets.is_dir():
            return _receipt(reason="owner_roots_unavailable")
        if not (audit / "goals.jsonl").is_file() or not task_path.is_file():
            return _receipt(reason="goal_or_task_ledger_missing")
        if not rule_path.is_file() or not skill_path.is_file() or not manifest.is_file():
            return _receipt(reason="required_rule_or_skill_unavailable")
        if not (evidence_root / "blobs").is_dir() or not (evidence_root / "ledger").is_dir():
            return _receipt(reason="evidence_store_unavailable")
        from llm_loop.introspection.goal import GoalStore
        from llm_loop.introspection.task_evidence import TaskEvidenceVerifier
        from llm_loop.memory.evidence import BlobStore, EvidenceLedgerStore, OwnerScope

        goal = GoalStore(audit).get(goal_id)
        if not isinstance(goal, dict) or goal.get("session_id") != session_id:
            return _receipt(reason="goal_owner_scope_mismatch")
        if goal.get("status") != "complete":
            return _receipt(
                reason="goal_not_complete",
                goal_status=str(goal.get("status") or "unknown"),
            )

        # TaskEvidenceVerifier takes an advisory file lock even for reads.
        # If its existing lock file is absent, do not create one while
        # claiming this Host check is a no-write operation.
        if not (evidence_root / "ledger" / ".gc.lock").is_file():
            return _receipt(reason="evidence_lock_unavailable")

        owner = OwnerScope(workspace_id=str(workspace), session_id=session_id)
        verifier = TaskEvidenceVerifier(
            BlobStore(evidence_root / "blobs"),
            EvidenceLedgerStore(evidence_root / "ledger"),
            owner_resolver=lambda: owner,
        )
        contract = OwnerShortRunContract(
            goal_id=goal_id,
            session_id=session_id,
            rule_path=rule_path,
            skills_dir=skills_dir,
            required_rules=_RULES,
            required_skills=_SKILLS,
            previous_run_status="unknown",
        )
        result = read_owner_short_run(contract, audit_dir=audit, verifier=verifier)
        facts = result.preflight
        decision = (
            "NO_WRITE_VERIFIED" if facts.decision == "NO_WRITE_VERIFIED" else "HOLD"
        )
        return _receipt(
            decision=decision,
            reason=facts.reason,
            goal_status=facts.goal_status,
            goal_version=result.goal_version,
            tasks_checked=result.tasks_checked,
            evidence_refs_checked=result.evidence_refs_checked,
            evidence_status=facts.evidence_status,
            knowledge_gaps=facts.knowledge_gaps,
        )
    except Exception:  # noqa: BLE001 -- no authority error can become a verified finality
        return _receipt(reason="owner_authority_unavailable")
