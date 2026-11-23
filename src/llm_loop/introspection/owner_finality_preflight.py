"""Read-only Owner short-Run finality and knowledge-reuse safety contract.

The caller supplies trusted Goal/Run observations, TaskEvidenceVerifier and exact
Rule/Skill hydration receipts.  This is not a new authority or a completion
tool: it cannot write a Goal, issue a Host grant or infer current facts from
Experience/LLM prose.  It is safe to use before a model call and to reconcile
its proposed finality label after the call.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshot:
    kind: str
    ref: str
    source_version: str
    content_sha256: str
    complete: bool
    integrity: str = ""
    required_steps_present: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Durable JSON snapshots turn tuples into lists.  Normalize before a
        # cross-Run equality check to avoid a false "source changed" HOLD.
        object.__setattr__(
            self, "required_steps_present", tuple(self.required_steps_present)
        )


@dataclass(frozen=True, slots=True)
class FinalityPreflight:
    decision: str
    reason: str
    evidence_status: str
    knowledge_gaps: tuple[str, ...]
    goal_status: str
    run_status: str

    @property
    def may_claim_verified(self) -> bool:
        return self.decision == "NO_WRITE_VERIFIED"


@dataclass(frozen=True, slots=True)
class FinalityReconciliation:
    decision: str
    model_claim_rejected: bool
    reason: str


def rule_snapshot(record: Mapping[str, Any]) -> KnowledgeSnapshot:
    """Accept only an exact, fully hydrated Rule SoT record, not a search card."""

    content = str(record.get("content") or "")
    ref = str(record.get("rule_ref") or "")
    version = str(record.get("source_version_token") or "")
    complete = bool(
        record.get("hydrated") is True
        and record.get("projection_complete") is True
        and record.get("authority") == "rule_sot"
        and ref.startswith("RULE-AI-")
        and version
        and content.strip()
    )
    return KnowledgeSnapshot(
        kind="rule",
        ref=ref,
        source_version=version,
        content_sha256=hashlib.sha256(content.encode()).hexdigest() if complete else "",
        complete=complete,
    )


def skill_snapshot(
    name: str,
    loaded: ToolResult,
    *,
    required_steps: Sequence[str],
) -> KnowledgeSnapshot:
    """Check a full, integrity-verified skill_load result and all required steps.

    The step markers are supplied by the trusted task contract; merely naming a
    Skill or claiming a count is never sufficient.  Actual external actions
    still require their own Host/tool receipts, not this content check.
    """

    content = loaded.content
    marker = "--- SKILL.md 全文 ---\n"
    body = content.split(marker, 1)[1] if marker in content else ""
    steps = tuple(str(s).strip() for s in required_steps)
    integrity_ok = (
        loaded.status is ToolResultStatus.SUCCESS
        and loaded.tool_name == "skill_load"
        and content.startswith(f"[技能 {name}] ")
        and "（integrity=ok）" in content.split("\n", 1)[0]
    )
    step_positions = [body.find(step) if step else -1 for step in steps]
    complete = bool(
        name.strip()
        and integrity_ok
        and body.strip()
        and "next_offset=" not in content
        and steps
        and all(position >= 0 for position in step_positions)
        and step_positions == sorted(step_positions)
    )
    return KnowledgeSnapshot(
        kind="skill",
        ref=name,
        source_version=hashlib.sha256(body.encode()).hexdigest() if complete else "",
        content_sha256=hashlib.sha256(body.encode()).hexdigest() if complete else "",
        complete=complete,
        integrity="ok" if integrity_ok else "unverified",
        required_steps_present=steps if complete else (),
    )


def knowledge_reuse_gaps(
    *,
    required_rules: Sequence[str],
    required_skills: Mapping[str, Sequence[str]],
    current: Sequence[KnowledgeSnapshot],
    previous: Sequence[KnowledgeSnapshot] | None = None,
) -> tuple[str, ...]:
    """Fail closed on incomplete, stale or renamed Rule/Skill, including reused Runs.

    A fresh short Run must obtain current exact source snapshots.  A reused
    short Run additionally compares its previously hydrated snapshot to the
    current authoritative source; a changed digest means rehydrate, not reuse.
    """

    now = {(p.kind, p.ref): p for p in current}
    prior = {(p.kind, p.ref): p for p in previous} if previous is not None else None
    gaps: list[str] = []

    def require(kind: str, ref: str, steps: tuple[str, ...] = ()) -> None:
        key = (kind, ref)
        proof = now.get(key)
        if proof is None or not proof.complete or not proof.source_version or not proof.content_sha256:
            gaps.append(f"{kind}:{ref}:not_fully_hydrated")
            return
        if kind == "skill" and (
            proof.integrity != "ok"
            or not steps
            or not set(steps).issubset(proof.required_steps_present)
        ):
            gaps.append(f"{kind}:{ref}:required_steps_or_integrity_missing")
            return
        if prior is not None:
            old = prior.get(key)
            if old is None or not old.complete:
                gaps.append(f"{kind}:{ref}:prior_hydration_missing")
            elif (
                old.source_version != proof.source_version
                or old.content_sha256 != proof.content_sha256
                or (kind == "skill" and old.required_steps_present != proof.required_steps_present)
            ):
                gaps.append(f"{kind}:{ref}:source_changed_rehydrate")

    for ref in dict.fromkeys(str(r).strip() for r in required_rules):
        if not ref:
            gaps.append("rule:required_ref_missing")
        else:
            require("rule", ref)
    for name, markers in required_skills.items():
        if not name.strip():
            gaps.append("skill:required_ref_missing")
        else:
            require("skill", name, tuple(str(m).strip() for m in markers))
    return tuple(gaps)


def verify_evidence_refs(
    refs: Sequence[str],
    verifier: TaskEvidenceVerifier | None,
    *,
    evidence_required: bool = True,
) -> tuple[str, str]:
    """Live owner/integrity check; a historical verified flag is not sufficient."""

    refs = tuple(str(r).strip() for r in refs)
    evidence_status = "not_required"
    reason = ""
    if evidence_required and not refs:
        evidence_status = "missing"
        reason = "evidence_ref_missing"
    elif refs:
        if not all(refs) or verifier is None:
            evidence_status = "verification_unavailable"
        else:
            try:
                report = verifier.verify(refs)
                evidence_status = str(report.status)
                if (
                    report.status == "verified"
                    and (report.checked_count != len(refs) or report.failing_ref)
                ):
                    evidence_status = "verification_incomplete"
            except Exception:  # noqa: BLE001 -- unavailable verifier must not yield verified
                evidence_status = "verification_unavailable"
        if evidence_status != "verified":
            reason = f"evidence_{evidence_status}"
    return evidence_status, reason


def owner_finality_preflight(
    *,
    goal_status: str,
    run_status: str,
    evidence_refs: Sequence[str],
    verifier: TaskEvidenceVerifier | None,
    knowledge_gaps: Sequence[str] = (),
    evidence_required: bool = True,
    enforce_knowledge: bool = False,
    required_rules: Sequence[str] = (),
    required_skills: Mapping[str, Sequence[str]] | None = None,
    current_knowledge: Sequence[KnowledgeSnapshot] | None = None,
    previous_knowledge: Sequence[KnowledgeSnapshot] | None = None,
) -> FinalityPreflight:
    """Never turn an absent/unverified EvidenceRef into verified completion.

    This only verifies ref authenticity/owner/integrity, not semantic sufficiency,
    actual Host authorization, task acceptance or approval to write.
    """

    gaps = tuple(knowledge_gaps)
    if enforce_knowledge:
        if not required_rules or not required_skills or current_knowledge is None:
            gaps += ("knowledge:required_contract_or_hydration_missing",)
        else:
            gaps += knowledge_reuse_gaps(
                required_rules=required_rules,
                required_skills=required_skills,
                current=current_knowledge,
                previous=previous_knowledge,
            )
    evidence_status, reason = verify_evidence_refs(
        evidence_refs, verifier, evidence_required=evidence_required
    )
    if not reason and gaps:
        reason = "required_knowledge_not_verified"
    if not reason and goal_status not in {"active", "complete"}:
        reason = "goal_status_not_authoritative"
    if reason:
        decision = "HOLD"
    elif goal_status == "complete" and evidence_status == "verified":
        decision = "NO_WRITE_VERIFIED"
        reason = "goal_already_complete_with_verified_refs"
    else:
        decision = "PROCEED_READ_ONLY"
        reason = "finality_not_established_no_write_authority"
    return FinalityPreflight(
        decision=decision,
        reason=reason,
        evidence_status=evidence_status,
        knowledge_gaps=gaps,
        goal_status=goal_status,
        run_status=run_status,
    )


def reconcile_model_finality(
    preflight: FinalityPreflight, proposed_decision: str
) -> FinalityReconciliation:
    """Reject unsupported model claims without hiding the model's raw error."""

    proposed = str(proposed_decision or "").strip()
    if preflight.decision == "HOLD":
        return FinalityReconciliation(
            "HOLD", proposed != "HOLD", preflight.reason
        )
    if proposed == "HOLD":
        return FinalityReconciliation("HOLD", False, "model_conservative_hold")
    if proposed != preflight.decision:
        return FinalityReconciliation("HOLD", True, "model_claim_not_supported")
    return FinalityReconciliation(preflight.decision, False, preflight.reason)


