"""Owner short-Run deterministic EvidenceRef/Rule/Skill fail-closed regression.

All evidence, Goal, Rule and Skill stores live under tmp_path.  No Provider
calls or production mutations occur in these tests.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.owner_finality_preflight import (
    KnowledgeSnapshot,
    knowledge_reuse_gaps,
    owner_finality_preflight,
    reconcile_model_finality,
    rule_snapshot,
    skill_snapshot,
    verify_evidence_refs,
)
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier
from llm_loop.introspection.tools_skill_files import run_skill_list, run_skill_load
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceLedgerStore,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.skills.loader import write_manifest

RULE = """# Rules

## RULE-AI-01

**规则**：缺失证据必须 HOLD。
**禁止**：不得以旧经验代替当前 EvidenceRef。
"""
SKILL_STEPS = (
    "1. Check current Goal status and version.",
    "2. Check prior Run reason.",
    "3. Verify exact EvidenceRef.",
    "4. Never repeat update_goal for complete Goal.",
    "5. HOLD when evidence is missing.",
)
SKILL = (
    "---\nname: finality-verify\ndescription: strict finality verification\n---\n"
    "## Steps\n" + "\n".join(SKILL_STEPS) + "\n"
    "## Prohibitions\nNever infer Host permission from Skill text.\n"
)


def _evidence(tmp_path: Path):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    owner = OwnerScope(workspace_id=str(tmp_path / "workspace"), session_id="owner-1")
    verifier = TaskEvidenceVerifier(blobs, ledger, owner_resolver=lambda: owner)
    return blobs, ledger, owner, verifier


def _capture(blobs, ledger, owner, stable_id: str = "positive") -> str:
    request = make_capture_request(
        owner=owner,
        stable_capture_id=stable_id,
        raw_observation="verified test evidence\n",
        acquired_at=datetime.now(UTC),
        tool_name="read_file",
        tool_call_id=f"call-{stable_id}",
        source=SourceIdentity(
            kind=SourceKind.FILE,
            locator="fixture/result.txt",
            version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
        ),
        coverage=Coverage(unit="line", start=0, end_exclusive=1, source_complete=True),
        provenance=Provenance(producer="isolated_test"),
    )
    return EvidenceCapture(blobs, ledger).capture(request).evidence_ref.ref


def _knowledge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rule_path = tmp_path / "ai_rules.md"
    rule_path.write_text(RULE, encoding="utf-8")
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", rule_path=rule_path)
    rule = rule_snapshot(searcher.search(kind="rule", query="RULE-AI-01")[0])
    skills_dir = tmp_path / "skills"
    target = skills_dir / "finality-verify"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(SKILL, encoding="utf-8")
    write_manifest(skills_dir)
    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
    host = SimpleNamespace(skills_dir=str(skills_dir))
    listed = run_skill_list(host, {})
    assert listed.status is ToolResultStatus.SUCCESS
    assert "finality-verify" in listed.content
    loaded = run_skill_load(host, {"name": "finality-verify"})
    assert loaded.status is ToolResultStatus.SUCCESS
    skill = skill_snapshot("finality-verify", loaded, required_steps=SKILL_STEPS)
    return rule_path, target / "SKILL.md", searcher, host, rule, skill


def _gaps(rule, skill, *, previous=None):
    return knowledge_reuse_gaps(
        required_rules=["RULE-AI-01"],
        required_skills={"finality-verify": SKILL_STEPS},
        current=[rule, skill],
        previous=previous,
    )


def test_missing_ref_forces_hold_even_if_model_says_verified():
    result = owner_finality_preflight(
        goal_status="active",
        run_status="incomplete",
        evidence_refs=[],
        verifier=None,
    )
    assert result.decision == "HOLD"
    assert result.reason == "evidence_ref_missing"
    corrected = reconcile_model_finality(result, "NO_WRITE_VERIFIED")
    assert corrected.decision == "HOLD"
    assert corrected.model_claim_rejected is True


def test_unknown_ref_forces_hold_even_when_goal_complete(tmp_path: Path):
    _blobs, _ledger, _owner, verifier = _evidence(tmp_path)
    missing = "evidence://v1/" + "a" * 64
    result = owner_finality_preflight(
        goal_status="complete",
        run_status="incomplete",
        evidence_refs=[missing],
        verifier=verifier,
    )
    assert result.decision == "HOLD"
    assert result.evidence_status == "unresolved_or_not_authorized"
    assert not result.may_claim_verified
    assert reconcile_model_finality(result, "NO_WRITE_VERIFIED").model_claim_rejected


def test_valid_evidence_complete_goal_never_repeats_update(tmp_path: Path):
    blobs, ledger, owner, verifier = _evidence(tmp_path)
    ref = _capture(blobs, ledger, owner)
    result = owner_finality_preflight(
        goal_status="complete",
        run_status="incomplete",
        evidence_refs=[ref],
        verifier=verifier,
    )
    assert result.decision == "NO_WRITE_VERIFIED"
    assert result.may_claim_verified
    final = reconcile_model_finality(result, "NO_WRITE_VERIFIED")
    assert final.decision == "NO_WRITE_VERIFIED"
    assert not final.model_claim_rejected


def test_active_goal_does_not_gain_completion_from_valid_ref(tmp_path: Path):
    blobs, ledger, owner, verifier = _evidence(tmp_path)
    ref = _capture(blobs, ledger, owner)
    result = owner_finality_preflight(
        goal_status="active",
        run_status="incomplete",
        evidence_refs=[ref],
        verifier=verifier,
    )
    assert result.decision == "PROCEED_READ_ONLY"
    assert reconcile_model_finality(result, "NO_WRITE_VERIFIED").decision == "HOLD"
    assert reconcile_model_finality(result, "PROCEED_READ_ONLY").decision == "PROCEED_READ_ONLY"


def test_unavailable_verifier_and_unknown_goal_are_not_success(tmp_path: Path):
    ref = "evidence://v1/" + "b" * 64
    assert verify_evidence_refs([ref], None) == (
        "verification_unavailable",
        "evidence_verification_unavailable",
    )
    result = owner_finality_preflight(
        goal_status="unknown",
        run_status="completed",
        evidence_refs=[],
        verifier=None,
        evidence_required=False,
    )
    assert result.decision == "HOLD"


def test_exact_rule_and_full_skill_allow_reuse(tmp_path: Path, monkeypatch):
    _, _, _, _, rule, skill = _knowledge(tmp_path, monkeypatch)
    assert rule.complete and skill.complete
    assert skill.integrity == "ok"
    assert skill.required_steps_present == SKILL_STEPS
    assert _gaps(rule, skill) == ()
    assert _gaps(rule, skill, previous=[rule, skill]) == ()


def test_rule_card_and_missing_prior_hydration_block_reuse(tmp_path: Path, monkeypatch):
    _, _, searcher, _, rule, skill = _knowledge(tmp_path, monkeypatch)
    assert _gaps(rule, skill, previous=[]) == (
        "rule:RULE-AI-01:prior_hydration_missing",
        "skill:finality-verify:prior_hydration_missing",
    )
    card = searcher.search(kind="rule", query="授权")
    if card:
        bad = rule_snapshot({**card[0], "hydrated": False, "projection_complete": False})
    else:
        bad = rule_snapshot({"rule_ref": "RULE-AI-01", "content": "summary only"})
    assert not bad.complete
    assert "rule:RULE-AI-01:not_fully_hydrated" in _gaps(bad, skill)


def test_rule_source_change_requires_rehydration(tmp_path: Path, monkeypatch):
    rule_path, _, searcher, _, rule, skill = _knowledge(tmp_path, monkeypatch)
    rule_path.write_text(RULE + "\n## Extra\nNew mandatory rule.\n", encoding="utf-8")
    changed = rule_snapshot(searcher.search(kind="rule", query="RULE-AI-01")[0])
    assert changed.complete
    assert changed.source_version != rule.source_version
    assert "rule:RULE-AI-01:source_changed_rehydrate" in _gaps(
        changed, skill, previous=[rule, skill]
    )


def test_skill_modified_manifest_and_missing_step_fail_closed(tmp_path: Path, monkeypatch):
    _, skill_path, _, host, rule, skill = _knowledge(tmp_path, monkeypatch)
    short = skill_snapshot(
        "finality-verify",
        run_skill_load(host, {"name": "finality-verify"}),
        required_steps=(*SKILL_STEPS, "6. Nonexistent mandatory step."),
    )
    assert not short.complete
    assert "skill:finality-verify:not_fully_hydrated" in _gaps(rule, short)
    skill_path.write_text(SKILL + "\nUnauthorized shortcut\n", encoding="utf-8")
    denied = run_skill_load(host, {"name": "finality-verify"})
    assert denied.status is ToolResultStatus.FAILURE
    changed = skill_snapshot("finality-verify", denied, required_steps=SKILL_STEPS)
    assert not changed.complete
    assert "skill:finality-verify:not_fully_hydrated" in _gaps(rule, changed, previous=[rule, skill])


def test_knowledge_gap_blocks_verified_label_even_with_valid_ref(tmp_path: Path):
    blobs, ledger, owner, verifier = _evidence(tmp_path)
    ref = _capture(blobs, ledger, owner)
    result = owner_finality_preflight(
        goal_status="complete",
        run_status="incomplete",
        evidence_refs=[ref],
        verifier=verifier,
        knowledge_gaps=["skill:finality-verify:required_steps_or_integrity_missing"],
    )
    assert result.decision == "HOLD"
    assert result.reason == "required_knowledge_not_verified"


def test_e1k_must_declare_rule_skill_and_verified_hydration(tmp_path: Path, monkeypatch):
    blobs, ledger, owner, verifier = _evidence(tmp_path)
    ref = _capture(blobs, ledger, owner)
    rule_path, _, searcher, _, rule, skill = _knowledge(tmp_path, monkeypatch)
    absent = owner_finality_preflight(
        goal_status="complete", run_status="incomplete", evidence_refs=[ref],
        verifier=verifier, enforce_knowledge=True,
    )
    assert absent.decision == "HOLD"
    assert "knowledge:required_contract_or_hydration_missing" in absent.knowledge_gaps
    complete = owner_finality_preflight(
        goal_status="complete", run_status="incomplete", evidence_refs=[ref],
        verifier=verifier, enforce_knowledge=True,
        required_rules=["RULE-AI-01"],
        required_skills={"finality-verify": SKILL_STEPS},
        current_knowledge=[rule, skill],
        previous_knowledge=[rule, skill],
    )
    assert complete.decision == "NO_WRITE_VERIFIED"
    # The same previous snapshot is no longer reusable after a source edit.
    rule_path.write_text(RULE + "\nNew mandatory prohibition.\n", encoding="utf-8")
    updated = rule_snapshot(searcher.search(kind="rule", query="RULE-AI-01")[0])
    stale = owner_finality_preflight(
        goal_status="complete", run_status="incomplete", evidence_refs=[ref],
        verifier=verifier, enforce_knowledge=True,
        required_rules=["RULE-AI-01"],
        required_skills={"finality-verify": SKILL_STEPS},
        current_knowledge=[updated, skill],
        previous_knowledge=[rule, skill],
    )
    assert stale.decision == "HOLD"
    assert "rule:RULE-AI-01:source_changed_rehydrate" in stale.knowledge_gaps


def test_skill_snapshot_json_roundtrip_does_not_false_invalidate_reuse(tmp_path: Path, monkeypatch):
    _, _, _, _, rule, skill = _knowledge(tmp_path, monkeypatch)
    wire = json.loads(json.dumps(asdict(skill)))
    restored = KnowledgeSnapshot(**wire)
    assert restored.required_steps_present == SKILL_STEPS
    assert _gaps(rule, skill, previous=[rule, restored]) == ()


def test_reordered_required_skill_steps_are_not_accepted(tmp_path: Path, monkeypatch):
    _, skill_path, _, host, rule, skill = _knowledge(tmp_path, monkeypatch)
    reordered = SKILL.replace(SKILL_STEPS[0], "__STEP1__")
    reordered = reordered.replace(SKILL_STEPS[1], SKILL_STEPS[0])
    reordered = reordered.replace("__STEP1__", SKILL_STEPS[1])
    skill_path.write_text(reordered, encoding="utf-8")
    write_manifest(skill_path.parent.parent)
    loaded = run_skill_load(host, {"name": "finality-verify"})
    assert loaded.status is ToolResultStatus.SUCCESS
    invalid = skill_snapshot("finality-verify", loaded, required_steps=SKILL_STEPS)
    assert not invalid.complete
    assert "skill:finality-verify:not_fully_hydrated" in _gaps(rule, invalid, previous=[rule, skill])
