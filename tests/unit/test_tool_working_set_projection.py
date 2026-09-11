from __future__ import annotations

import os

import pytest

from llm_loop.core.episode_history import project_active_tool_working_set
from llm_loop.core.message import (
    Message,
    MessageSource,
    RecoverabilityStatus,
    ToolResult,
    ToolResultStatus,
)
from llm_loop.tools.registry import tool_result_to_message


@pytest.fixture(autouse=True)
def _isolate_tool_working_set_env(monkeypatch):
    """Keep runtime-exported working-set knobs from changing test semantics."""
    for key in [k for k in os.environ if k.startswith("LFL_TOOL_WORKING_SET_")]:
        monkeypatch.delenv(key, raising=False)


def _assistant(call_id: str) -> Message:
    return Message(
        role="assistant",
        content="继续检查",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
        model_used="cognilocal/ornith",
        metadata={"answer_origin": "model"},
    )


def _tool(call_id: str, text: str, *, ref: str | None) -> Message:
    metadata = {}
    if ref:
        metadata = {
            "recoverability_status": "recorded",
            "evidence_ref": ref,
            "evidence_representation": "excerpt",
            "evidence_projection_complete": False,
            "evidence_source_label": "read_file:src/x.py",
            "evidence_coverage_label": "source_line:0-200",
        }
    return Message(
        role="tool",
        content=text,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=ToolResultStatus.SUCCESS,
        tool_name="read_file",
        metadata=metadata,
    )


def test_working_set_receipt_compacts_only_older_exposed_group(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    first_raw = "FIRST-RAW-" * 1000
    latest_raw = "LATEST-RAW-" * 1000
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", first_raw, ref="evidence://v1/first"),
        _assistant("c2"),
        _tool("c2", latest_raw, ref="evidence://v1/latest"),
    ]

    projected = project_active_tool_working_set(messages)

    assert messages[2].content == first_raw  # storage truth untouched
    assert projected[1].tool_calls == messages[1].tool_calls
    assert projected[2].tool_call_id == "c1"
    assert "tool_result_receipt" in projected[2].content
    assert "evidence_ref=evidence://v1/first" in projected[2].content
    assert "prior_full_result_exposed=true" in projected[2].content
    assert projected[4].content == latest_raw  # newest group must stay fully visible


def test_working_set_receipt_fails_open_without_durable_ref(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    raw = "NO-DURABLE-REF" * 100
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", raw, ref=None),
        _assistant("c2"),
        _tool("c2", "latest", ref="evidence://v1/latest"),
    ]
    assert project_active_tool_working_set(messages)[2].content == raw


def test_working_set_receipts_keep_incomplete_batch_raw(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "32768")
    first_raw = "A" * 12000
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", first_raw, ref="evidence://v1/first"),
        _assistant("c2"),
        _tool("c2", "latest", ref="evidence://v1/latest"),
    ]
    projected = project_active_tool_working_set(messages)
    assert projected[2].content == first_raw


def test_working_set_receipts_default_off(monkeypatch):
    monkeypatch.delenv("LFL_TOOL_WORKING_SET_RECEIPTS", raising=False)
    raw = "RAW" * 100
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", raw, ref="evidence://v1/first"),
        _assistant("c2"),
        _tool("c2", "latest", ref="evidence://v1/latest"),
    ]
    projected = project_active_tool_working_set(messages)
    assert projected is messages
    assert projected[2].content == raw


def test_tool_result_helper_preserves_evidence_metadata_without_raw_wire_leak():
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="bounded projection",
        tool_call_id="c1",
        tool_name="read_file",
        recoverability_status=RecoverabilityStatus.RECORDED,
        evidence_ref="evidence://v1/abc",
        evidence_representation="excerpt",
        evidence_projection_complete=False,
        evidence_source_label="read_file:src/x.py",
        evidence_coverage_label="source_line:0-200",
        evidence_origin_facts={
            "acquired_at": "2026-09-05T01:02:03+00:00",
            "source_kind": "file",
            "source_version_policy": "probeable",
            "source_version_token": "stat:1:2",
            "provenance": {
                "producer": "tool_registry_enforce",
                "authority": "tool_observation",
                "scope": "success",
            },
        },
        source_resolution_mode="source_execution",
        source_execution_performed=True,
    )

    message = tool_result_to_message(result)
    wire = message.to_llm_dict()

    assert message.metadata["recoverability_status"] == "recorded"
    assert message.metadata["evidence_ref"] == "evidence://v1/abc"
    assert message.metadata["evidence_source_label"] == "read_file:src/x.py"
    assert message.metadata["evidence_coverage_label"] == "source_line:0-200"
    assert message.metadata["evidence_origin_facts"]["acquired_at"] == "2026-09-05T01:02:03+00:00"
    assert message.metadata["evidence_origin_facts"]["source_version_token"] == "stat:1:2"
    direct = result.to_message()
    assert direct.metadata["evidence_origin_facts"] == message.metadata["evidence_origin_facts"]
    assert "2026-09-05T01:02:03+00:00" not in wire["content"]  # metadata stays off wire until projection
    assert message.metadata["source_resolution_mode"] == "source_execution"
    assert message.metadata["source_execution_performed"] is True
    assert "evidence://v1/abc" not in wire["content"]