@dataclass(frozen=True, slots=True)
class OwnerShortRunContract:
    """Trusted Host-only, read-only finality check; never populated from model text.

    Rule/Skill paths are resolved by the caller from the installed runtime assets,
    not from tool arguments or retrieved web content.  A previous snapshot is
    advisory: current sources are always reloaded before any reuse decision.
    """

    goal_id: str
    session_id: str
    rule_path: Path
    skills_dir: Path
    required_rules: tuple[str, ...]
    required_skills: Mapping[str, tuple[str, ...]]
    previous_knowledge: tuple[KnowledgeSnapshot, ...] | None = None
    previous_run_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class OwnerShortRunResult:
    preflight: FinalityPreflight
    goal_id: str
    goal_version: int | None
    tasks_checked: int
    evidence_refs_checked: int
    current_knowledge: tuple[KnowledgeSnapshot, ...]


def _short_run_hold(
    contract: OwnerShortRunContract,
    reason: str,
    *,
    goal_status: str = "unknown",
    goal_version: int | None = None,
    tasks_checked: int = 0,
) -> OwnerShortRunResult:
    return OwnerShortRunResult(
        preflight=FinalityPreflight(
            decision="HOLD",
            reason=reason,
            evidence_status="unavailable",
            knowledge_gaps=(),
            goal_status=goal_status,
            run_status=contract.previous_run_status,
        ),
        goal_id=contract.goal_id,
        goal_version=goal_version,
        tasks_checked=tasks_checked,
        evidence_refs_checked=0,
        current_knowledge=(),
    )


