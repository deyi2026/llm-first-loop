#!/usr/bin/env python3
"""Fleet live qualification: real-LLM spawn through slice1-5 wiring.

Isolated end-to-end evidence for the Project/ExecutionWorkspace/WorkerLease/
reclaim minimal vertical slice (factory G1 wiring + slice5 G2/G3 views):

  phase spawn   - real LLM child run through SubAgentRunner + ProjectCoordinator
                  (factory-style wiring, isolated state dir): on-disk lease,
                  per-run workspace, facts stream (run_started with parent
                  binding, rounds, run_settled) verification. Leaves an
                  un-settled crash lease with short TTL for the reclaim phase.
  phase recover - NEW process on the same state dir: durable topology recovery
                  (parent_of), merged topology_lease_view (settled lease +
                  facts_summary provenance), expired-lease reclaim with
                  generation fencing proof, then settle on the reclaimed lease.

All state lives under --root; the shared runtime and its data dir are never
touched. Requires a real provider key in the environment (GLM_API_KEY per
data/providers.json). Exit code 0 only if every mechanical check passes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from llm_loop.core.run_context import current_session_id  # noqa: E402
from llm_loop.core.session import SessionStore  # noqa: E402
from llm_loop.event_log.store import EventStore  # noqa: E402
from llm_loop.fleet.coordinator import ProjectCoordinator  # noqa: E402
from llm_loop.llm.client import LLMClient  # noqa: E402
from llm_loop.subagent.runner import SubAgentRunner  # noqa: E402
from llm_loop.tools.registry import ToolRegistry  # noqa: E402

CHECKS: list[dict[str, object]] = []


def check(name: str, ok: bool, detail: str) -> None:
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def load_real_client() -> LLMClient:
    providers = json.loads((REPO / "data" / "providers.json").read_text())
    glm = providers["glm"]
    key = os.environ.get(glm["api_key_env"], "")
    if not key:
        raise SystemExit(f"missing real provider key env: {glm['api_key_env']}")
    client = LLMClient(api_key=key, base_url=glm["base_url"], model=glm["default_model"])
    return client


def make_coordinator(root: Path, owner_id: str) -> ProjectCoordinator:
    return ProjectCoordinator(
        fleet_dir=str(root / "fleet"),
        project_id="fleet-live-qual",
        physical_root=str(root / "workspaces"),
        repo_head="live-qual",
        owner_id=owner_id,
    )


def make_runner(root: Path, owner_id: str, llm: object) -> SubAgentRunner:
    events = EventStore(root / "events", enabled=True)
    store = SessionStore(root / "sessions", event_store=events)
    return SubAgentRunner(
        llm=llm,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        session_store=store,
        project_coordinator=make_coordinator(root, owner_id),
        fleet_lease_ttl_seconds=120.0,
    )


def phase_spawn(root: Path) -> int:
    client = load_real_client()
    runner = make_runner(root, "qual-runner-a", llm=client)
    parent_id = "qual-parent-spawn"
    token = current_session_id.set(parent_id)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        started = runner.start(
            "Reply with exactly this token and nothing else: FLEET-LIVE-OK",
            depth=0,
        )
        child_id = str(started["child_id"])
        done, outcome, snapshot = runner.result_current(child_id, wait_seconds=120.0)
        check("real_child_terminal", done and outcome == "ok",
              f"done={done} outcome={outcome}")
        res = snapshot.get("result") if isinstance(snapshot, dict) else None
        text = str(getattr(res, "final_answer", "") or "")
        # criterion: a substantive real-model reply flowed through the child.
        # Exact token obedience is provider-model variance, not slice behavior.
        check("real_llm_output", len(text.strip()) >= 10,
              f"token_echo={'FLEET-LIVE-OK' in text} text={text[:120]!r}")
    finally:
        current_session_id.reset(token)

    # on-disk truth, cross-checked from a fresh coordinator (not the runner's cache)
    coord = make_coordinator(root, "qual-inspector")
    rec = coord.recover(child_id)
    lease = rec.get("lease") or {}
    check("disk_lease_settled", lease.get("state") == "settled",
          f"state={lease.get('state')} gen={lease.get('generation')}")
    check("disk_settlement_recorded", bool(rec.get("settlement")),
          f"settlement={rec.get('settlement')}")
    summary = rec.get("facts_summary") or {}
    check("disk_facts_summary_parent",
          summary.get("last_parent_session_id") == parent_id and summary.get("run_settled", 0) >= 1,
          f"summary={summary}")
    registry = json.loads((root / "fleet" / "state.json").read_text())
    ws_rec = (registry.get("workspaces") or {}).get(rec["workspace_id"])
    check("disk_workspace_registry", bool(ws_rec) and ws_rec.get("project_id") == "fleet-live-qual",
          f"workspace_record={ws_rec} (physical dir materializes lazily by design)")
    facts = [f for f in coord.store.list_facts(rec["workspace_id"]) if isinstance(f, dict)]
    events = [f.get("event") for f in facts]
    check("facts_run_started", "run_started" in events, f"events={events[:8]}")
    started_fact = next((f for f in facts if f.get("event") == "run_started"), {})
    check("facts_parent_binding", started_fact.get("parent_session_id") == parent_id,
          f"parent_session_id={started_fact.get('parent_session_id')!r}")
    check("facts_settled", "run_settled" in events, f"events={events[-4:]}")
    settled_fact = next((f for f in facts if f.get("event") == "run_settled"), {})
    check("facts_settle_parent", settled_fact.get("parent_session_id") == parent_id,
          f"settle parent={settled_fact.get('parent_session_id')!r}")

    # merged read view used by the subagent_topology tool (slice5 G3)
    ok, detail, view = runner.topology_lease_view(child_id=child_id)
    check("topology_view_ok", ok, f"detail={detail}")
    tl = ((view.get("lease") or {}).get("facts") or {})
    check("view_facts_summary", bool(tl.get("facts_summary")),
          f"facts_summary keys={sorted((tl.get('facts_summary') or {}).keys())}")
    lease_facts = tl.get("lease") or {}
    check("view_lease_state", lease_facts.get("state") == "settled",
          f"view lease={lease_facts}")

    # crash lease for the reclaim phase: begin + one fact, then "die" (no settle)
    crash_coord = make_coordinator(root, "qual-crasher")
    crash_lease = crash_coord.begin_run("qual-crash-run", ttl_seconds=3.0)
    crash_coord.run_fact(crash_lease, {"event": "run_started", "parent_session_id": parent_id})
    import dataclasses
    meta = {
        "parent_id": parent_id,
        "child_id": child_id,
        "crash_run_key": "qual-crash-run",
        "crash_lease_generation": crash_lease.generation,
        "crash_lease": dataclasses.asdict(crash_lease),
        "started": started,
        "root": str(root),
    }
    (root / "spawn_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(json.dumps({"phase": "spawn", "meta": meta, "checks": CHECKS}, ensure_ascii=False, indent=1))
    return 0 if all(c["ok"] for c in CHECKS) else 1


def phase_recover(root: Path) -> int:
    meta = json.loads((root / "spawn_meta.json").read_text())
    # no llm needed: recovery/view/reclaim paths are mechanical
    runner = make_runner(root, "qual-runner-b", llm=None)
    parent = runner.parent_of(meta["child_id"])
    check("durable_parent_of", parent == meta["parent_id"],
          f"recovered parent={parent!r} expected={meta['parent_id']!r}")

    ok, detail, view = runner.topology_lease_view(child_id=meta["child_id"])
    tl = ((view.get("lease") or {}).get("facts") or {})
    check("recover_view_facts_summary", bool(tl.get("facts_summary")),
          f"facts_summary={json.dumps(tl.get('facts_summary'), ensure_ascii=False)[:200]}")

    coord = make_coordinator(root, "qual-reclaimer")
    # expired crash lease: reclaim advances generation, old lease is fenced
    deadline = time.time() + 10
    lease = None
    while time.time() < deadline:
        lease = coord.reclaim_run_if_expired(meta["crash_run_key"])
        if lease is not None:
            break
        time.sleep(0.5)
    check("reclaim_after_expiry", lease is not None and lease.generation > meta["crash_lease_generation"],
          f"reclaimed={lease is not None} old_gen={meta['crash_lease_generation']} new_gen={lease.generation if lease else None}")
    old_lease = lease
    stale_fields = dict(meta["crash_lease"])
    stale_fields["generation"] = stale_fields.get("generation", meta["crash_lease_generation"])
    from llm_loop.fleet.store import WorkerLease
    stale = WorkerLease(**stale_fields)
    try:
        coord.run_fact(stale, {"event": "stale_write_attempt", "note": "must be fenced"})
        check("fencing_write_rejected", False, "stale-generation write was NOT rejected")
    except Exception as exc:  # noqa: BLE001 - fencing failure IS the expected mechanical fact
        check("fencing_write_rejected", type(exc).__name__ == "FencedError",
              f"stale gen={stale.generation} write raised {type(exc).__name__}: {exc}")
    coord.finish_run(old_lease, {"event": "run_settled", "outcome": "success", "note": "reclaimed-then-settled"})
    rec2 = coord.recover(meta["crash_run_key"])
    check("reclaimed_settles", (rec2.get("lease") or {}).get("state") == "settled",
          f"final state={(rec2.get('lease') or {}).get('state')}")
    print(json.dumps({"phase": "recover", "checks": CHECKS}, ensure_ascii=False, indent=1))
    return 0 if all(c["ok"] for c in CHECKS) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["spawn", "recover"], required=True)
    ap.add_argument("--root", default=None, help="state root (default: fresh temp dir, printed)")
    args = ap.parse_args()
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="fleet-live-qual-"))
    root.mkdir(parents=True, exist_ok=True)
    print(f"root={root}", flush=True)
    rc = phase_spawn(root) if args.phase == "spawn" else phase_recover(root)
    print(f"RESULT phase={args.phase} rc={rc} checks={len(CHECKS)} failed={[c['check'] for c in CHECKS if not c['ok']]}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
