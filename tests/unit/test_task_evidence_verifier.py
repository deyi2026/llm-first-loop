"""P1 Task evidence authenticity verification.

These tests lock only mechanical properties of already-declared Evidence refs:
owner scope, record/blob presence and immutable blob integrity.  They deliberately
do not score freshness, relevance, sufficiency, or task completion semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_evidence import (
    TaskEvidenceVerificationError,
    TaskEvidenceVerifier,
)
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_task import run_task_update
from llm_loop.memory.evidence import (
    AvailabilityState,
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceLedgerStore,
    EvidenceState,
    FreshnessState,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)


def _capture(
    blobs: BlobStore,
    ledger: EvidenceLedgerStore,
    owner: OwnerScope,
    *,
    stable_id: str,
    text: str = "observed truth\n",
):
    request = make_capture_request(
        owner=owner,
        stable_capture_id=stable_id,
        raw_observation=text,
        acquired_at=datetime.now(UTC),
        tool_name="read_file",
        tool_call_id=f"call-{stable_id}",
        source=SourceIdentity(
            kind=SourceKind.FILE,
            locator="notes/a.txt",
            version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
        ),
        coverage=Coverage(unit="line", start=0, end_exclusive=1, source_complete=True),
        provenance=Provenance(producer="test"),
    )
    return EvidenceCapture(blobs, ledger).capture(request).evidence_ref


@pytest.fixture()
def evidence_env(tmp_path: Path):
    blobs = BlobStore(tmp_path / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "evidence" / "ledger")
    owner = OwnerScope(workspace_id=str(tmp_path / "workspace"), session_id="sid-owner")
    ref = _capture(blobs, ledger, owner, stable_id="valid")
    verifier = TaskEvidenceVerifier(blobs, ledger, owner_resolver=lambda: owner)
    return blobs, ledger, owner, ref, verifier


def test_verifier_accepts_authorized_intact_ref_even_when_stale(evidence_env):
    _blobs, ledger, owner, ref, verifier = evidence_env
    ledger.update_state(
        owner,
        EvidenceState(
            evidence_ref=ref,
            freshness=FreshnessState.STALE,
            availability=AvailabilityState.AVAILABLE,
            updated_at=datetime.now(UTC).isoformat(),
        ),
    )

    report = verifier.verify([ref.ref])

    assert report.status == "verified"
    assert report.checked_count == 1
    assert report.refs_digest
    assert report.failing_ref == ""


def test_verifier_hides_unknown_vs_other_owner(evidence_env, tmp_path: Path):
    blobs, ledger, _owner, _ref, verifier = evidence_env
    other = OwnerScope(workspace_id=str(tmp_path / "workspace"), session_id="sid-other")
    other_ref = _capture(blobs, ledger, other, stable_id="other")
    unknown_ref = "evidence://v1/" + "a" * 64

    other_report = verifier.verify([other_ref.ref])
    unknown_report = verifier.verify([unknown_ref])

    assert other_report.status == "unresolved_or_not_authorized"
    assert unknown_report.status == "unresolved_or_not_authorized"


def test_verifier_distinguishes_missing_and_corrupt_blob(evidence_env):
    blobs, ledger, owner, ref, verifier = evidence_env
    record = ledger.require_authorized(owner, ref)
    assert blobs.delete(record.blob_ref) is True
    assert verifier.verify([ref.ref]).status == "blob_missing"

    ref2 = _capture(blobs, ledger, owner, stable_id="corrupt")
    record2 = ledger.require_authorized(owner, ref2)
    blob_path = (
        blobs.root / "sha256" / record2.blob_ref.sha256[:2] / f"{record2.blob_ref.sha256}.blob"
    )
    blob_path.write_bytes(b"tampered")
    assert verifier.verify([ref2.ref]).status == "integrity_failed"


def test_verifier_reports_unsupported_ref_and_unavailable_owner(evidence_env):
    blobs, ledger, _owner, _ref, _verifier = evidence_env
    verifier = TaskEvidenceVerifier(
        blobs,
        ledger,
        owner_resolver=lambda: (_ for _ in ()).throw(RuntimeError("no current owner")),
    )

    assert verifier.verify(["evidence://legacy/ref"]).status == "unsupported_ref"
    assert verifier.verify(["evidence://v1/" + "b" * 64]).status == "verification_unavailable"


def test_task_store_rejects_unverified_done_without_persisting(evidence_env, tmp_path: Path):
    _blobs, _ledger, _owner, _ref, verifier = evidence_env
    store = TaskStore(tmp_path / "audit", evidence_verifier=verifier)
    task = store.create("G1", "verify", acceptance=["mechanical evidence exists"])
    store.update("G1", task.task_id, status="in_progress")
    missing = "evidence://v1/" + "c" * 64

    with pytest.raises(TaskEvidenceVerificationError) as exc:
        store.update("G1", task.task_id, status="done", evidence_refs=[missing])

    assert exc.value.status == "unresolved_or_not_authorized"
    current = store.get("G1", task.task_id)
    assert current is not None
    assert current.status == "in_progress"
    assert current.evidence_refs == []


def test_task_store_records_successful_verification_metadata(evidence_env, tmp_path: Path):
    _blobs, _ledger, _owner, ref, verifier = evidence_env
    store = TaskStore(tmp_path / "audit", evidence_verifier=verifier)
    task = store.create("G1", "verify", acceptance=["mechanical evidence exists"])
    store.update("G1", task.task_id, status="in_progress")

    done = store.update("G1", task.task_id, status="done", evidence_refs=[ref.ref])

    assert done.status == "done"
    assert done.evidence_verification_status == "verified"
    assert done.evidence_verified_at
    assert done.evidence_refs_digest


def test_done_ref_change_is_verified_and_required_refs_cannot_be_removed(
    evidence_env, tmp_path: Path
):
    _blobs, _ledger, _owner, ref, verifier = evidence_env
    store = TaskStore(tmp_path / "audit", evidence_verifier=verifier)
    task = store.create(
        "G1",
        "verify",
        acceptance=["mechanical evidence exists"],
        evidence_required=True,
    )
    store.update("G1", task.task_id, status="in_progress")
    store.update("G1", task.task_id, status="done", evidence_refs=[ref.ref])
    missing = "evidence://v1/" + "d" * 64

    with pytest.raises(TaskEvidenceVerificationError):
        store.update("G1", task.task_id, evidence_refs=[missing])
    with pytest.raises(ValueError, match="evidence_required=true"):
        store.update("G1", task.task_id, evidence_refs=[])

    current = store.get("G1", task.task_id)
    assert current is not None
    assert current.status == "done"
    assert current.evidence_refs == [ref.ref]


def test_verifier_unavailable_blocks_only_done_records_that_claim_refs(tmp_path: Path):
    store = TaskStore(tmp_path / "audit", evidence_verifier=None)
    task = store.create("G1", "optional", acceptance=["done"])
    store.update("G1", task.task_id, status="in_progress")
    done = store.update("G1", task.task_id, status="done")
    assert done.status == "done"

    task2 = store.create("G1", "claims-ref", acceptance=["done"])
    store.update("G1", task2.task_id, status="in_progress")
    with pytest.raises(TaskEvidenceVerificationError) as exc:
        store.update(
            "G1",
            task2.task_id,
            status="done",
            evidence_refs=["evidence://v1/" + "e" * 64],
        )
    assert exc.value.status == "verification_unavailable"


def test_task_update_off_mode_reports_unavailable_without_exposing_ref(tmp_path: Path):
    audit = tmp_path / "audit"
    goal = GoalStore(audit).create("P1 production tool path")
    store = TaskStore(audit)
    task = store.create(goal.id, "claim ref", acceptance=["done"])
    store.update(goal.id, task.task_id, status="in_progress")
    claimed_ref = "evidence://v1/" + "f" * 64
    host = SimpleNamespace(
        audit_dir=audit,
        ctx=SimpleNamespace(task_evidence_verifier=None),
    )

    result = run_task_update(
        None,
        host,
        {
            "goal_id": goal.id,
            "task_id": task.task_id,
            "status": "done",
            "evidence_refs": [claimed_ref],
        },
    )

    assert result.status == ToolResultStatus.FAILURE
    assert "verification_unavailable" in result.content
    assert claimed_ref not in result.content
    current = TaskStore(audit).get(goal.id, task.task_id)
    assert current is not None and current.status == "in_progress"