def _current_rule_skill_snapshots(
    contract: OwnerShortRunContract, audit_dir: Path
) -> tuple[KnowledgeSnapshot, ...]:
    """Rehydrate exact Rule SoT and manifest-verified full Skill bodies, never cards."""

    from types import SimpleNamespace

    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.introspection.tools_skill_files import run_skill_load

    searcher = RecordSearcher(audit_dir=audit_dir, rule_path=contract.rule_path)
    snapshots: list[KnowledgeSnapshot] = []
    for ref in contract.required_rules:
        rows = searcher.search(kind="rule", query=ref, limit=5)
        exact = next((r for r in rows if str(r.get("rule_ref")) == ref), None)
        snapshots.append(rule_snapshot(exact or {"rule_ref": ref}))
    host = SimpleNamespace(skills_dir=str(contract.skills_dir))
    for name, steps in contract.required_skills.items():
        loaded = run_skill_load(host, {"name": name})
        snapshots.append(skill_snapshot(name, loaded, required_steps=steps))
    return tuple(snapshots)


def read_owner_short_run(
    contract: OwnerShortRunContract,
    *,
    audit_dir: Path,
    verifier: TaskEvidenceVerifier | None,
) -> OwnerShortRunResult:
    """Real runtime read-only gate; missing EvidenceRef returns HOLD before LLM.

    The Goal is read by exact ID and session owner; refs come exclusively from
    durable done Tasks.  Neither an LLM-supplied ref nor a persisted 'verified'
    flag can substitute for a live TaskEvidenceVerifier check.  The result is
    NOT a Host grant, Goal update, Task acceptance or proof of external effects.
    """

    import json

    from llm_loop.introspection.goal import GoalStore
    from llm_loop.introspection.task_store import TaskStore, safe_goal_id

    if not contract.goal_id or not contract.session_id:
        return _short_run_hold(contract, "owner_contract_missing")
    try:
        store = GoalStore(audit_dir)
        goal = store.get(contract.goal_id)
        if not isinstance(goal, dict) or goal.get("session_id") != contract.session_id:
            return _short_run_hold(contract, "goal_owner_scope_mismatch")
        status = str(goal.get("status") or "unknown")
        version = store.version_of(goal)
        task_path = audit_dir / "tasks" / f"{safe_goal_id(contract.goal_id)}.jsonl"
        if not task_path.is_file():
            return _short_run_hold(contract, "task_evidence_missing", goal_status=status,
                                   goal_version=version)
        before = task_path.read_bytes()
        if not before or len(before) > 4_000_000:
            return _short_run_hold(contract, "task_ledger_empty_or_oversize",
                                   goal_status=status, goal_version=version)
        # TaskStore normally skips malformed historical lines for availability;
        # a *verified finality* claim instead fails closed on any corrupt row.
        try:
            rows = [json.loads(line) for line in before.decode("utf-8").splitlines()
                    if line.strip()]
        except (UnicodeError, json.JSONDecodeError):
            return _short_run_hold(contract, "task_ledger_corrupt",
                                   goal_status=status, goal_version=version)
        if any(not isinstance(row, dict) or not row.get("task_id")
               or row.get("goal_id") != contract.goal_id for row in rows):
            return _short_run_hold(contract, "task_ledger_corrupt",
                                   goal_status=status, goal_version=version)
        tasks = TaskStore(audit_dir).list_for_goal(contract.goal_id)
        gaps: list[str] = []
        refs: list[str] = []
        if not tasks or not any(t.status == "done" for t in tasks):
            gaps.append("task:no_verified_done_task")
        for task in tasks:
            if task.status not in {"done", "cancelled"}:
                gaps.append(f"task:{task.task_id}:not_terminal")
            if task.status == "done":
                if not task.evidence_refs:
                    gaps.append(f"task:{task.task_id}:evidence_ref_missing")
                if task.evidence_verification_status != "verified":
                    gaps.append(f"task:{task.task_id}:historical_verification_missing")
                refs.extend(task.evidence_refs)
        base = owner_finality_preflight(
            goal_status=status, run_status=contract.previous_run_status,
            evidence_refs=refs, verifier=verifier, knowledge_gaps=gaps,
        )
        if base.decision == "HOLD":
            return OwnerShortRunResult(base, contract.goal_id, version,
                                       len(tasks), len(refs), ())
        # Only after evidence authenticity succeeds do we load Rule/Skill.
        # Missing/changed required steps cannot be skipped for a shorter Run.
        snapshots = _current_rule_skill_snapshots(contract, audit_dir)
        final = owner_finality_preflight(
            goal_status=status, run_status=contract.previous_run_status,
            evidence_refs=refs, verifier=verifier, enforce_knowledge=True,
            required_rules=contract.required_rules,
            required_skills=contract.required_skills,
            current_knowledge=snapshots,
            previous_knowledge=contract.previous_knowledge,
        )
        # Optimistic read-only consistency check: a concurrent Task/Goal change
        # invalidates this observation; it never grants a write capability.
        goal_after = store.get(contract.goal_id)
        if (task_path.read_bytes() != before or not isinstance(goal_after, dict)
                or store.version_of(goal_after) != version
                or goal_after.get("status") != status):
            return _short_run_hold(contract, "owner_state_changed_during_check",
                                   goal_status=status, goal_version=version,
                                   tasks_checked=len(tasks))
        return OwnerShortRunResult(final, contract.goal_id, version,
                                   len(tasks), len(refs), snapshots)
    except Exception:  # noqa: BLE001 -- authority errors must deterministically HOLD
        return _short_run_hold(contract, "owner_authority_unavailable")
