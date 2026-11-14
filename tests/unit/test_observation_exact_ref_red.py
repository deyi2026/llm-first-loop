"""RED: an authorized durable EvidenceRef must reach the final provider view.

Uses real EvidenceLedger/BlobStore/EvidenceReadTool, no external source action
or real Provider call. This is a code-level pre-send qualification fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from llm_loop.core.loop.engine_services.observation_visibility import (
    ensure_latest_observation_visible,
)
from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    OwnerScope,
    ProjectionEngine,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from llm_loop.tools.eligibility import runtime_tool_health
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_tools import EvidenceReadTool
from llm_loop.tools.registry import ToolRegistry


def _fixture(
    tmp_path,
    *,
    tool_schema=True,
    owner_mismatch=False,
    source_kind=SourceKind.RUNTIME_SNAPSHOT,
    version_policy=SourceVersionPolicy.VERSIONED,
    version_token="snapshot:v1",
    locator="runtime:test-observation",
):
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
                kind=source_kind,
                locator=locator,
                version_policy=version_policy,
                version_token=version_token,
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


def _project(engine, session, schemas, *, effective_budget=3698, request_preflight=None):
    return ensure_latest_observation_visible(
        engine,
        session,
        [{"role": "system", "content": "policy"}, {"role": "user", "content": "根据证据回答", "_active_run_ingress_ref": "0"}],
        session_id=session.id,
        active_turn_ref=0,
        active_ingress_ref="0",
        effective_budget=effective_budget,
        budget_info={"limited_by": "model_window"},
        request_preflight=request_preflight,
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
    capsule = json.loads(next(m["content"] for m in view if m.get("role") == "tool"))
    assert capsule["evidence_ref"] == ref
    assert capsule["read_tool"] == "read_evidence"
    assert capsule["limit_max"] == 4000
    assert capsule["inline_complete"] is False
    assert capsule["version_token"] == "snapshot:v1"
    assert capsule["freshness"] == "unknown", "historical evidence must not claim currentness"
    assert str(tmp_path) not in json.dumps(capsule)
    tool = engine.registry.get("read_evidence")
    first = json.loads(tool.execute(evidence_ref=ref, range_type="text_char", start=0, limit=4000).content)
    assert first["range"]["next_start"] == 4000
    second = json.loads(tool.execute(evidence_ref=ref, range_type="text_char", start=4000, limit=4000).content)
    assert first["content"] + second["content"] == raw
    assert second["range"]["next_start"] is None


def test_cross_owner_ref_must_not_leak_or_send(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path, owner_mismatch=True)
    view, hold = _project(engine, session, schemas)
    assert hold, "cross-owner EvidenceRef must fail closed"
    assert not any(ref in str(m.get("content", "")) for m in view)


def test_cross_workspace_same_session_ref_must_not_leak(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path)
    tool = engine.registry.get("read_evidence")
    tool.owner_resolver = lambda: OwnerScope(
        workspace_id=str(tmp_path / "other-workspace"), session_id=session.id
    )
    view, hold = _project(engine, session, schemas)
    assert hold and not any(ref in str(m.get("content", "")) for m in view)


def test_ref_record_bound_to_different_tool_call_must_hold(tmp_path):
    engine, session, _ref, schemas, _events, _raw = _fixture(tmp_path)
    tool = engine.registry.get("read_evidence")
    other = EvidenceCapture(tool.hydration.blobs, tool.ledger).capture(
        make_capture_request(
            owner=tool.owner_resolver(),
            stable_capture_id="other-call",
            raw_observation="unrelated",
            acquired_at=datetime(2026, 11, 14, tzinfo=UTC),
            tool_name="fixture_tool",
            tool_call_id="other-call",
            source=SourceIdentity(
                kind=SourceKind.RUNTIME_SNAPSHOT,
                locator="runtime:other",
                version_policy=SourceVersionPolicy.VERSIONED,
                version_token="snapshot:other",
            ),
            coverage=Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
            provenance=Provenance(producer="offline-red"),
        )
    )
    session.messages[-1].metadata["evidence_ref"] = other.evidence_ref.ref
    view, hold = _project(engine, session, schemas)
    assert hold and not any(other.evidence_ref.ref in str(m.get("content", "")) for m in view)


def test_ref_without_callable_read_evidence_schema_must_hold(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path, tool_schema=False)
    assert not schemas
    view, hold = _project(engine, session, schemas)
    assert hold, "a durable ref alone is not provider-readable"
    assert not any(ref in str(m.get("content", "")) for m in view)


def test_stale_probeable_file_ref_must_hold(tmp_path):
    source = tmp_path / "changing.txt"
    source.write_text("old", encoding="utf-8")
    stat = source.stat()
    engine, session, ref, schemas, _events, _raw = _fixture(
        tmp_path,
        source_kind=SourceKind.FILE,
        version_policy=SourceVersionPolicy.PROBEABLE,
        version_token=f"stat:{stat.st_mtime_ns}:{stat.st_size}",
        locator=str(source),
    )
    source.write_text("new and different", encoding="utf-8")
    view, hold = _project(engine, session, schemas)
    assert hold and not any(ref in str(m.get("content", "")) for m in view)


def test_versioned_ref_without_version_token_must_hold(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path, version_token=None)
    view, hold = _project(engine, session, schemas)
    assert hold and not any(ref in str(m.get("content", "")) for m in view)


def test_broken_blob_hydration_must_hold(tmp_path, monkeypatch):
    from llm_loop.memory.evidence import EvidenceBlobLostError

    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path)
    tool = engine.registry.get("read_evidence")

    def _broken_read(**_kwargs):
        raise EvidenceBlobLostError("test-only missing blob")

    monkeypatch.setattr(tool.hydration, "read", _broken_read)
    view, hold = _project(engine, session, schemas)
    assert hold and not any(ref in str(m.get("content", "")) for m in view)


def test_ref_capsule_hard_overflow_must_hold(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path)
    view, hold = _project(
        engine, session, schemas,
        request_preflight=lambda _messages, _tools, **_kw: {"hard_overflow": True},
    )
    assert hold and not any(ref in str(m.get("content", "")) for m in view)


def test_ref_capsule_must_fit_physical_budget(tmp_path):
    engine, session, ref, schemas, _events, _raw = _fixture(tmp_path)
    view, hold = _project(engine, session, schemas, effective_budget=50)
    assert hold and not any(ref in str(m.get("content", "")) for m in view)


def test_two_call_group_projects_all_refs_or_none(tmp_path):
    engine, session, first_ref, schemas, _events, first_raw = _fixture(tmp_path)
    tool = engine.registry.get("read_evidence")
    owner = tool.owner_resolver()
    second_raw = "SECOND_EXACT_OBSERVATION_" + "xyz" * 2000
    second = EvidenceCapture(tool.hydration.blobs, tool.ledger).capture(
        make_capture_request(
            owner=owner,
            stable_capture_id="c2",
            raw_observation=second_raw,
            acquired_at=datetime(2026, 11, 14, tzinfo=UTC),
            tool_name="fixture_tool",
            tool_call_id="c2",
            source=SourceIdentity(
                kind=SourceKind.RUNTIME_SNAPSHOT,
                locator="runtime:second-observation",
                version_policy=SourceVersionPolicy.VERSIONED,
                version_token="snapshot:v2",
            ),
            coverage=Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
            provenance=Provenance(producer="offline-red"),
        )
    )
    second_call = {"id": "c2", "type": "function", "function": {"name": "fixture_tool", "arguments": "{}"}}
    session.messages[1].tool_calls.append(second_call)
    session.messages.append(
        Message(
            role="tool",
            content="[状态: success] " + second_raw,
            source=MessageSource.TOOL,
            tool_call_id="c2",
            tool_name="fixture_tool",
            metadata={"recoverability_status": "recorded", "evidence_ref": second.evidence_ref.ref},
        )
    )
    calls = session.messages[1].tool_calls
    ingress = {"role": "user", "content": "根据证据回答", "_active_run_ingress_ref": "0"}
    raw_view = (
        {"role": "system", "content": "policy"},
        ingress,
        {"role": "assistant", "content": "", "tool_calls": calls},
        {"role": "tool", "tool_call_id": "c1", "content": "[状态: success] " + first_raw},
        {"role": "tool", "tool_call_id": "c2", "content": "[状态: success] " + second_raw},
    )
    engine._build_conservative_active_run_messages = lambda *_a, **_kw: SimpleNamespace(
        state="rebuilt", messages=raw_view, projected_chars=len(first_raw) + len(second_raw) + 200
    )
    view, hold = _project(engine, session, schemas)
    assert hold == ""
    capsules = [json.loads(m["content"]) for m in view if m.get("role") == "tool"]
    assert {row["evidence_ref"] for row in capsules} == {first_ref, second.evidence_ref.ref}
    assert len(capsules) == 2
    session.messages[-1].metadata["evidence_ref"] = "evidence://v1/invalid"
    view, hold = _project(engine, session, schemas)
    assert hold, "a partial multi-call ref projection must fail atomically"
    assert not any(first_ref in str(m.get("content", "")) for m in view)


@pytest.mark.parametrize(
    ("schema_tokens", "expect_recovery"),
    [(26000, True), (28659, False)],
)
def test_real_loop_enforced_evidence_projects_ref_or_holds_at_physical_limit(
    build_test_engine, tmp_path, monkeypatch, schema_tokens, expect_recovery
):
    class _InertTool:
        description = "schema-only; never execute"
        parameters = {"type": "object", "properties": {}}

        def __init__(self, name):
            self.name = name

        def execute(self, **_kwargs):
            raise AssertionError("inert schema must not execute")

    source = tmp_path / "real-loop-evidence.txt"
    source.write_text("ACTUAL_TOOL_OBSERVATION\n" + "payload-" * 900, encoding="utf-8")
    engine, fake = build_test_engine([
        {"tool_calls": [ToolCall(id="real-evidence-1", name="read_file", arguments={"path": str(source)})]},
        {"content": "已依据证据完成"},
    ])
    sid = engine.session.create()
    owner = OwnerScope(workspace_id=str(tmp_path), session_id=sid)
    blobs = BlobStore(tmp_path / "real-blobs")
    ledger = EvidenceLedgerStore(tmp_path / "real-ledger")
    engine.registry.set_evidence_enforcer(
        EvidenceEnforcer(
            EvidenceCapture(blobs, ledger),
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=10000,
        )
    )
    engine.registry.register(
        EvidenceReadTool(blobs, ledger, freshness=EvidenceFreshness(ledger), owner_resolver=lambda: owner)
    )
    eligible = [
        row for row in engine.registry.schemas(lazy=engine.settings.tool_schema_lazy)
        if row["name"] != "convergence_decide" and runtime_tool_health(row["name"]).available
    ]
    for i in range(101 - len(eligible)):
        engine.registry.register(_InertTool(f"evidence_schema_{i:03d}"))
    fake.max_tokens = 32768
    fake.count_tool_schema_tokens = lambda tools: schema_tokens if len(tools) == 101 else -1
    monkeypatch.setattr(engine, "_effective_history_budget", lambda *_a, **_kw: 79979)
    monkeypatch.setattr(
        engine,
        "_effective_history_budget_detail",
        lambda *_a, **_kw: {
            "allowed_input_tokens": 32768,
            "projection_chars_per_token": 0.9,
            "effective_budget": 79979,
            "limited_by": "model_window",
        },
    )
    result = engine.run(sid, "请读取文件后根据原始观察回答")
    if expect_recovery:
        assert result.final_answer == "已依据证据完成"
        assert result.run_incomplete is False
        assert len(fake.calls) == 2
    else:
        assert result.run_incomplete is True
        assert "context_capacity_unavailable" in result.final_answer
        assert len(fake.calls) == 1, "no oversized second provider send"
    assert all(len(call["tools"]) == 101 for call in fake.calls)
    tool_messages = [m for m in engine.session.load(sid).messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].metadata.get("recoverability_status") == "recorded"
    ref = tool_messages[0].metadata.get("evidence_ref")
    assert ref and ledger.count(owner) == 1
    if not expect_recovery:
        return
    projected_tools = [m for m in fake.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(projected_tools) == 1
    capsule = json.loads(projected_tools[0]["content"])
    assert capsule["schema"] == "lfl_exact_tool_observation_ref_v1"
    assert capsule["evidence_ref"] == ref
    assert capsule["read_tool"] == "read_evidence"
