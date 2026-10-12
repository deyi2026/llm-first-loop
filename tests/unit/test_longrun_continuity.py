from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.longrun_continuity import (
    build_longrun_manifest,
    canonical_read_key,
    continuity_wire,
    previous_overflow_manifest,
    restore_read_cache,
)
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.message import (
    Message,
    MessageSource,
    RecoverabilityStatus,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def _host_with_cache():
    state = SimpleNamespace(longrun_read_cache={})
    host = SimpleNamespace(_run_state=lambda: state)
    return host, state


def test_exact_read_file_reuses_only_while_stat_version_is_unchanged(tmp_path):
    path = tmp_path / "large.txt"
    path.write_text("alpha\n" * 200, encoding="utf-8")
    st = path.stat()
    version = f"stat:{st.st_mtime_ns}:{st.st_size}"
    args = {
        "path": str(path),
        "offset": 0,
        "limit": 100,
        "snapshot": True,
        "evidence_force_refresh": True,
    }
    call = ToolCall(id="c1", name="read_file", arguments=args)
    host, state = _host_with_cache()
    cycle = ToolCycleService(host)
    cycle._remember_continuity_read(  # pyright: ignore[reportPrivateUsage]
        call,
        ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="physical body",
            tool_call_id="c1",
            tool_name="read_file",
            recoverability_status=RecoverabilityStatus.RECORDED,
            evidence_ref="evidence://v1/abc",
            evidence_source_version_token=version,
        ),
    )
    assert canonical_read_key("read_file", args) in state.longrun_read_cache

    reused = cycle._continuity_reuse_result(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="c2", name="read_file", arguments=dict(args))
    )
    assert reused is not None
    assert reused.status is ToolResultStatus.SUCCESS
    assert reused.source_execution_performed is False
    assert reused.short_circuit_kind == "longrun_duplicate_read"
    assert "evidence://v1/abc" in reused.content

    path.write_text("beta\n" * 201, encoding="utf-8")
    changed = cycle._continuity_reuse_result(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="c3", name="read_file", arguments=dict(args))
    )
    assert changed is None


def test_exact_read_evidence_is_immutable_and_reusable_without_source_action():
    args = {"evidence_ref": "evidence://v1/abc", "start": 10, "limit": 20}
    host, _state = _host_with_cache()
    cycle = ToolCycleService(host)
    cycle._remember_continuity_read(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="e1", name="read_evidence", arguments=args),
        ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="evidence body",
            tool_call_id="e1",
            tool_name="read_evidence",
            recoverability_status=RecoverabilityStatus.RECORDED,
            evidence_ref="evidence://v1/abc",
            source_execution_performed=False,
        ),
    )
    reused = cycle._continuity_reuse_result(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="e2", name="read_evidence", arguments=dict(args))
    )
    assert reused is not None
    assert reused.source_execution_performed is False
    assert reused.evidence_ref == "evidence://v1/abc"


def test_overflow_manifest_roundtrips_read_anchors_and_is_non_authoritative(tmp_path):
    args = {"path": "/tmp/a.txt", "offset": 0, "limit": 10}
    key = canonical_read_key("read_file", args)
    manifest = build_longrun_manifest(
        session_id="s1",
        data_dir=tmp_path,
        read_cache={
            key: {
                "tool": "read_file",
                "arguments": args,
                "evidence_ref": "evidence://v1/a",
                "source_version_token": "stat:1:2",
                "artifact_ref": "",
            }
        },
        pressure={"observed_chars": 141000, "soft_limit_chars": 135000},
    )
    restored = restore_read_cache(manifest)
    assert restored[key]["evidence_ref"] == "evidence://v1/a"
    wire = continuity_wire(manifest)
    assert wire is not None and wire["role"] == "assistant"
    assert "longrun_continuity—not_instruction" in wire["content"]
    assert '"authority":false' in wire["content"]
    assert '"instruction":false' in wire["content"]


def test_only_immediately_adjacent_overflow_placeholder_can_resume_manifest():
    manifest = {"version": 1, "kind": "longrun_continuity", "read_anchors": []}
    placeholder = Message(
        role="assistant",
        content="",
        source=MessageSource.SYSTEM,
        metadata={
            "program_final_placeholder": True,
            "run_end_reason": "overflow",
            "longrun_continuity_manifest": manifest,
        },
    )
    assert previous_overflow_manifest([placeholder]) == manifest
    later_user = Message(role="user", content="new task", source=MessageSource.USER)
    assert previous_overflow_manifest([placeholder, later_user]) is None


