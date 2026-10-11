"""P1.7 cooperative STOP/outbound admission test: FakeRemote only."""

from __future__ import annotations

import hashlib
import os
import select
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from llm_loop.assurance.offline_effects import FakeRemote
from llm_loop.assurance.p16_host_broker import (
    BrokerDeniedError,
    OfflineHostReviewBroker,
    OfflineReviewRequest,
    OnceOnlyBrokerJournal,
    OwnerEvidenceCatalog,
    ReplayForbiddenError,
)
from llm_loop.assurance.p17_stop_dispatch_gate import OfflineStopDispatchGate
from llm_loop.assurance.task_control_store import LeaseRef, TaskControlStore
from llm_loop.fleet.store import FleetStore

SHA = hashlib.sha256(b"synthetic task input").hexdigest()
ACTION = hashlib.sha256(b"synthetic fake remote action").hexdigest()


@pytest.fixture
def gate_setup(tmp_path: Path):
    root = tmp_path / "assurance-p17-root"
    ctl = TaskControlStore(root / "control")
    ctl.create_once("task_01", "owner_01", SHA, hashlib.sha256(b"acceptance").hexdigest(), "grant_01")
    fleet = FleetStore(root / "fleet")
    fleet.create_project("project_01")
    ws = fleet.create_workspace("project_01", str(root / "source"), SHA)
    lease = fleet.acquire_lease(
        "project_01", ws.workspace_id,
        owner_id="owner_01", worker_id="worker_01", ttl_seconds=30.0,
    )
    ref = LeaseRef(ws.workspace_id, lease.lease_id, 1, lease.worker_id, "generation_1")

    def verify(_):
        return fleet.lease_is_current(lease)

    prepared = ctl.prepare_binding_cas("task_01", "owner_01", 0, ref, verify)
    bound = ctl.commit_binding_cas("task_01", "owner_01", prepared.revision, ref, verify)
    broker = OfflineHostReviewBroker(
        ctl, fleet, OwnerEvidenceCatalog([]), OnceOnlyBrokerJournal(root / "review_calls"),
    )
    remote = FakeRemote(root / "remote")
    gate = OfflineStopDispatchGate(root=root, broker=broker, remote=remote)
    req = OfflineReviewRequest(
        "review_01", "task_01", "owner_01", "grant_01",
        0, bound.revision, SHA, (), lease, ref,
    )
    return root, ctl, fleet, gate, remote, req


def _call(gate, request, **options):
    return gate.send_synthetic_once(
        request, attempt_id="attempt_01",
        operation_id="physical_operation_01", action_sha256=ACTION, **options,
    )


def test_fake_dispatch_records_unique_operation_and_zero_production_authority(gate_setup):
    _, _, _, gate, remote, req = gate_setup
    result = _call(gate, req)
    assert result.status == "RECONCILED"
    assert result.may_release is False and result.may_dispatch_production_effect is False
    assert remote.dispatch_count() == 1 and remote.applied_count() == 1
    with pytest.raises(ReplayForbiddenError):
        _call(gate, req)
    with pytest.raises(ReplayForbiddenError):
        gate.send_synthetic_once(
            req, attempt_id="attempt_02",
            operation_id="physical_operation_01", action_sha256=ACTION,
        )
    assert gate.recover_without_replay("attempt_01").status == "RECONCILED"
    assert remote.dispatch_count() == 1


def test_stop_first_is_durable_and_denies_every_new_dispatch(gate_setup):
    _, ctl, _, gate, remote, req = gate_setup
    receipt = gate.accept_stop(
        task_id=req.task_id, owner=req.owner,
        expected_revision=req.task_revision,
        intent_id="human_stop_01", payload_sha256=SHA,
    )
    assert receipt.state == "STOP_REQUESTED"
    assert ctl.read_exact(req.task_id, req.owner).control_epoch == 1
    with pytest.raises(BrokerDeniedError):
        _call(gate, req)
    assert remote.dispatch_count() == 0


