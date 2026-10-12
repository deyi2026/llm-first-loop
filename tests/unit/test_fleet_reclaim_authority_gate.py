"""Fleet Gate R0 (Reclaim Authority) deterministic tests.

Invariants implemented by this gate:

- ``renew_lease`` is a rolling-TTL heartbeat: expiry resets to
  ``now + extend_seconds`` and never accumulates across renewals, so a
  crash never leaves a phantom blocking window of stacked TTLs;
- expiry itself fences the holder (``_require_current`` and ``settle``):
  an expired lease cannot write facts, renew itself back to life, or
  settle -- TTL is authority, not a hint;
- ``begin_run`` is fail-closed against a live lease: expired -> exactly
  one generation-CAS winner takes over; unexpired or expiry-free ->
  typed ``LeaseActiveError`` carrying the precise remaining window;
- live takeover exists only as ``force_reclaim``: double CAS (lease id +
  generation) with a mandatory on-disk recorded justification.
"""

from __future__ import annotations

import json
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
)


def _store(fleet_dir: Path) -> tuple[FleetStore, str, str]:
    store = FleetStore(fleet_dir)
    store.create_project("p")
    workspace = store.create_workspace("p", "/tmp/phys", "sha")
    return store, "p", workspace.workspace_id


def _coordinator(fleet_dir: Path, owner: str = "parent-1") -> ProjectCoordinator:
    return ProjectCoordinator(
        fleet_dir=fleet_dir,
        project_id="p",
        physical_root=str(fleet_dir.parent / "phys"),
        repo_head="sha",
        owner_id=owner,
    )