def test_engine_soft_pressure_rebuilds_before_any_provider_call(build_test_engine):
    engine, fake = build_test_engine([{"content": "done"}])
    preflight_calls: list[int] = []

    def preflight(messages, tools, *, model=None):  # noqa: ARG001
        preflight_calls.append(len(fake.calls))
        if len(preflight_calls) == 1:
            return {
                "observed_chars": 141_000,
                "soft_limit_chars": 135_000,
                "hard_limit_chars": 150_000,
                "soft_pressure": True,
                "hard_overflow": False,
            }
        return {
            "observed_chars": 120_000,
            "soft_limit_chars": 135_000,
            "hard_limit_chars": 150_000,
            "soft_pressure": False,
            "hard_overflow": False,
        }

    fake.request_envelope_preflight = preflight
    sid = engine.session.create()
    result = engine.run(sid, "hello")

    assert result.final_answer == "done"
    # First preflight occurred before any model request; only rebuilt request was sent.
    assert preflight_calls == [0, 0]
    assert len(fake.calls) == 1
    assert engine._run_state().ingress_pressure_compact_count == 1  # pyright: ignore[reportPrivateUsage]


def test_real_overflow_finalizer_persists_empty_placeholder_with_event_bound_handoff(
    build_test_engine,
    tmp_path,
):
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.errors import LLMRequestTooLargeError

    engine, fake = build_test_engine([])
    engine._event_store = EventStore(tmp_path / "events", enabled=True)  # pyright: ignore[reportPrivateUsage]
    attempts = 0

    def overflow_chat(messages, tools, *, timeout_s=None, model=None):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        observed = 155_000 if attempts == 1 else 151_000
        raise LLMRequestTooLargeError(
            "request_too_large",
            observed_chars=observed,
            limit_chars=150_000,
            provider="web-test",
        )

    fake.chat = overflow_chat
    sid = engine.session.create()
    result = engine.run(sid, "continue the long task")

    assert attempts == 2
    assert result.run_incomplete is True
    assert result.final_answer.startswith("[文本入口超限]")
    assert "本次终止不是由该 token 窗口直接触发" in result.final_answer
    sess = engine.session.load(sid)
    terminal = sess.messages[-1]
    assert terminal.role == "assistant"
    assert terminal.content == ""
    assert terminal.metadata["program_final_placeholder"] is True
    assert terminal.metadata["run_end_reason"] == "overflow"
    assert terminal.metadata["program_final_event_seq"] > 0
    manifest = terminal.metadata["longrun_continuity_manifest"]
    assert manifest["version"] == 1
    assert manifest["reason"] == "ingress_pressure_or_overflow"

    events = engine._event_store.read_cached(sid)  # pyright: ignore[reportPrivateUsage]
    event = next(e for e in events if e.seq == terminal.metadata["program_final_event_seq"])
    assert event.type == "program.final"
    assert event.payload["full_text"] == result.final_answer
    assert event.payload["continuity_manifest"]["version"] == 1


def test_hard_preflight_overflow_never_reaches_provider_send(build_test_engine, tmp_path):
    from llm_loop.event_log.store import EventStore

    engine, fake = build_test_engine([{"content": "must-not-send"}])
    engine._event_store = EventStore(tmp_path / "events", enabled=True)  # pyright: ignore[reportPrivateUsage]
    preflight_calls = 0

    def preflight(messages, tools, *, model=None):  # noqa: ARG001
        nonlocal preflight_calls
        preflight_calls += 1
        return {
            "observed_chars": 163_443,
            "soft_limit_chars": 135_000,
            "hard_limit_chars": 150_000,
            "soft_pressure": True,
            "hard_overflow": True,
        }

    fake.request_envelope_preflight = preflight
    sid = engine.session.create()
    result = engine.run(sid, "exact active ingress")

    assert fake.calls == []
    assert preflight_calls >= 2
    assert result.final_answer.startswith("[文本入口超限]")
    assert "mandatory_projection_cannot_fit" in result.final_answer
    events = engine._event_store.read_cached(sid)  # pyright: ignore[reportPrivateUsage]
    pressure = [event.payload for event in events if event.type == "request.ingress_pressure"]
    assert any(row.get("action") == "minimum_projection_preflight" for row in pressure)


def test_exact_wire_fit_uses_absolute_post_schema_history_cap(build_test_engine):
    engine, fake = build_test_engine([{"content": "done"}])
    preflight_calls = 0

    def preflight(messages, tools, *, model=None):  # noqa: ARG001
        nonlocal preflight_calls
        preflight_calls += 1
        if preflight_calls == 1:
            return {
                "observed_chars": 163_443,
                "soft_limit_chars": 135_000,
                "hard_limit_chars": 150_000,
                "soft_pressure": True,
                "hard_overflow": True,
            }
        return {
            "observed_chars": 124_000,
            "soft_limit_chars": 135_000,
            "hard_limit_chars": 150_000,
            "soft_pressure": False,
            "hard_overflow": False,
        }

    fake.request_envelope_preflight = preflight
    sid = engine.session.create()
    result = engine.run(sid, "hello")

    assert result.final_answer == "done"
    assert len(fake.calls) == 1
    cap = engine._run_state().ingress_history_budget_cap  # pyright: ignore[reportPrivateUsage]
    assert isinstance(cap, int) and cap > 0
    facts = engine._run_state().ingress_pressure_facts  # pyright: ignore[reportPrivateUsage]
    assert facts["history_budget_cap"] == cap
    assert facts["history_budget_before"] > cap
    assert facts["wire_deficit_chars"] == 28_443
