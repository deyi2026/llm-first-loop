"""Round-2 fleet knife: reclaim races + expired-lease reclamation (measured).

Every race/expiry test runs against a real filesystem with real elapsed
time -- no patched clock, no simulated interleaving:

- thread hammers race through separate ``FleetStore`` file descriptors
  (the in-process flock path);
- a subprocess hammer exercises the cross-process fcntl path;
- TTL tests use real sleeps.

Invariants under measurement:

- at most one ``active`` lease per workspace at any moment (racing
  reclaims must never leave a phantom active generation);
- crash-recovery reclaim is CAS on the observed stale generation:
  exactly one recovery winner, losers get ``LeaseConflictError``;
- ``acquire_lease`` never silently steps on a live active lease;
- a lease past its declared expiry is mechanically reclaimable by any
  owner; an unexpired or expiry-free live lease is refused with
  ``LeaseActiveError`` (that takeover stays an operator decision);
- settlement stays exactly-once and fenced under every race above.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from llm_loop.fleet.coordinator import ProjectCoordinator
from llm_loop.fleet.store import (
    FencedError,
    FleetStore,
    LeaseActiveError,
    LeaseConflictError,
    SettlementError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _seed(fleet_dir: Path) -> tuple[FleetStore, str, str]:
    store = FleetStore(fleet_dir)
    store.create_project("p")
    workspace = store.create_workspace("p", "/tmp/phys-run", "sha")
    return store, "p", workspace.workspace_id


def _raw_state(fleet_dir: Path) -> dict:
    return json.loads((fleet_dir / "state.json").read_text(encoding="utf-8"))


def _active_leases(fleet_dir: Path, workspace_id: str) -> list[dict]:
    return [
        raw
        for raw in _raw_state(fleet_dir)["leases"].values()
        if raw["workspace_id"] == workspace_id and raw["state"] == "active"
    ]


# ---------------------------------------------------------------- races


def test_acquire_on_active_lease_is_a_typed_conflict(tmp_path: Path) -> None:
    """acquire must never silently step on a live active lease."""
    store, project, ws = _seed(tmp_path / "fleet")
    store.acquire_lease(project, ws, owner_id="ow")
    with pytest.raises(LeaseConflictError):
        store.acquire_lease(project, ws, owner_id="ow2")
    assert len(_active_leases(tmp_path / "fleet", ws)) == 1


def test_concurrent_unconditional_reclaim_never_two_active(tmp_path: Path) -> None:
    """Thread hammer: serial explicit takeovers are fine, phantom actives are not."""
    rounds = 25
    threads = 8
    for round_index in range(rounds):
        fleet_dir = tmp_path / "fleet" / f"r{round_index}"
        store, project, ws = _seed(fleet_dir)
        store.acquire_lease(project, ws, owner_id="seed")
        barrier = threading.Barrier(threads)
        results: list[tuple[str, object]] = []
        lock = threading.Lock()

        def hammer(
            worker_index: int,
            *,
            _dir: Path = fleet_dir,
            _barrier: threading.Barrier = barrier,
            _project: str = project,
            _ws: str = ws,
            _lock: threading.Lock = lock,
            _results: list[tuple[str, object]] = results,
        ) -> None:
            racing_store = FleetStore(_dir)
            _barrier.wait(timeout=15)
            try:
                lease = racing_store.reclaim(_project, _ws, owner_id=f"o{worker_index}")
            except Exception as exc:  # noqa: BLE001 - race outcome is the fact under test
                lease = exc
            with _lock:
                _results.append((f"o{worker_index}", lease))

        workers = [
            threading.Thread(target=hammer, args=(index,)) for index in range(threads)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        actives = _active_leases(fleet_dir, ws)
        assert len(actives) == 1, f"round {round_index}: phantom actives {actives}"
        winners = [
            worker_index
            for worker_index, outcome in results
            if not isinstance(outcome, Exception)
        ]
        assert winners, f"round {round_index}: nobody won the reclaim race"
        state = _raw_state(fleet_dir)
        generations = sorted(
            raw["generation"] for raw in state["leases"].values()
        )
        assert generations == list(range(1, len(generations) + 1)), (
            f"round {round_index}: non-monotonic generations {generations}"
        )


def test_concurrent_crash_recovery_is_cas_exactly_one_winner(tmp_path: Path) -> None:
    """begin-style recovery (reclaim with expected_generation) is single-winner."""
    fleet_dir = tmp_path / "fleet"
    store, project, ws = _seed(fleet_dir)
    crashed = store.acquire_lease(project, ws, owner_id="dead-owner")

    threads = 8
    barrier = threading.Barrier(threads)
    outcomes: list[object] = []
    lock = threading.Lock()

    def recover(worker_index: int) -> None:
        racing_store = FleetStore(fleet_dir)
        barrier.wait(timeout=15)
        try:
            outcome: object = racing_store.reclaim(
                project,
                ws,
                owner_id=f"o{worker_index}",
                expected_generation=crashed.generation,
            )
        except Exception as exc:  # noqa: BLE001 - race outcome is the fact under test
            outcome = exc
        with lock:
            outcomes.append(outcome)

    workers = [
        threading.Thread(target=recover, args=(index,)) for index in range(threads)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    leases = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    conflicts = [
        outcome for outcome in outcomes if isinstance(outcome, LeaseConflictError)
    ]
    assert len(leases) == 1, f"expected exactly one recovery winner, got {leases}"
    assert len(conflicts) == threads - 1, outcomes
    actives = _active_leases(fleet_dir, ws)
    assert len(actives) == 1 and actives[0]["generation"] == 2

    winner = leases[0]
    with pytest.raises(FencedError):
        store.settle(crashed, {"ok": False})
    store.settle(winner, {"ok": True})
    with pytest.raises(SettlementError):
        store.settle(winner, {"ok": True})


def test_cross_process_reclaim_race_keeps_single_active(tmp_path: Path) -> None:
    """fcntl flock must serialize real OS processes hammering one fleet dir."""
    fleet_dir = tmp_path / "fleet"
    store, project, ws = _seed(fleet_dir)
    store.acquire_lease(project, ws, owner_id="seed")

    child = (
        "from llm_loop.fleet.store import FleetStore\n"
        f"store = FleetStore({str(fleet_dir)!r})\n"
        f"store.reclaim({project!r}, {ws!r}, owner_id='child')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", child],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(6)
    ]
    return_codes = [process.wait(timeout=30) for process in processes]
    assert return_codes == [0] * 6

    actives = _active_leases(fleet_dir, ws)
    assert len(actives) == 1, f"phantom actives after cross-process race: {actives}"
    final = store.current_lease(ws)
    store.settle(final, {"ok": True})
    with pytest.raises(SettlementError):
        store.settle(final, {"ok": True})


def test_concurrent_begin_run_single_workspace_single_lease(tmp_path: Path) -> None:
    """Coordinator run-boundary race: one workspace identity, one lease."""
    fleet_dir = tmp_path / "fleet"
    threads = 8
    barrier = threading.Barrier(threads)
    outcomes: list[object] = []
    lock = threading.Lock()

    def begin(worker_index: int) -> None:
        coordinator = ProjectCoordinator(
            fleet_dir=fleet_dir,
            project_id="p",
            physical_root=str(tmp_path / "phys"),
            repo_head="sha",
            owner_id=f"o{worker_index}",
        )
        barrier.wait(timeout=15)
        try:
            outcome: object = coordinator.begin_run("run-1", worker_id=f"w{worker_index}")
        except Exception as exc:  # noqa: BLE001 - race outcome is the fact under test
            outcome = exc
        with lock:
            outcomes.append(outcome)

    workers = [
        threading.Thread(target=begin, args=(index,)) for index in range(threads)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    leases = [o for o in outcomes if not isinstance(o, Exception)]
    conflicts = [o for o in outcomes if isinstance(o, LeaseConflictError)]
    assert len(leases) == 1, f"expected one lease winner, got {leases}"
    assert len(conflicts) == threads - 1, outcomes

    state = _raw_state(fleet_dir)
    run_roots = [
        raw["physical_root"]
        for raw in state["workspaces"].values()
        if raw["physical_root"].endswith("/runs/run-1")
    ]
    assert len(run_roots) == 1, f"duplicate run workspace identities: {run_roots}"
    assert len(_active_leases(fleet_dir, run_roots and "ws-1" or "")) == 1


# ----------------------------------------------------------------- TTL


def test_expired_lease_is_mechanically_reclaimable(tmp_path: Path) -> None:
    """Past expiry: any owner may supersede; old worker stays fenced."""
    store, project, ws = _seed(tmp_path / "fleet")
    g1 = store.acquire_lease(project, ws, owner_id="slow", ttl_seconds=0.2)

    with pytest.raises(LeaseActiveError):
        store.reclaim_if_expired(project, ws, owner_id="next")
    time.sleep(0.25)

    g2 = store.reclaim_if_expired(project, ws, owner_id="next", ttl_seconds=30.0)
    assert g2.generation == 2
    assert g2.expires_at is not None

    with pytest.raises(FencedError):
        store.settle(g1, {"ok": False})
    store.settle(g2, {"ok": True})


def test_renew_extends_expiry_in_real_time(tmp_path: Path) -> None:
    store, project, ws = _seed(tmp_path / "fleet")
    g1 = store.acquire_lease(project, ws, owner_id="ow", ttl_seconds=0.25)
    renewed = store.renew_lease(g1, extend_seconds=2.0)
    assert renewed.expires_at is not None and renewed.expires_at > g1.expires_at

    time.sleep(0.3)
    with pytest.raises(LeaseActiveError):
        store.reclaim_if_expired(project, ws, owner_id="next")


def test_renew_is_fenced_for_stale_lease(tmp_path: Path) -> None:
    store, project, ws = _seed(tmp_path / "fleet")
    g1 = store.acquire_lease(project, ws, owner_id="ow")
    store.reclaim(project, ws, owner_id="next")
    with pytest.raises(FencedError):
        store.renew_lease(g1, extend_seconds=1.0)


def test_no_expiry_lease_refuses_mechanical_expiry_reclaim(tmp_path: Path) -> None:
    """Expiry-free live lease: time cannot license a takeover (operator decision)."""
    store, project, ws = _seed(tmp_path / "fleet")
    store.acquire_lease(project, ws, owner_id="ow")

    with pytest.raises(LeaseActiveError):
        store.reclaim_if_expired(project, ws, owner_id="next")

    g2 = store.reclaim(project, ws, owner_id="next")  # explicit path stays open
    assert g2.generation == 2
