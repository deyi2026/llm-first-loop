"""P0-2 GAP-REQ-2 (Phase B3): settlement join keys on request.usage.

Design DESIGN-20261002 §2 GAP-REQ-2: request.usage events gain
``provider_call_id`` / ``provider_attempt_id`` when the settlement binding is
available, so event-log consumers can join a usage row to the settlement
journal's logical call (pcall) and transport attempt (pattempt) records.

Timing fact frozen by implementation review (2026-10-02): ``request.meta`` is
emitted strictly BEFORE the physical send, so a settlement pattempt id cannot
exist at meta time without changing event ordering (forbidden: additive-only).
Meta keeps its existing ``provider_call_id``; the attempt-level join key lands
on ``request.usage`` only, under the non-colliding name ``provider_attempt_id``
(meta already uses ``attempt_id`` for the reachability attempt concept).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.event_log.store import EventStore
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.provider_calls import ProviderCallCoordinator
from llm_loop.resources.provider_settlement import ProviderCallSettlementJournal
from llm_loop.resources.transport_observation import ShadowTransportRecorder


class _NullRuntimeAdapter:
    def note_provider_call(self, *args: Any, **kwargs: Any) -> None:
        return None


def _events_of(store: EventStore, sid: str, event_type: str) -> list[dict]:
    return [dict(e.payload) for e in store.read(sid) if e.type == event_type]


def test_request_usage_carries_provider_call_and_attempt_ids(tmp_path, build_test_engine):
    engine, fake = build_test_engine([{"content": "ok"}])
    engine._event_store = EventStore(tmp_path / "events")
    fake.provider = "cognilocal"
    fake.model = "ornith"

    settle_store = EventStore(tmp_path / "settlement")
    journal = ProviderCallSettlementJournal(settle_store)
    recorder = ShadowTransportRecorder()
    recorder.set_settlement_journal(journal)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=_NullRuntimeAdapter(),
        settlement_journal=journal,
    )
    fake.transport_observer = recorder
    engine.provider_call_coordinator = coordinator

    # Simulate the transport layer: the physical send opens a transport attempt
    # under the shadow call site the engine bound for this client.
    original_chat = fake.chat

    def observed_chat(*args: Any, **kwargs: Any):
        with recorder.transport_attempt(
            provider_id="cognilocal", model_id="ornith", transport_retry_index=0
        ):
            return original_chat(*args, **kwargs)

    fake.chat = observed_chat

    sid = engine.session.create()
    engine.run(sid, "hi")

    usage_payloads = _events_of(engine._event_store, sid, "request.usage")
    assert usage_payloads, "engine round must emit request.usage"
    usage = usage_payloads[-1]

    call_ids = [
        str(p.get("call_id") or "")
        for p in _events_of(settle_store, sid, "provider.call.opened")
    ]
    attempt_ids = [
        str(p.get("attempt_id") or "")
        for p in _events_of(settle_store, sid, "provider.transport.opened")
    ]
    assert call_ids and attempt_ids, "wired fake must open call + transport attempt"

    assert usage.get("provider_call_id") == call_ids[-1]
    assert usage.get("provider_attempt_id") == attempt_ids[-1]
    # The usage attempt id must be the journal's latest attempt for that call.
    assert (
        journal.last_attempt_id_for_call(str(usage.get("provider_call_id") or ""))
        == usage.get("provider_attempt_id")
    )


def test_request_usage_ids_empty_without_settlement_binding(tmp_path, build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    engine._event_store = EventStore(tmp_path / "events")
    sid = engine.session.create()
    engine.run(sid, "hi")

    usage_payloads = _events_of(engine._event_store, sid, "request.usage")
    assert usage_payloads
    usage = usage_payloads[-1]
    assert usage.get("provider_call_id") == ""
    assert usage.get("provider_attempt_id") == ""


def test_request_meta_keeps_pre_send_shape_no_faked_attempt_id(tmp_path, build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    engine._event_store = EventStore(tmp_path / "events")
    sid = engine.session.create()
    engine.run(sid, "hi")

    metas = _events_of(engine._event_store, sid, "request.meta")
    assert metas
    meta = metas[-1]
    # Meta is emitted before the physical send: provider_call_id is the only
    # settlement join key available there, and no attempt id may be invented.
    assert meta.get("provider_call_id") == ""
    assert "provider_attempt_id" not in meta


def test_settlement_jsonl_remains_parseable_additive(tmp_path, build_test_engine):
    """B3 is additive-only: settlement store lines must stay plain JSON objects."""
    engine, fake = build_test_engine([{"content": "ok"}])
    fake.provider = "cognilocal"
    fake.model = "ornith"
    settle_store = EventStore(tmp_path / "settlement")
    journal = ProviderCallSettlementJournal(settle_store)
    recorder = ShadowTransportRecorder()
    recorder.set_settlement_journal(journal)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=_NullRuntimeAdapter(),
        settlement_journal=journal,
    )
    fake.transport_observer = recorder
    engine.provider_call_coordinator = coordinator
    original_chat = fake.chat

    def observed_chat(*args: Any, **kwargs: Any):
        with recorder.transport_attempt(
            provider_id="cognilocal", model_id="ornith", transport_retry_index=0
        ):
            return original_chat(*args, **kwargs)

    fake.chat = observed_chat
    sid = engine.session.create()
    engine.run(sid, "hi")

    lines = [
        line
        for path in sorted((tmp_path / "settlement").rglob("*.jsonl"))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines
    for line in lines:
        record = json.loads(line)
        assert isinstance(record, dict)