def test_working_set_stats_report_only_mechanical_projection_facts(monkeypatch):
    from llm_loop.core.episode_history import project_active_tool_working_set_with_stats

    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "8000")
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", "A" * 5000, ref="evidence://v1/a"),
        _assistant("c2"),
        _tool("c2", "B" * 5000, ref="evidence://v1/b"),
        _assistant("c3"),
        _tool("c3", "C" * 5000, ref="evidence://v1/c"),
    ]

    projected, stats = project_active_tool_working_set_with_stats(messages)

    assert stats.enabled is True
    assert stats.batch_chars == 8000
    assert stats.raw_tool_chars == 15000
    assert stats.folded_results == 2
    assert stats.folded_groups == 2
    assert stats.pending_raw_chars == 0
    assert stats.pending_results == 0
    assert stats.latest_raw_chars == 5000
    assert stats.fold_boundaries == (5,)
    assert stats.projected_tool_chars < stats.raw_tool_chars
    assert stats.receipt_chars == len(projected[2].content) + len(projected[4].content)
    assert projected[6].content == "C" * 5000


def test_working_set_stats_expose_incomplete_batch_without_folding(monkeypatch):
    from llm_loop.core.episode_history import project_active_tool_working_set_with_stats

    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "16000")
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", "A" * 5000, ref="evidence://v1/a"),
        _assistant("c2"),
        _tool("c2", "B" * 5000, ref="evidence://v1/b"),
    ]

    projected, stats = project_active_tool_working_set_with_stats(messages)

    assert stats.folded_results == 0
    assert stats.pending_raw_chars == 5000
    assert stats.pending_results == 1
    assert stats.latest_raw_chars == 5000
    assert stats.fold_boundaries == ()
    assert projected[2].content == "A" * 5000


def test_working_set_grace_keeps_recent_exposed_groups_raw(monkeypatch):
    from llm_loop.core.episode_history import project_active_tool_working_set_with_stats

    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "8000")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "2")
    messages = [Message(role="user", content="task", source=MessageSource.USER)]
    for idx in range(1, 6):
        messages.extend(
            [
                _assistant(f"c{idx}"),
                _tool(f"c{idx}", chr(64 + idx) * 5000, ref=f"evidence://v1/{idx}"),
            ]
        )

    projected, stats = project_active_tool_working_set_with_stats(messages)

    assert stats.grace_groups == 2
    assert stats.folded_groups == 2
    assert stats.folded_results == 2
    assert stats.grace_raw_chars == 10000
    assert stats.grace_results == 2
    assert stats.latest_raw_chars == 5000
    assert "tool_result_receipt" in projected[2].content
    assert "tool_result_receipt" in projected[4].content
    assert projected[6].content == "C" * 5000
    assert projected[8].content == "D" * 5000
    assert projected[10].content == "E" * 5000


def test_working_set_receipt_exposes_mechanical_origin_not_task_judgment(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    older = _tool("c1", "A" * 5000, ref="evidence://v1/a")
    older.metadata["evidence_origin_facts"] = {
        "acquired_at": "2026-08-28T12:00:00+00:00",
        "source_kind": "file",
        "source_version_policy": "probeable",
        "source_version_token": "stat:10:20",
        "provenance": {
            "producer": "tool_registry_enforce",
            "authority": "tool_observation",
            "scope": "success",
        },
    }
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        older,
        _assistant("c2"),
        _tool("c2", "latest", ref="evidence://v1/b"),
    ]

    receipt = project_active_tool_working_set(messages)[2].content

    assert "acquired_at=2026-08-28T12:00:00+00:00" in receipt
    assert "version_policy=probeable" in receipt
    assert "task_applicability=not_evaluated" in receipt
    # High-cardinality/verbose origin details remain recoverable, not repeated in every receipt.
    assert "version_token=" not in receipt
    assert "provenance_authority=" not in receipt
    assert "task_applicability=current" not in receipt
