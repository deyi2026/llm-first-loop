"""P0-3 GAP-DUR-1: orphaned transport-attempt reconciliation (decision 654cc7d5a §5).

Facts tested mechanically:
1. script marks opened-without-settled attempts via a durable
   `provider.transport.orphaned` event and is idempotent on re-run;
2. no fabricated fields (no reason/cause/outcome) are written;
3. journal hydration moves orphaned attempts out of the opened semantics;
4. snapshot_call counts attempts_orphaned and never treats orphaned as settled.
"""

from __future__ import annotations

import json

from llm_loop.event_log.store import EventStore
from llm_loop.resources.provider_settlement import ProviderCallSettlementJournal
from scripts.evidence.mark_orphaned_transport_attempts import mark_orphaned_attempts as _mark


def _load_script():
    import types

    return types.SimpleNamespace(mark_orphaned_attempts=_mark)


def _opened_payload(call_id: str, attempt_id: str, *, provider_id: str = "glm", started_at: float = 100.0):
    return {
        "call_id": call_id,
        "attempt_id": attempt_id,
        "parent_attempt_id": None,
        "attempt_kind": "primary",
        "site_index": 0,
        "transport_retry_index": 0,
        "provider_id": provider_id,
        "model_id": "glm-5.3",
        "started_at": started_at,
    }


def _settled_payload(opened: dict, *, outcome: str = "success"):
    return {
        **opened,
        "outcome": outcome,
        "settled_at": 101.0,
        "usage": {},
        "usage_observations": 0,
        "status_code": None,
        "provider_code": None,
        "retry_after_seconds": None,
        "rate_limits": [],
        "error_type": None,
    }


def test_script_marks_opened_without_settled_and_is_idempotent(tmp_path):
    script = _load_script()
    store = EventStore(tmp_path / "events")
    # session s1: control attempt settled; target attempt orphan candidate
    store.append("s1", "provider.transport.opened", _opened_payload("pcall:a", "pattempt:a1"))
    store.append("s1", "provider.transport.settled", _settled_payload(_opened_payload("pcall:a", "pattempt:a1")))
    store.append("s1", "provider.transport.opened", _opened_payload("pcall:b", "pattempt:b1", started_at=200.0))
    # session s2: another orphan candidate in a different session
    store.append("s2", "provider.transport.opened", _opened_payload("pcall:c", "pattempt:c1", provider_id="cognilocal"))

    dry = script.mark_orphaned_attempts(store, dry_run=True, now=1000.0)
    assert dry["marked"] == 0
    assert dry["candidates"] == 2
    orphaned_events = [e for e in store.read("s1") + store.read("s2") if e.type == "provider.transport.orphaned"]
    assert orphaned_events == []

    run1 = script.mark_orphaned_attempts(store, dry_run=False, now=1000.0)
    assert run1["marked"] == 2
    s1_orphans = [e for e in store.read("s1") if e.type == "provider.transport.orphaned"]
    s2_orphans = [e for e in store.read("s2") if e.type == "provider.transport.orphaned"]
    assert len(s1_orphans) == 1 and len(s2_orphans) == 1
    payload = s1_orphans[0].payload
    assert payload["attempt_id"] == "pattempt:b1"
    assert payload["call_id"] == "pcall:b"
    assert payload["provider_id"] == "glm"
    assert payload["model_id"] == "glm-5.3"
    assert payload["opened_at"] == 200.0
    assert payload["orphaned_at"] == 1000.0
    assert payload["mechanical_fact"] == "opened_without_settled"
    # no fabricated outcome/cause fields
    for forbidden in ("outcome", "reason", "cause", "finish_reason", "usage"):
        assert forbidden not in payload

    run2 = script.mark_orphaned_attempts(store, dry_run=False, now=2000.0)
    assert run2["marked"] == 0
    assert run2["already_orphaned"] == 2
    total = [e for e in store.read("s1") + store.read("s2") if e.type == "provider.transport.orphaned"]
    assert len(total) == 2