def test_stop_ack_waits_for_cooperating_fake_dispatch_linearization(gate_setup):
    _, ctl, _, gate, remote, req = gate_setup
    dispatch_opened = threading.Event()
    finish_fake_transport = threading.Event()

    def after_opened():
        dispatch_opened.set()
        assert finish_fake_transport.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        sender = pool.submit(_call, gate, req, after_opened_for_test=after_opened)
        assert dispatch_opened.wait(timeout=4)
        stopper = pool.submit(
            gate.accept_stop, task_id=req.task_id, owner=req.owner,
            expected_revision=req.task_revision, intent_id="human_stop_02",
            payload_sha256=SHA,
        )
        time.sleep(0.025)
        assert not stopper.done(), "STOP must not acknowledge ahead of dispatched fake call"
        finish_fake_transport.set()
        assert sender.result(timeout=5).status == "RECONCILED"
        assert stopper.result(timeout=5).state == "STOP_REQUESTED"
    assert remote.dispatch_count() == 1
    assert ctl.read_exact(req.task_id, req.owner).state == "STOP_REQUESTED"
    with pytest.raises(BrokerDeniedError):
        gate.send_synthetic_once(
            req, attempt_id="attempt_next", operation_id="operation_next",
            action_sha256=ACTION,
        )
    assert remote.dispatch_count() == 1


def test_fake_remote_effect_before_lost_receipt_only_reconciles_once(gate_setup):
    _, _, _, gate, remote, req = gate_setup

    def simulate_crash_before_receipt():
        raise RuntimeError("simulated lost receipt after fake effect")

    state = _call(gate, req, after_remote_for_test=simulate_crash_before_receipt)
    assert state.status == "OUTCOME_UNKNOWN"
    assert remote.dispatch_count() == 1
    assert gate.recover_without_replay("attempt_01").status == "RECONCILED"
    with pytest.raises(ReplayForbiddenError):
        gate.send_synthetic_once(
            req, attempt_id="attempt_replacement",
            operation_id="physical_operation_01", action_sha256=ACTION,
        )
    assert remote.dispatch_count() == 1


def test_unknown_remote_visibility_cannot_authorize_new_send(gate_setup):
    _, _, _, gate, remote, req = gate_setup

    def fail_before_fake_effect():
        raise RuntimeError("deliberate failure before dispatch")

    with pytest.raises(RuntimeError):
        _call(gate, req, after_opened_for_test=fail_before_fake_effect)
    assert remote.dispatch_count() == 0
    assert gate.recover_without_replay("attempt_01").status == "OUTCOME_UNKNOWN"
    with pytest.raises(ReplayForbiddenError):
        _call(gate, req)
    assert remote.dispatch_count() == 0


def test_expired_fleet_holder_cannot_dispatch_synthetic_effect(gate_setup):
    _, _, fleet, gate, remote, req = gate_setup
    fleet.renew_lease(req.fleet_lease, extend_seconds=0.035)
    time.sleep(0.065)
    with pytest.raises(BrokerDeniedError):
        _call(gate, req)
    assert remote.dispatch_count() == 0


def test_gate_never_accepts_realistic_production_root(tmp_path):
    root = tmp_path / "pretend_prod"
    with pytest.raises(BrokerDeniedError, match="test-only"):
        OfflineStopDispatchGate(
            root=root, broker=object(), remote=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("phase", "marker", "fake_count", "expected_state"),
    [
        ("after_opened", "READY_AFTER_OPENED", 0, "OUTCOME_UNKNOWN"),
        ("after_remote", "READY_AFTER_REMOTE", 1, "RECONCILED"),
    ],
)
def test_real_sigkill_releases_control_flock_and_never_replays(
    gate_setup, phase, marker, fake_count, expected_state,
):
    root, ctl, _, gate, remote, req = gate_setup
    helper = Path(__file__).resolve().parents[1] / "helpers" / "assurance_p17_fake_dispatch_worker.py"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    worker = subprocess.Popen(
        [sys.executable, str(helper), str(root), phase],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        stdin=subprocess.DEVNULL,
    )
    try:
        assert worker.stdout is not None
        ready, _, _ = select.select([worker.stdout], [], [], 12)
        assert ready, "synthetic child did not reach durability boundary"
        assert worker.stdout.readline().strip() == marker
        assert worker.poll() is None
        os.kill(worker.pid, signal.SIGKILL)
        _, stderr = worker.communicate(timeout=7)
        assert worker.returncode == -signal.SIGKILL, stderr[:400]
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=7)
    assert remote.dispatch_count() == fake_count
    assert gate.recover_without_replay("attempt_01").status == expected_state
    assert gate.recover_without_replay("attempt_01").status == expected_state
    with pytest.raises(ReplayForbiddenError):
        gate.send_synthetic_once(
            req, attempt_id="attempt_retry",
            operation_id="physical_operation_01", action_sha256=ACTION,
        )
    assert remote.dispatch_count() == fake_count
    stop = gate.accept_stop(
        task_id=req.task_id, owner=req.owner,
        expected_revision=req.task_revision,
        intent_id="after_crash_stop", payload_sha256=SHA,
    )
    assert stop.state == "STOP_REQUESTED"
    assert ctl.read_exact(req.task_id, req.owner).control_epoch == 1
