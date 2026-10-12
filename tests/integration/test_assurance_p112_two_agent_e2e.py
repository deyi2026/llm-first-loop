"""P1.12 functional dual-agent vertical slice, not another authority mock.

Real LFL Executor LoopEngine uses a *closed* local artifact writer. The
executor run terminates; a separate OS process then runs an independent
reviewer LoopEngine via the P1 macOS sandbox, and an isolated P1.8 Docker
reviewer independently verifies the bounded acceptance facts.
The host Gate handles PASS/FAIL/STOP/unsafe attempt without any release.
Only injected FakeLLM models and synthetic files; zero real provider calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import llm_loop.assurance.p112_offline_vertical as vertical
from llm_loop.assurance.p1_review_supervisor import OfflineReviewSupervisor
from llm_loop.assurance.p16_host_broker import (
    EvidenceSlice,
    OfflineHostReviewBroker,
    OfflineReviewRequest,
    OnceOnlyBrokerJournal,
    OwnerEvidenceCatalog,
)
from llm_loop.assurance.p18_bounded_reviewer import (
    OfflineBoundedReviewer,
    expected_review_operation_id,
)
from llm_loop.assurance.p112_functional_evidence import (
    BASE_IMAGE,
    frozen_merge_acceptance,
)
from llm_loop.assurance.p112_offline_vertical import (
    OfflineExecutorWriteTool,
    evaluate_offline_delivery,
)
from llm_loop.assurance.task_control_store import LeaseRef, TaskControlStore
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.fleet.store import FleetStore
from llm_loop.llm.client import LLMResponse

IMAGE = os.environ.get("LFL_ASSURANCE_P18_IMAGE_REF", "")
OPT_IN = os.environ.get("LFL_ASSURANCE_REAL_DOCKER_PROBE") == "1"
pytestmark = pytest.mark.skipif(
    not (
        OPT_IN and sys.platform == "darwin"
        and Path("/usr/bin/sandbox-exec").is_file()
        and re.fullmatch(r"lfl/assurance-p18-reviewer@sha256:[0-9a-f]{64}", IMAGE)
    ),
    reason="requires explicit offline real macOS process and pinned P1.8 Docker",
)

GOOD_SOURCE = b"def add(a, b):\n    return a + b\n"
BAD_SOURCE = b"def add(a, b):\n    return a - b\n"
TASK = "task_p112"
OWNER = "owner_p112"
FUNCTIONAL_FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "assurance_p112_functional"
)
MERGE_GOOD = (FUNCTIONAL_FIXTURES / "glm53_candidate.txt").read_bytes()
MERGE_MUTANT = (FUNCTIONAL_FIXTURES / "touching_boundary_mutant.txt").read_bytes()


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _json(data: dict) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"),
    ).encode("ascii")


def _acceptance() -> dict:
    return {
        "schema": "lfl.dual_assurance.p18_acceptance/v1",
        "checks": [
            {"id": "required_addition", "type": "CONTAINS_LITERAL",
             "value": "return a + b"},
            {"id": "no_shell_escape", "type": "EXCLUDES_LITERAL",
             "value": "os.system("},
        ],
    }


def _execute_in_real_loopengine(build_test_engine, root: Path, source: bytes):
    engine, fake = build_test_engine([
        LLMResponse(
            content="", provider="fake",
            tool_calls=[ToolCall(
                id="executor_write_001", name="write_offline_candidate",
                arguments={"content": source.decode("utf-8")},
            )],
        ),
        LLMResponse(
            content="Executor finished local candidate only", tool_calls=[],
            provider="fake",
        ),
    ])
    engine.registry.dispose()
    tool = OfflineExecutorWriteTool(root / "assurance-p112-executor-root")
    engine.registry.register(tool)
    assert engine.registry.names() == ["write_offline_candidate"]
    sid = engine.session.create()
    final = engine.run(
        sid, "Implement an add(a,b) function in one offline source file.",
    )
    assert final.final_answer and "Executor finished" in final.final_answer
    assert len(fake.calls) == 2
    assert tool.path.read_bytes() == source
    assert final.tool_calls and final.tool_calls[0]["name"] == tool.name
    return sid, tool.path, tool


def _task_broker(root: Path, candidate: bytes, acceptance: dict):
    sha = _digest(candidate)
    ahash = _digest(_json(acceptance))
    control = TaskControlStore(root / "task_control")
    control.create_once(TASK, OWNER, sha, ahash, "grant_p112")
    fleet = FleetStore(root / "fleet")
    fleet.create_project("project_p112")
    workspace = fleet.create_workspace(
        "project_p112", str(root / "synthetic_workspace"), sha,
    )
    lease = fleet.acquire_lease(
        "project_p112", workspace.workspace_id,
        owner_id=OWNER, worker_id="worker_p112", ttl_seconds=90.0,
    )
    ref = LeaseRef(
        workspace.workspace_id, lease.lease_id, lease.generation,
        lease.worker_id, "generation_p112",
    )

    def current(_: LeaseRef) -> bool:
        return fleet.lease_is_current(lease)

    staged = control.prepare_binding_cas(TASK, OWNER, 0, ref, current)
    actual = control.commit_binding_cas(
        TASK, OWNER, staged.revision, ref, current,
    )
    catalog = OwnerEvidenceCatalog([
        EvidenceSlice(
            "p112_test_receipt", TASK, OWNER, sha,
            b"Synthetic Executor task received for independent bounded review",
        ),
    ])
    broker = OfflineHostReviewBroker(
        control, fleet, catalog, OnceOnlyBrokerJournal(root / "review_journal"),
    )
    draft = OfflineReviewRequest(
        "review_placeholder", TASK, OWNER, "grant_p112",
        actual.control_epoch, actual.revision, sha,
        ("p112_test_receipt",), lease, ref,
    )
    request = replace(
        draft, operation_id=expected_review_operation_id(draft, ahash),
    )
    return control, broker, request


def _scenario(
    tmp_path: Path, build_test_engine, *, candidate: bytes,
    reviewer_mode: str = "read_then_final",
    stop_at_gate: bool = False,
    tamper_at_gate: bool = False,
    acceptance_override: dict | None = None,
    functional_image_ref: str = BASE_IMAGE,
):
    sid, path, tool = _execute_in_real_loopengine(build_test_engine, tmp_path, candidate)
    content = path.read_bytes()
    acceptance = acceptance_override if acceptance_override is not None else _acceptance()
    control, broker, request = _task_broker(tmp_path, content, acceptance)
    forbidden = tmp_path / "other_owner_private"
    forbidden.mkdir()
    (forbidden / "private.txt").write_text("NOT_AUTHORIZED", encoding="utf-8")
    supervisor = OfflineReviewSupervisor(
        tmp_path / "assurance-p1-root", control, OWNER,
        denied_read_roots=(forbidden,), offline_experiment_approved=True,
    )
    process = supervisor.start(TASK, content, mode=reviewer_mode)
    try:
        process_result = process.wait(timeout_s=13.0)
        assert process_result.physical_process_ended, process_result
        reviewer = OfflineBoundedReviewer(
            broker, image_ref=IMAGE,
            experimental_root=tmp_path / "assurance-p18-root",
        )
        bounded = reviewer.review_once(
            request, candidate=content, acceptance=acceptance,
        )
        if tamper_at_gate:
            path.write_bytes(b"# malicious external post-review drift\n")
        if stop_at_gate:
            control.append_intent_cas(
                TASK, OWNER, control.read_exact(TASK, OWNER).revision,
                "stop_p112_before_gate", "STOP", _digest(b"stop task p112"),
            )
        gate = evaluate_offline_delivery(
            executor_session_id=sid, candidate_path=path,
            broker=broker, request=request,
            reviewer_process=process, reviewer_result=process_result,
            bounded_result=bounded,
            functional_image_ref=functional_image_ref,
        )
        return gate, bounded, process_result, tool
    finally:
        process.cancel_for_test_cleanup()


def test_executor_to_independent_reviewer_to_local_gate_pass(
    tmp_path, build_test_engine,
):
    gate, bounded, process, tool = _scenario(
        tmp_path, build_test_engine, candidate=GOOD_SOURCE,
    )
    assert process.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    assert process.worker_receipt is not None
    assert process.worker_receipt["tool_names_attempted"] == ["review_frozen_candidate"]
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "LOCAL_EXPERIMENT_VERIFIED"
    assert gate.executor_session_id != gate.reviewer_session_id
    assert gate.candidate_sha256 == _digest(tool.path.read_bytes())
    assert not gate.may_publish and not gate.may_dispatch_production_effect
    print("P112_E2E_PASS: actual LoopEngine Executor -> independent LoopEngine process -> Docker reviewer -> local Gate")


def test_bad_executor_output_is_vetoed_by_independent_reviewer(
    tmp_path, build_test_engine,
):
    gate, bounded, process, _ = _scenario(
        tmp_path, build_test_engine, candidate=BAD_SOURCE,
    )
    assert process.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    assert bounded.verdict == "FAIL"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "INDEPENDENT_BOUNDED_ACCEPTANCE_FAILED_OR_UNKNOWN"
    assert not gate.may_publish


def test_user_stop_after_both_reviewers_prevents_local_acceptance(
    tmp_path, build_test_engine,
):
    gate, bounded, process, _ = _scenario(
        tmp_path, build_test_engine, candidate=GOOD_SOURCE,
        stop_at_gate=True,
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert process.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    assert gate.verdict == "BLOCKED" and gate.reason == "TASK_STOP_OR_FLEET_FENCED"


def test_executor_artifact_tamper_after_both_reviews_blocks_gate(
    tmp_path, build_test_engine,
):
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=GOOD_SOURCE,
        tamper_at_gate=True,
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED" and gate.reason == "EXECUTOR_CANDIDATE_DRIFT"


def test_reviewer_unauthorized_shell_attempt_vetoes_even_valid_candidate(
    tmp_path, build_test_engine,
):
    gate, bounded, process, _ = _scenario(
        tmp_path, build_test_engine,
        candidate=GOOD_SOURCE, reviewer_mode="unsafe_tool",
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert process.phase == "UNQUALIFIED_UNSAFE_TOOL_ATTEMPT"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "REVIEWER_SESSION_OR_PROCESS_UNQUALIFIED"


def test_writer_is_one_shot_and_cannot_modify_same_output(tmp_path):
    tool = OfflineExecutorWriteTool(
        tmp_path / "assurance-p112-executor-root",
    )
    first = tool.execute(content=GOOD_SOURCE.decode("utf-8"))
    assert first.status is ToolResultStatus.SUCCESS
    second = tool.execute(content=BAD_SOURCE.decode("utf-8"))
    assert second.status is ToolResultStatus.FAILURE
    assert tool.path.read_bytes() == GOOD_SOURCE
    untrusted = tool.execute(
        content=GOOD_SOURCE.decode("utf-8"), path="/etc/passwd",
    )
    assert untrusted.status is ToolResultStatus.FAILURE
    assert tool.path.read_bytes() == GOOD_SOURCE


def test_failed_work_revised_as_new_explicit_attempt_is_re_reviewed(
    tmp_path, build_test_engine,
):
    """Correction is a fresh attempt, NEVER replaying a settled guest attempt."""
    bad, _, _, _ = _scenario(
        tmp_path / "attempt_1", build_test_engine, candidate=BAD_SOURCE,
    )
    assert bad.verdict == "BLOCKED" and not bad.may_publish
    corrected, bounded, _, tool = _scenario(
        tmp_path / "attempt_2", build_test_engine, candidate=GOOD_SOURCE,
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert corrected.verdict == "LOCAL_EXPERIMENT_VERIFIED"
    assert corrected.candidate_sha256 != bad.candidate_sha256
    assert corrected.executor_session_id != bad.executor_session_id
    assert corrected.reviewer_session_id != bad.reviewer_session_id
    assert tool.path.read_bytes() == GOOD_SOURCE
    assert not corrected.may_publish and not bad.may_publish


def test_semantic_review_required_is_uncertain_not_an_automatic_pass(
    tmp_path, build_test_engine,
):
    checks = {
        "schema": "lfl.dual_assurance.p18_acceptance/v1",
        "checks": [{
            "id": "semantic_correctness", "type": "SEMANTIC_REVIEW_REQUIRED",
            "value": "Independent functional proof of the addition algorithm",
        }],
    }
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine,
        candidate=GOOD_SOURCE, acceptance_override=checks,
    )
    assert bounded.verdict == "UNCERTAIN"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "INDEPENDENT_BOUNDED_ACCEPTANCE_FAILED_OR_UNKNOWN"


def test_real_docker_host_gate_accepts_frozen_glm53_good_algorithm(
    tmp_path, build_test_engine,
):
    assert _digest(MERGE_GOOD) == (
        "082802ddc8d73e80fbf0fa2c301740797bf0b97ad589d030ae80f168c6d7db66"
    )
    gate, bounded, process, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_GOOD,
        acceptance_override=frozen_merge_acceptance(),
    )
    assert process.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "LOCAL_EXPERIMENT_VERIFIED"
    assert gate.reason == "OFFLINE_FUNCTIONAL_EVIDENCE_VERIFIED"
    assert gate.functional_verdict == "PASS_FUNCTIONAL"
    assert gate.functional_passed == 311
    assert gate.functional_receipt_sha256
    assert gate.may_publish is False


def test_real_docker_host_gate_vetoes_mutant_even_if_static_reviewer_passes(
    tmp_path, build_test_engine,
):
    assert _digest(MERGE_MUTANT) == (
        "53ffa7800bcd8d39f6702dd8b90f75b18e3bb35e677d52e5348ee590348cdb8b"
    )
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_MUTANT,
        acceptance_override=frozen_merge_acceptance(),
    )
    assert bounded.verdict == "PASS_BOUNDED"  # old structural semantic false positive
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "FUNCTIONAL_ORACLE_FAIL"
    assert gate.functional_verdict == "FAIL_FUNCTIONAL"
    assert gate.functional_passed == 239
    assert gate.may_publish is False


def test_model_self_report_pass_functional_cannot_replace_host_oracle(
    tmp_path, build_test_engine,
):
    fraudulent = (
        b'def merge_closed_intervals(intervals):\n'
        b'    merged = "PASS_FUNCTIONAL"\n'
        b'    return merged\n'
    )
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=fraudulent,
        acceptance_override=frozen_merge_acceptance(),
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "FUNCTIONAL_ORACLE_FAIL"
    assert gate.functional_verdict == "FAIL_FUNCTIONAL"
    assert gate.functional_passed == 0
    assert not gate.may_publish


def test_real_docker_stop_revokes_functional_acceptance_even_with_good_source(
    tmp_path, build_test_engine,
):
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_GOOD,
        acceptance_override=frozen_merge_acceptance(),
        stop_at_gate=True,
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "TASK_STOP_OR_FLEET_FENCED"
    assert gate.functional_verdict is None  # STOP blocks before Docker


def test_missing_real_docker_evidence_fails_closed_no_model_pass_override(
    tmp_path, build_test_engine,
):
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_GOOD,
        acceptance_override=frozen_merge_acceptance(),
        functional_image_ref="python@sha256:" + "0" * 64,
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "FUNCTIONAL_EVIDENCE_UNKNOWN"
    assert gate.functional_verdict == "UNKNOWN"
    assert gate.functional_receipt_sha256 is None


def test_different_unfrozen_checklist_cannot_opt_out_of_host_functional_gate(
    tmp_path, build_test_engine,
):
    alternate = {
        "schema": "lfl.dual_assurance.p18_acceptance/v1",
        "checks": [{"id": "deceptive_pass", "type": "CONTAINS_LITERAL",
                    "value": "def merge_closed_intervals("}],
    }
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_MUTANT,
        acceptance_override=alternate,
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "FUNCTIONAL_ACCEPTANCE_NOT_FROZEN"


def test_candidate_changed_during_real_functional_docker_run_is_vetoed(
    tmp_path, build_test_engine, monkeypatch,
):
    real_review = vertical.run_host_functional_review

    def review_then_tamper(candidate, **kwargs):
        evidence = real_review(candidate, **kwargs)
        assert evidence.verdict == "PASS_FUNCTIONAL"
        path = tmp_path / "assurance-p112-executor-root" / "candidate.py"
        path.write_bytes(MERGE_MUTANT)
        return evidence

    monkeypatch.setattr(vertical, "run_host_functional_review", review_then_tamper)
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_GOOD,
        acceptance_override=frozen_merge_acceptance(),
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "EXECUTOR_CANDIDATE_DRIFT"


def test_stop_during_real_functional_docker_review_cannot_be_overridden(
    tmp_path, build_test_engine, monkeypatch,
):
    real_review = vertical.run_host_functional_review

    def review_then_stop(candidate, **kwargs):
        evidence = real_review(candidate, **kwargs)
        assert evidence.verdict == "PASS_FUNCTIONAL"
        control = TaskControlStore(tmp_path / "task_control")
        current = control.read_exact(TASK, OWNER)
        control.append_intent_cas(
            TASK, OWNER, current.revision,
            "stop_during_functional_review", "STOP", _digest(b"stop p112 mid-review"),
        )
        return evidence

    monkeypatch.setattr(vertical, "run_host_functional_review", review_then_stop)
    gate, bounded, _, _ = _scenario(
        tmp_path, build_test_engine, candidate=MERGE_GOOD,
        acceptance_override=frozen_merge_acceptance(),
    )
    assert bounded.verdict == "PASS_BOUNDED"
    assert gate.verdict == "BLOCKED"
    assert gate.reason == "TASK_STOP_OR_FLEET_FENCED"