def test_hydration_moves_orphaned_out_of_opened_and_snapshot_distinguishes(tmp_path):
    store = EventStore(tmp_path / "events")
    # call pcall:mixed: one settled attempt + one orphaned attempt
    store.append("s1", "provider.call.opened", {
        "call_id": "pcall:mixed", "owner_ref": "task:s1", "execution_class": "foreground_task",
        "service_priority": 10, "purpose": "task", "created_at": 1.0,
    })
    store.append("s1", "provider.transport.opened", _opened_payload("pcall:mixed", "pattempt:m1"))
    store.append("s1", "provider.transport.settled", _settled_payload(_opened_payload("pcall:mixed", "pattempt:m1")))
    store.append("s1", "provider.transport.opened", _opened_payload("pcall:mixed", "pattempt:m2", started_at=300.0))
    store.append("s1", "provider.transport.orphaned", {
        "call_id": "pcall:mixed", "attempt_id": "pattempt:m2", "provider_id": "glm",
        "model_id": "glm-5.3", "opened_at": 300.0, "orphaned_at": 999.0,
        "mechanical_fact": "opened_without_settled",
    })
    # call pcall:only: single orphaned attempt
    store.append("s2", "provider.call.opened", {
        "call_id": "pcall:only", "owner_ref": "task:s2", "execution_class": "foreground_task",
        "service_priority": 10, "purpose": "task", "created_at": 1.0,
    })
    store.append("s2", "provider.transport.opened", _opened_payload("pcall:only", "pattempt:o1"))
    store.append("s2", "provider.transport.orphaned", {
        "call_id": "pcall:only", "attempt_id": "pattempt:o1", "provider_id": "cognilocal",
        "model_id": "gguf", "opened_at": 400.0, "orphaned_at": 999.0,
        "mechanical_fact": "opened_without_settled",
    })

    journal = ProviderCallSettlementJournal(store)
    assert journal.TRANSPORT_ORPHANED == "provider.transport.orphaned"

    mixed = journal.snapshot_call("pcall:mixed", session_id="s1")
    assert mixed["attempts_orphaned"] == 1
    assert mixed["attempts_settled"] == 1
    assert mixed["attempts_opened"] == 1  # orphaned moved out of opened semantics
    assert mixed["attempts_complete"] is True  # non-orphaned attempt fully settled
    assert all(row.get("attempt_id") != "pattempt:m2" for row in mixed["attempts"])
    assert journal.last_attempt_id_for_call("pcall:mixed") == "pattempt:m2"

    only = journal.snapshot_call("pcall:only", session_id="s2")
    assert only["attempts_orphaned"] == 1
    assert only["attempts_opened"] == 0
    assert only["attempts_settled"] == 0
    assert only["attempts_complete"] is False
    assert only["attempts"] == []


def test_json_payloads_round_trip_through_files(tmp_path):
    store = EventStore(tmp_path / "events")
    script = _load_script()
    store.append("s1", "provider.transport.opened", _opened_payload("pcall:a", "pattempt:a1", started_at=12.5))
    script.mark_orphaned_attempts(store, dry_run=False, now=77.0)
    raw = (tmp_path / "events" / "s1.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) == 2
    event = json.loads(raw[-1])
    assert event["type"] == "provider.transport.orphaned"
    assert event["payload"]["attempt_id"] == "pattempt:a1"
    assert event["seq"] == 2


def test_multi_segment_sessions_excluded_by_default(tmp_path):
    """Replication artifacts: multi-segment layers stay out until an attribution decision."""

    script = _load_script()
    store = EventStore(tmp_path / "events")
    store.append("s1", "provider.transport.opened", _opened_payload("pcall:a", "pattempt:a1"))
    # build a genuine multi-segment layout: write via the store, then rotate
    # the single file into a session directory segment
    store.append("seg-sid", "provider.transport.opened", _opened_payload("pcall:z", "pattempt:z1"))
    single = tmp_path / "events" / "seg-sid.jsonl"
    segment_dir = tmp_path / "events" / "seg-sid"
    segment_dir.mkdir(parents=True)
    single.rename(segment_dir / "000.jsonl")

    default = script.mark_orphaned_attempts(store, dry_run=False, now=1.0)
    assert default["marked"] == 1  # single-file s1 marked
    assert default["scanned_sessions"] == 1

    widened = script.mark_orphaned_attempts(store, dry_run=True, now=2.0, include_multi_segment=True)
    assert widened["scanned_sessions"] == 2
    assert widened["already_orphaned"] == 1
    assert widened["candidates"] == 1  # only the multi-segment attempt remains
