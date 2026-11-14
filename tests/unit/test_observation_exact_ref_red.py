"""RED: an authorized durable EvidenceRef must reach the final provider view.

Uses real EvidenceLedger/BlobStore/EvidenceReadTool, no external source action
or real Provider call. This is a code-level pre-send qualification fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from llm_loop.core.loop.engine_services.observation_visibility import (
    ensure_latest_observation_visible,
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.tools.evidence_tools import EvidenceReadTool
from llm_loop.tools.registry import ToolRegistry


def _fixture(tmp_path, *, tool_schema=True, owner_mismatch=False):
    owner = OwnerScope(workspace_id=str(tmp_path), session_id="test-session")
    blobs = BlobStore(tmp_path / "blobs")
    ledger = EvidenceLedgerStore(tmp_path / "ledger")
    raw = "EXACT_OBSERVATION_" + "abcdefg" * 1000
    result = EvidenceCapture(blobs, ledger).capture(
        make_capture_request(
            owner=owner,
            stable_capture_id="c1",
            raw_observation=raw,
            acquired_at=datetime(2026, 11, 14, tzinfo=UTC),
            tool_name="fixture_tool",
            tool_call_id="c1",
            source=SourceIdentity(
                kind=SourceKind.RUNTIME_SNAPSHOT,
                locator="runtime:test-observation",
                version_policy=SourceVersionPolicy.VERSIONED,
                version_token="snapshot:v1",
            ),
            coverage=Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
            provenance=Provenance(producer="offline-red"),
        )
    )
    registry = ToolRegistry()
    read_owner = (
        OwnerScope(workspace_id=str(tmp_path), session_id="other-session")
        if owner_mismatch
        else owner
    )
    registry.register(
        EvidenceReadTool(
            blobs, ledger, freshness=EvidenceFreshness(ledger), owner_resolver=lambda: read_owner
        )
    )
    calls = [
        {"id": "c1", "type": "function", "function": {"name": "fixture_tool", "arguments": "{}"}}
    ]
    session = SimpleNamespace(
        id=owner.session_id,
        messages=[
            Message(role="user", content="根据证据回答", source=MessageSource.USER),
            Message(role="assistant", content="", tool_calls=calls, source=MessageSource.SYSTEM),
            Message(
                role="tool",
                content="[状态: success] " + raw,
                source=MessageSource.TOOL,
                tool_call_id="c1",
                tool_name="fixture_tool",
                metadata={"recoverability_status": "recorded", "evidence_ref": result.evidence_ref.ref},
            ),
        ],
    )
    ingress = {"role": "user", "content": "根据证据回答", "_active_run_ingress_ref": "0"}
    assistant = {"role": "assistant", "content": "", "tool_calls": calls}
    tool = {"role": "tool", "tool_call_id": "c1", "content": "[状态: success] " + raw}
    events = []
    engine = SimpleNamespace(
        registry=registry,
        _build_conservative_active_run_messages=lambda *_a, **_kw: SimpleNamespace(
            state="rebuilt", messages=({"role": "system", "content": "policy"}, ingress, assistant, tool),
            projected_chars=len(raw) + 100,
        ),
        _event_append=lambda _sid, kind, payload: events.append((kind, payload)),
        _record_action=lambda *_a, **_kw: None,
    )
    schemas = (
        [{"type": "function", "function": {"name": "read_evidence", "parameters": {"type": "object"}}}]
        if tool_schema
        else []
    )
    return engine, session, result.evidence_ref.ref, schemas, events, raw


def _project(engine, session, schemas):
    return ensure_latest_observation_visible(
        engine,
        session,
        [{"role": "system", "content": "policy"}, {"role": "user", "content": "根据证据回答", "_active_run_ingress_ref": "0"}],
        session_id=session.id,
        active_turn_ref=0,
        active_ingress_ref="0",
        effective_budget=3698,
        budget_info={"limited_by": "model_window"},
        request_preflight=None,
        tools_param=schemas,
        chat_model_arg="local",
        model="local",
        planned_label="local",
        rounds=2,
    )


def test_authorized_exact_ref_is_model_visible_before_second_send(tmp_path):
    engine, session, ref, schemas, events, raw = _fixture(tmp_path)
    view, hold = _project(engine, session, schemas)
    assert hold == "", "RED: authorized recoverable EvidenceRef must not be needlessly HOLD"
    assert any(
        m.get("role") == "tool" and ref in str(m.get("content", ""))
        and "read_evidence" in str(m.get("content", ""))
        for m in view
    )
    assert all(raw not in str(m.get("content", "")) for m in view)
    assert any(kind == "request.observation_visibility" for kind, _ in events)


def test_cross_owner_ref_must_not_leak_or_send(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path, owner_mismatch=True)
    view, hold = _project(engine, session, schemas)
    assert hold, "cross-owner EvidenceRef must fail closed"
    assert not any(ref in str(m.get("content", "")) for m in view)


def test_ref_without_callable_read_evidence_schema_must_hold(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path, tool_schema=False)
    assert not schemas
    view, hold = _project(engine, session, schemas)
    assert hold, "a durable ref alone is not provider-readable"
    assert not any(ref in str(m.get("content", "")) for m in view)
