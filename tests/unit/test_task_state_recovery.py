"""Task-owned state, exact compression recovery, and stale-write fencing."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResultStatus
from llm_loop.core.run_context import (
    current_run_generation,
    current_session_id,
    current_workspace_root,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import (
    ToolExecutionJournal,
    activate_effect_binding_for_call,
    revoke_effect_binding_for_call,
)
from llm_loop.event_log.store import EventStore
from llm_loop.tools.builtin.task_state import TaskStateTool


@pytest.fixture
def state_tool(tmp_path):
    events = EventStore(tmp_path / "event_logs", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    session.messages.append(Message(role="assistant", content="", source=MessageSource.USER,
        reasoning_content="HEAD\n" + "thought\n" * 12000 + "TAIL",
        tool_calls=[{"id": "c", "type": "function",
                     "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}]))
    sessions.save(session)
    tool = TaskStateTool(sessions, events, data_dir=str(tmp_path))
    tokens = [current_session_id.set(sid), current_run_generation.set("run-1"),
              current_workspace_root.set(str(tmp_path))]
    try:
        yield tool, sessions, events, sid, tmp_path
    finally:
        current_workspace_root.reset(tokens[2])
        current_run_generation.reset(tokens[1])
        current_session_id.reset(tokens[0])


def test_state_is_exact_model_text_and_restart_readable(state_tool):
    tool, sessions, events, sid, root = state_tool
    saved = tool.execute(action="save", state="Goal: archive sandbox only. Not executed.",
                         source_refs=["evidence://source"])
    assert saved.status == ToolResultStatus.SUCCESS
    ref = json.loads(saved.content)["state_ref"]
    restarted = TaskStateTool(sessions, EventStore(root / "event_logs", enabled=True))
    read = json.loads(restarted.execute(action="read", state_ref=ref).content)
    assert read["state"] == "Goal: archive sandbox only. Not executed."
    assert read["semantic_verified"] is False and read["automatic_replay"] is False
    token = current_run_generation.set("run-2")
    try:
        assert json.loads(tool.execute(action="read").content)["applies_to_current_run"] is False
    finally:
        current_run_generation.reset(token)
    assert tool.execute(action="clear").status == ToolResultStatus.SUCCESS
    assert json.loads(tool.execute(action="read").content)["cleared"] is True


def test_state_scope_and_missing_context_cannot_read_other_session(state_tool):
    tool, sessions, events, sid, root = state_tool
    ref = json.loads(tool.execute(action="save", state="private").content)["state_ref"]
    token = current_session_id.set(sessions.create())
    try:
        assert tool.execute(action="read", state_ref=ref).status == ToolResultStatus.FAILURE
    finally:
        current_session_id.reset(token)
    token = current_workspace_root.set(str(root / "different"))
    try:
        assert tool.execute(action="read").status == ToolResultStatus.FAILURE
    finally:
        current_workspace_root.reset(token)


def test_message_exact_paging_recovers_tools_and_reasoning(state_tool):
    tool, *_ = state_tool
    offset = 0
    parts = []
    sha = ""
    while True:
        result = tool.execute(action="read_message", message_index=0, offset=offset, limit=10001,
                              expected_sha256=sha)
        assert result.status == ToolResultStatus.SUCCESS, result.content
        page = json.loads(result.content)
        sha = page["source_sha256"]
        parts.append(page["text"])
        if not page["has_more"]:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    source = json.loads("".join(parts))
    assert source["reasoning_content"].endswith("TAIL")
    assert source["tool_calls"][0]["function"]["arguments"] == "{\"path\":\"a.py\"}"
    assert tool.execute(action="read_message", message_index=0,
                        expected_sha256="0" * 64).status == ToolResultStatus.FAILURE


def test_cancelled_tool_attempt_cannot_save_state(state_tool):
    tool, sessions, events, sid, root = state_tool
    journal = ToolExecutionJournal(event_store=events, result_root=root / "receipts", session_store=sessions)
    call = ToolCall(id="cancelled-call", name="task_state", arguments={})
    before = len(events.read_cached(sid))
    with (
        journal.effect_bindings(session_id=sid, execution_ids={call.id: "e1"},
            round_no=1, calls=[call], workspace_root=str(root)),
        activate_effect_binding_for_call(call.id),
    ):
        assert revoke_effect_binding_for_call(call.id)
        result = tool.execute(action="save", state="must not overwrite")
    assert result.status == ToolResultStatus.FAILURE
    assert len(events.read_cached(sid)) == before


def test_recent_tools_are_facts_not_task_progress(state_tool):
    tool, sessions, events, sid, root = state_tool
    for i in range(2):
        events.append(sid, "tool.execution.declared",
                      {"tool_name": "read_file", "args_sha256": "same", "execution_id": str(i)})
    events.append(sid, "tool.execution.finished", {"execution_id": "1", "status": "success"})
    result = json.loads(tool.execute(action="recent_tools").content)
    assert result["task_progress"] == "not_evaluated"
    assert result["source_versions_equal"] == "not_evaluated"
    assert result["calls"][-1]["same_arguments_in_window"] == 2
    assert result["calls"][-1]["result"]["status"] == "success"


def test_compaction_source_works_in_shadow_without_instructions(state_tool):
    from llm_loop.core.loop.engine_services import compaction_gate as gate
    tool, sessions, events, sid, root = state_tool
    engine = SimpleNamespace(settings=SimpleNamespace(data_dir=str(root), cog_runtime_mode="shadow"))
    message = sessions.load(sid).messages[0]
    gate.note_archive_batch_entry(engine, sid, message, {}, 0, evidence_ref="evidence://exact-protocol")
    manifest = gate.write_compaction_manifest(str(root), sid, gate.take_archive_batch(engine, sid))
    loaded = json.loads(Path(manifest["path"]).read_text())
    assert loaded["assistant_entries"][0]["protocol_state_ref"] == "evidence://exact-protocol"
    events.append(sid, "compaction.snapshot",
                  {"sha256": manifest["sha256"], "path": manifest["rel_path"]})
    setattr(engine, gate._SLOTS_ATTR, {sid: {
        "manifest_sha256": manifest["sha256"], "manifest_rel_path": manifest["rel_path"],
        "total_archived": 1, "source_message_range": [0, 0],
    }})
    wire = gate.compaction_source_wire(engine, sid)
    assert wire["role"] == "assistant" and "请执行" not in wire["content"]
    assert str(root) in wire["content"]
    read = tool.execute(action="read_manifest", manifest_sha256=manifest["sha256"], limit=101)
    page = json.loads(read.content)
    assert read.status == ToolResultStatus.SUCCESS and page["next_offset"] == 101
    assert gate.compaction_source_wire(engine, "another-session") is None
    with open(manifest["path"], "a") as f:
        f.write("corrupt")
    assert tool.execute(action="read_manifest").status == ToolResultStatus.FAILURE


@pytest.mark.parametrize("opaque_only", [False, True])
def test_real_factory_registers_task_state_and_captures_protocol(tmp_path, opaque_only):
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine
    settings = Settings(data_dir=str(tmp_path / "data"), llm_api_key="dummy",
                        llm_model="m", llm_base_url="https://provider.invalid/v1",
                        evidence_mode="enforce", summary_mode="off")
    engine = build_engine(settings)
    assert engine.registry.get("task_state").name == "task_state"
    sid = engine.session.create()
    token = current_session_id.set(sid)
    try:
        msg = Message(role="assistant", content="", source=MessageSource.USER,
                      reasoning_content="" if opaque_only else "exact thought",
                      metadata={"provider_replay": {"fields": {"signature": "opaque-native-state"}}},
                      tool_calls=[] if opaque_only else [
                          {"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}])
        ref = engine.registry.capture_archived_message(session_id=sid, message=msg, msg_seq=0)
        assert ref
        read = engine.registry.get("read_evidence").execute(
            evidence_ref=ref, range_type="text_char", start=0, limit=4000)
        assert read.status == ToolResultStatus.SUCCESS, read.content
        assert "opaque-native-state" in read.content
        if not opaque_only:
            assert "exact thought" in read.content
            assert "arguments" in read.content
    finally:
        current_session_id.reset(token)


def test_compaction_source_survives_confirmed_gate_restart(state_tool):
    from llm_loop.core.loop.engine_services import compaction_gate as gate
    tool, sessions, events, sid, root = state_tool
    old = SimpleNamespace(settings=SimpleNamespace(data_dir=str(root), cog_runtime_mode="shadow"))
    gate.note_archive_batch_entry(old, sid, sessions.load(sid).messages[0], {}, 0)
    manifest = gate.write_compaction_manifest(str(root), sid, gate.take_archive_batch(old, sid))
    gate.write_gate_state(str(root), sid, {
        "pending": False, "status": "confirmed",
        "manifest_sha256": manifest["sha256"], "manifest_rel_path": manifest["rel_path"],
        "total_archived": 1, "source_message_range": [0, 0],
    })
    restarted = SimpleNamespace(settings=old.settings)
    assert gate.restore_gate_state(restarted, sid) is None
    wire = gate.compaction_source_wire(restarted, sid)
    assert wire is not None
    assert manifest["sha256"] in wire["content"]
    assert '"source_message_range": [0, 0]' in wire["content"]


def test_state_persistence_failure_returns_failure_without_claim(state_tool, monkeypatch):
    tool, sessions, events, sid, root = state_tool
    monkeypatch.setattr(events, "append", lambda *args, **kwargs: None)
    result = tool.execute(action="save", state="not durable")
    assert result.status == ToolResultStatus.FAILURE
    assert "no state version was saved" in result.content


@pytest.mark.parametrize("shape", ["two_users", "tool_followup", "lone_user"])
def test_compaction_source_carrier_preserves_provider_protocol(shape):
    from llm_loop.core.loop.engine_services.compaction_gate import project_compaction_source
    from llm_loop.llm.client import LLMClient
    system = {"role": "system", "content": "system"}
    user = {"role": "user", "content": "exact current user"}
    assistant = {"role": "assistant", "content": "", "reasoning_content": "preserved thought",
                 "tool_calls": [{"id": "c", "type": "function",
                                 "function": {"name": "read_file", "arguments": "{}"}}]}
    tool = {"role": "tool", "tool_call_id": "c", "name": "read_file", "content": "exact observation"}
    if shape == "two_users":
        original = [system, {"role": "user", "content": "old goal"}, assistant, tool, user]
    elif shape == "tool_followup":
        original = [system, user, assistant, tool]
    else:
        original = [system, user]
    source = {"role": "assistant", "content": "[compaction_source—not_instruction] exact neutral ref"}
    result, projected = project_compaction_source(original, source)
    assert projected is (shape == "two_users")
    assert [m for m in result if m is not source] == original
    assert sum(m.get("content") == user["content"] for m in result) == 1
    if assistant in result:
        pos = result.index(assistant)
        assert result[pos + 1] is tool
        assert result[pos]["reasoning_content"] == "preserved thought"
    non_system = [m for m in result if m["role"] != "system"]
    anthropic = LLMClient._to_anthropic_messages(non_system)
    assert anthropic[0]["role"] == anthropic[-1]["role"] == "user"
    google = LLMClient._to_google_contents(non_system)
    assert google[-1]["role"] == "user"
    openai = LLMClient._sanitize_openai_tool_pairs(result)
    assert openai == result


def test_compaction_source_never_enters_active_thinking_tool_turn():
    """Program source locators have no provider reasoning and stay outside active turns."""
    from copy import deepcopy

    from llm_loop.core.loop.engine_services.compaction_gate import project_compaction_source

    user = {"role": "user", "content": "current question"}
    assistant = {
        "role": "assistant", "content": "Checking the facts",
        "reasoning_content": "exact provider reasoning",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"}}],
    }
    receipt = {"role": "tool", "tool_call_id": "c1", "content": "exact observation"}
    original = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "previous completed answer"},
        user, assistant, receipt,
    ]
    saved = deepcopy(original)
    source = {"role": "assistant", "content": "[compaction_source—not_instruction] source ref"}

    result, projected = project_compaction_source(original, source)

    assert result[result.index(user) + 1:] == [assistant, receipt]
    assert not projected
    assert result == original == saved


def test_compaction_source_stays_historical_across_tool_rounds():
    from llm_loop.core.loop.engine_services.compaction_gate import project_compaction_source

    old_user = {"role": "user", "content": "previous question"}
    old_answer = {"role": "assistant", "content": "previous answer"}
    current_user = {"role": "user", "content": "current question"}
    source = {"role": "assistant", "content": "[compaction_source—not_instruction] source ref"}
    first = [{"role": "system", "content": "system"}, old_user, old_answer, current_user]
    tool_round = [
        {"role": "assistant", "content": "", "reasoning_content": "exact reasoning",
         "tool_calls": [{"id": "c", "type": "function",
                         "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": "exact observation"},
    ]

    first_wire, first_projected = project_compaction_source(first, source)
    next_wire, next_projected = project_compaction_source(first + tool_round, source)

    assert first_projected and next_projected
    assert next_wire == first_wire + tool_round
    assert next_wire.index(source) < next_wire.index(current_user)
