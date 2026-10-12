"""Real macOS sandbox-exec process tests, offline FakeLLM and fake Task store only."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

from llm_loop.assurance.p1_review_supervisor import OfflineReviewSupervisor
from llm_loop.assurance.task_control_store import (
    InvalidContractError,
    PermissionDeniedError,
    TaskControlStore,
)

SHA = hashlib.sha256(b"P1 task acceptance frozen").hexdigest()
CANDIDATE = b"# Offline reviewer artifact\nThe candidate is untrusted data.\n"


@pytest.fixture
def p1(tmp_path: Path):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        pytest.skip("P1 OS sandbox negative requires macOS sandbox-exec")
    base = tmp_path / "assurance-p1-root"
    owner_b = tmp_path / "other-owner-private"
    owner_b.mkdir()
    (owner_b / "secret.txt").write_text("SYNTHETIC_OWNER_B_NOT_AUTHORIZED", encoding="utf-8")
    control = TaskControlStore(tmp_path / "control-store")
    control.create_once("p1_task", "p1_owner", hashlib.sha256(CANDIDATE).hexdigest(), SHA, "p1_grant")
    supervisor = OfflineReviewSupervisor(
        base, control, "p1_owner", denied_read_roots=(owner_b,),
        offline_experiment_approved=True,
    )
    workers = []
    try:
        yield supervisor, control, workers
    finally:
        for worker in workers:
            worker.cancel_for_test_cleanup()


def _start(p1, mode: str):
    sup, _, workers = p1
    handle = sup.start("p1_task", CANDIDATE, mode=mode)
    workers.append(handle)
    return handle


def _stop(control: TaskControlStore) -> None:
    state = control.read_exact("p1_task", "p1_owner")
    control.append_intent_cas(
        "p1_task", "p1_owner", state.revision, "stop_001",
        "STOP", hashlib.sha256(b"stop review").hexdigest(),
        stop_scope="TASK_STICKY",
    )


def _wait_for(path: Path, seconds: float = 7.0) -> None:
    until = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < until:
        time.sleep(0.03)
    assert path.exists(), f"timeout waiting for true subprocess milestone: {path}"


def test_prior_executor_process_exit_does_not_cancel_independent_review(p1) -> None:
    # The previous executor was a separate process and is already *terminated*
    # before the trusted Task-level Supervisor launches the review process.
    executor = subprocess.run(
        [sys.executable, "-c", "print('executor normal final')"],
        capture_output=True, text=True, timeout=4, check=True,
    )
    assert executor.returncode == 0
    child = _start(p1, "read_then_final")
    result = child.wait(timeout_s=9.0)
    if result.phase == "FAILED_OR_UNBOUND_RECEIPT":
        pytest.fail((child.root / "scratch" / "stderr.log").read_text())
    assert result.physical_process_ended
    assert result.process_exit == 0
    assert result.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    assert result.worker_receipt is not None
    assert result.worker_receipt["tool_names_attempted"] == ["review_frozen_candidate"]
    assert result.worker_receipt["reviewer_session_id"] == child.reviewer_session_id


def test_reviewer_running_when_executor_process_normally_exits(p1) -> None:
    child = _start(p1, "block_until_release")
    _wait_for(child.root / "scratch" / "entered_block.flag")
    prior_executor = subprocess.run(
        [sys.executable, "-c", "raise SystemExit(0)"],
        capture_output=True, timeout=3, check=True,
    )
    assert prior_executor.returncode == 0
    assert child.observe().phase == "RUNNING"
    (child.root / "scratch" / "release.flag").write_text("release offline model", encoding="utf-8")
    result = child.wait(timeout_s=7)
    assert result.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"


def test_model_shell_attempt_denied_even_when_llm_claims_completion(p1) -> None:
    child = _start(p1, "unsafe_tool")
    result = child.wait(timeout_s=9.0)
    if result.phase == "FAILED_OR_UNBOUND_RECEIPT":
        pytest.fail((child.root / "scratch" / "stderr.log").read_text())
    assert result.phase == "UNQUALIFIED_UNSAFE_TOOL_ATTEMPT"
    assert result.worker_receipt is not None
    assert result.worker_receipt["tool_names_attempted"] == ["execute_command"]


def test_os_sandbox_blocks_write_network_and_nested_process_escape(p1) -> None:
    child = _start(p1, "os_probe")
    result = child.wait(timeout_s=9.0)
    if result.phase == "FAILED_OR_UNBOUND_RECEIPT":
        pytest.fail((child.root / "scratch" / "stderr.log").read_text())
    assert result.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    assert result.worker_receipt is not None
    assert result.worker_receipt["os_probe"] == {
        "candidate_write_denied": True,
        "subprocess_write_denied": True,
        "network_denied": True,
        "scratch_write_allowed": True,
        "other_owner_read_denied": True,
        "subprocess_other_owner_read_denied": True,
        "symlink_other_owner_read_denied": True,
        "process_fork_denied": True,
        "subprocess_spawn_denied": True,
    }
    assert (child.root / "immutable" / "candidate.txt").read_bytes() == CANDIDATE


def test_persistent_user_stop_kills_blocked_child_and_no_review_pass(p1) -> None:
    _, control, _ = p1
    child = _start(p1, "block_until_release")
    _wait_for(child.root / "scratch" / "entered_block.flag")
    assert child.observe().phase == "RUNNING"
    _stop(control)
    result = child.wait(timeout_s=6)
    assert result.physical_process_ended
    assert result.phase == "STOPPED_PROCESS_CONFIRMED_EXTERNAL_EFFECTS_NOT_PROVEN"
    assert result.worker_receipt is None
    assert control.read_exact("p1_task", "p1_owner").state == "STOP_REQUESTED"
    with pytest.raises(InvalidContractError):
        p1[0].start("p1_task", CANDIDATE, mode="read_then_final")


def test_uncooperative_child_escalated_to_os_kill_after_stop(p1) -> None:
    _, control, _ = p1
    child = _start(p1, "ignore_term")
    _wait_for(child.root / "scratch" / "entered_block.flag")
    _stop(control)
    result = child.wait(timeout_s=6)
    assert result.physical_process_ended
    assert result.worker_receipt is None
    assert result.phase == "STOPPED_PROCESS_CONFIRMED_EXTERNAL_EFFECTS_NOT_PROVEN"
    assert result.process_exit != 0


def test_post_review_candidate_drift_disqualifies_existing_receipt(p1) -> None:
    child = _start(p1, "read_then_final")
    result = child.wait(timeout_s=7)
    assert result.phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
    candidate_path = child.root / "immutable" / "candidate.txt"
    candidate_path.chmod(0o600)  # trusted supervisor changes an out-of-band artifact
    candidate_path.write_text("candidate drift after review", encoding="utf-8")
    assert child.observe().phase == "UNQUALIFIED_CANDIDATE_DRIFT"


def test_stop_is_scoped_to_its_exact_task_not_neighbor_review(p1) -> None:
    supervisor, control, workers = p1
    control.create_once(
        "other_task", "p1_owner", hashlib.sha256(CANDIDATE).hexdigest(),
        SHA, "p1_grant",
    )
    child = supervisor.start("other_task", CANDIDATE, mode="block_until_release")
    workers.append(child)
    _wait_for(child.root / "scratch" / "entered_block.flag")
    _stop(control)  # stops p1_task, not other_task
    assert child.observe().phase == "RUNNING"
    (child.root / "scratch" / "release.flag").write_text("release", encoding="utf-8")
    assert child.wait(timeout_s=7).phase == "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"


def test_owner_and_opt_in_enforced_before_spawn(p1, monkeypatch) -> None:
    _, control, _ = p1
    with pytest.raises(PermissionDeniedError):
        OfflineReviewSupervisor(
            p1[0].root, control, "other_owner",
            denied_read_roots=p1[0].denied_read_roots,
            offline_experiment_approved=True,
        ).start("p1_task", CANDIDATE, mode="read_then_final")
    # Even an attacker setting the old environment switch cannot opt this
    # execution path in without the trusted caller's typed flag.
    monkeypatch.setenv("LFL_P1_OFFLINE_EXPERIMENT", "1")
    with pytest.raises(InvalidContractError, match="opt-in"):
        OfflineReviewSupervisor(
            p1[0].root, control, "p1_owner",
            denied_read_roots=p1[0].denied_read_roots,
        )


def test_durable_stop_during_candidate_preparation_cannot_launch_reviewer(
    p1, monkeypatch,
) -> None:
    """Inject STOP after snapshot but before sandbox-exec dispatch.

    This does not prove atomic STOP vs physical launch after the last check;
    it closes an avoidable long preparation-window gap.
    """
    import llm_loop.assurance.p1_review_supervisor as supervisor_module

    supervisor, control, _ = p1
    real_writer = supervisor_module._atomic_json

    def injected_stop(path, document):
        real_writer(path, document)
        if path.name == "spec.json":
            _stop(control)

    def no_spawn(*_args, **_kwargs):
        pytest.fail("STOP committed during preparation; no process may be launched")

    monkeypatch.setattr(supervisor_module, "_atomic_json", injected_stop)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", no_spawn)
    with pytest.raises(InvalidContractError, match="STOP.*preparation"):
        supervisor.start("p1_task", CANDIDATE, mode="read_then_final")