def _raw(fleet_dir: Path) -> dict:
    return json.loads((fleet_dir / "state.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- rolling TTL


def test_renew_is_rolling_ttl_not_cumulative(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    t0 = time.time()
    store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=0.4)

    g1 = store.renew_lease(store.current_lease(ws), extend_seconds=0.4)
    g2 = store.renew_lease(store.current_lease(ws), extend_seconds=0.4)

    # each heartbeat still strictly extends the (single) live lease
    assert g1.expires_at is not None and g2.expires_at is not None
    assert g2.expires_at > g1.expires_at
    # but rolling: the window is measured from the last heartbeat, never
    # stacked -- cumulative renewal would push expiry to >= t0 + 1.2
    assert g2.expires_at < t0 + 0.75, (
        f"expiry accumulated across renewals: {g2.expires_at - t0:.3f}s"
    )


def test_renew_rejects_non_positive_extension(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    g1 = store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=30.0)
    with pytest.raises(ValueError):
        store.renew_lease(g1, extend_seconds=0.0)


def test_renew_keeps_expiry_free_lease_expiry_free(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    g1 = store.acquire_lease(project, ws, owner_id="dead")
    renewed = store.renew_lease(g1, extend_seconds=60.0)
    assert renewed.expires_at is None, "heartbeat must not change takeover authority"


# ------------------------------------------------- expiry fences the holder


def test_expired_lease_cannot_renew_fact_or_settle(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    g1 = store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=0.1)
    time.sleep(0.25)  # really expired; no successor exists yet

    with pytest.raises(FencedError):
        store.renew_lease(g1, extend_seconds=30.0)
    with pytest.raises(FencedError):
        store.record_fact(g1, {"event": "late"})
    with pytest.raises(FencedError):
        store.settle(g1, {"ok": True})

    g2 = store.reclaim_if_expired(project, ws, owner_id="next", ttl_seconds=30.0)
    store.record_fact(g2, {"event": "run_started"})  # successor rights intact


# ---------------------------------------------- begin_run is fail-closed


def test_unexpired_active_lease_blocks_begin_run(tmp_path: Path) -> None:
    fleet_dir = tmp_path / "fleet"
    coord = _coordinator(fleet_dir)
    g1 = coord.begin_run("run-1", worker_id="w1", ttl_seconds=60.0)

    rival = _coordinator(fleet_dir, owner="parent-2")
    with pytest.raises(LeaseActiveError) as blocked:
        rival.begin_run("run-1", worker_id="w2")
    assert blocked.value.remaining_seconds is not None
    assert 0 < blocked.value.remaining_seconds <= 60.0

    view = rival.recover("run-1")
    assert view["lease"]["state"] == "active"
    assert view["lease"]["lease_id"] == g1.lease_id  # no silent takeover
    assert 0 < view["lease"]["remaining_seconds"] <= 60.0


def test_expiry_free_active_lease_blocks_begin_run(tmp_path: Path) -> None:
    fleet_dir = tmp_path / "fleet"
    coord = _coordinator(fleet_dir)
    coord.begin_run("run-1", worker_id="w1")  # expiry-free: blocks forever

    rival = _coordinator(fleet_dir, owner="parent-2")
    with pytest.raises(LeaseActiveError) as blocked:
        rival.begin_run("run-1", worker_id="w2")
    assert blocked.value.remaining_seconds is None  # exact: no window exists

    view = rival.recover("run-1")
    assert view["lease"]["remaining_seconds"] is None


def test_begin_run_reclaims_only_after_real_expiry(tmp_path: Path) -> None:
    fleet_dir = tmp_path / "fleet"
    coord = _coordinator(fleet_dir)
    stale = coord.begin_run("run-1", worker_id="w1", ttl_seconds=0.05)

    with pytest.raises(LeaseActiveError):
        _coordinator(fleet_dir, owner="p2").begin_run("run-1", worker_id="w2")
    time.sleep(0.15)  # the bounded lease really expires

    fresh = _coordinator(fleet_dir, owner="parent-2")
    new_lease = fresh.begin_run("run-1", worker_id="w2", ttl_seconds=60.0)
    assert new_lease.generation == 2

    raw = _raw(fleet_dir)
    assert raw["leases"][stale.lease_id]["state"] == "superseded"
    with pytest.raises(FencedError):
        coord.run_fact(stale, {"event": "late"})


def test_expired_reclaim_race_exactly_one_winner(tmp_path: Path) -> None:
    fleet_dir = tmp_path / "fleet"
    seed = _coordinator(fleet_dir)
    seed.begin_run("run-1", worker_id="w0", ttl_seconds=0.05)
    time.sleep(0.15)  # time licenses takeover; concurrent resumes must race

    threads = 8
    barrier = threading.Barrier(threads)
    outcomes: list[object] = []
    lock = threading.Lock()

    def take(worker_index: int) -> None:
        coordinator = _coordinator(fleet_dir, owner=f"o{worker_index}")
        barrier.wait(timeout=15)
        try:
            outcome: object = coordinator.begin_run(
                "run-1", worker_id=f"w{worker_index}", ttl_seconds=60.0
            )
        except Exception as exc:  # noqa: BLE001 - race outcome is the fact under test
            outcome = exc
        with lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=take, args=(i,)) for i in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    winners = [o for o in outcomes if not isinstance(o, Exception)]
    rejections = [
        o for o in outcomes
        if isinstance(o, (LeaseActiveError, LeaseConflictError))
    ]
    assert len(winners) == 1, outcomes
    assert len(rejections) == threads - 1, outcomes

    active = [r for r in _raw(fleet_dir)["leases"].values() if r["state"] == "active"]
    assert len(active) == 1
    assert active[0]["generation"] == 2


# ------------------------------------------------------- CAS + force path


def test_reclaim_if_expired_generation_cas(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=0.05)
    time.sleep(0.15)

    with pytest.raises(LeaseConflictError):
        store.reclaim_if_expired(
            project, ws, owner_id="next", expected_generation=99
        )
    g2 = store.reclaim_if_expired(
        project, ws, owner_id="next", expected_generation=1, ttl_seconds=60.0
    )
    assert g2.generation == 2


def test_force_reclaim_requires_recorded_justification(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    g1 = store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=60.0)
    with pytest.raises(ValueError):
        store.force_reclaim(
            project, ws, owner_id="op",
            expected_lease_id=g1.lease_id, expected_generation=1,
            reason="   ", authorized_by="",
        )


def test_force_reclaim_takes_over_and_records_provenance(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    g1 = store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=60.0)

    g2 = store.force_reclaim(
        project, ws, owner_id="op",
        expected_lease_id=g1.lease_id, expected_generation=1,
        reason="holder pid gone, no renewal for 3 TTLs",
        authorized_by="operator-alice",
    )
    assert g2.generation == 2
    assert g2.state == "active"

    raw = _raw(tmp_path)
    assert raw["leases"][g1.lease_id]["state"] == "superseded"
    takeover = raw["leases"][g2.lease_id]["takeover"]
    assert takeover["kind"] == "operator_force_reclaim"
    assert takeover["reason"] == "holder pid gone, no renewal for 3 TTLs"
    assert takeover["authorized_by"] == "operator-alice"
    assert takeover["superseded_lease_id"] == g1.lease_id

    with pytest.raises(FencedError):
        store.record_fact(g1, {"event": "late"})  # old holder is fenced
    store.record_fact(g2, {"event": "run_started"})  # successor writes fine


def test_force_reclaim_double_cas_rejects_stale_identity(tmp_path: Path) -> None:
    store, project, ws = _store(tmp_path)
    g1 = store.acquire_lease(project, ws, owner_id="dead", ttl_seconds=60.0)

    with pytest.raises(LeaseConflictError):
        store.force_reclaim(
            project, ws, owner_id="op",
            expected_lease_id="lease-ws-1-g99", expected_generation=1,
            reason="r", authorized_by="op",
        )
    with pytest.raises(LeaseConflictError):
        store.force_reclaim(
            project, ws, owner_id="op",
            expected_lease_id=g1.lease_id, expected_generation=7,
            reason="r", authorized_by="op",
        )
    # failed attempts never touched the live lease
    current = store.current_lease(ws)
    assert current.lease_id == g1.lease_id
    assert current.state == "active"


def test_force_reclaim_run_coordinator_surface(tmp_path: Path) -> None:
    fleet_dir = tmp_path / "fleet"
    coord = _coordinator(fleet_dir)
    g1 = coord.begin_run("run-1", worker_id="w1")  # expiry-free live lease

    with pytest.raises(LeaseActiveError):
        _coordinator(fleet_dir, owner="p2").begin_run("run-1", worker_id="w2")

    g2 = coord.force_reclaim_run(
        "run-1",
        expected_lease_id=g1.lease_id,
        expected_generation=g1.generation,
        reason="holder dead after crash, no expiry declared",
        authorized_by="operator-bob",
    )
    assert g2.generation == 2
    takeover = _raw(fleet_dir)["leases"][g2.lease_id]["takeover"]
    assert takeover["authorized_by"] == "operator-bob"
    assert takeover["kind"] == "operator_force_reclaim"


def test_recover_reports_precise_remaining_ttl(tmp_path: Path) -> None:
    fleet_dir = tmp_path / "fleet"
    coord = _coordinator(fleet_dir)
    coord.begin_run("run-1", worker_id="w1", ttl_seconds=60.0)
    view = coord.recover("run-1")
    assert view["lease"]["expired"] is False
    assert 0 < view["lease"]["remaining_seconds"] <= 60.0

    coord.begin_run("run-2", worker_id="w1", ttl_seconds=0.05)
    time.sleep(0.15)
    expired_view = coord.recover("run-2")
    assert expired_view["lease"]["expired"] is True
    assert expired_view["lease"]["remaining_seconds"] <= 0
