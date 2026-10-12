"""Real SIGKILL victim for P1.7 FakeRemote-only outbound linearization."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

from llm_loop.assurance.offline_effects import FakeRemote
from llm_loop.assurance.p16_host_broker import (
    OfflineHostReviewBroker,
    OfflineReviewRequest,
    OnceOnlyBrokerJournal,
    OwnerEvidenceCatalog,
)
from llm_loop.assurance.p17_stop_dispatch_gate import OfflineStopDispatchGate
from llm_loop.assurance.task_control_store import TaskControlStore
from llm_loop.fleet.store import FleetStore


def main() -> int:
    if len(sys.argv) != 3:
        raise RuntimeError("P1.7 helper requires root and exact synthetic phase")
    root = Path(sys.argv[1]).resolve()
    phase = sys.argv[2]
    if root.name != "assurance-p17-root" or phase not in {
        "after_opened", "after_remote",
    }:
        raise RuntimeError("P1.7 helper rejected non-experiment")
    control = TaskControlStore(root / "control")
    fleet = FleetStore(root / "fleet")
    task = control.read_exact("task_01", "owner_01")
    ref = task.active_binding
    if ref is None:
        raise RuntimeError("synthetic binding not prepared")
    holder = fleet.current_lease(ref.run_key)
    broker = OfflineHostReviewBroker(
        control, fleet, OwnerEvidenceCatalog([]),
        OnceOnlyBrokerJournal(root / "review_calls"),
    )
    gate = OfflineStopDispatchGate(
        root=root, broker=broker, remote=FakeRemote(root / "remote"),
    )
    req = OfflineReviewRequest(
        "review_01", "task_01", "owner_01", "grant_01",
        task.control_epoch, task.revision, task.objective_sha256,
        (), holder, ref,
    )

    def after_opened():
        if phase == "after_opened":
            print("READY_AFTER_OPENED", flush=True)
            time.sleep(60)
            raise RuntimeError("child not killed at opened stage")

    def after_remote():
        if phase == "after_remote":
            print("READY_AFTER_REMOTE", flush=True)
            time.sleep(60)
            raise RuntimeError("child not killed after synthetic remote")

    gate.send_synthetic_once(
        req, attempt_id="attempt_01", operation_id="physical_operation_01",
        action_sha256=hashlib.sha256(b"synthetic fake remote action").hexdigest(),
        after_opened_for_test=after_opened,
        after_remote_for_test=after_remote,
    )
    raise RuntimeError("child unexpectedly completed without SIGKILL")


if __name__ == "__main__":
    raise SystemExit(main())
