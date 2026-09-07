"""P4 deterministic handoff qualification over real files and durable stores.

This test intentionally has no model call. It proves the mechanical substrate for the
subsequent one-model experiment: versioned AI effects, authenticated human effects,
conflict preservation, process/Engine reconstruction, and same-session continuation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_workspace_root
from llm_loop.factory import build_engine
from llm_loop.tools.registry import tool_result_to_message
from llm_loop.workspace.human_file_ops import HumanFileOperationError

WORKSPACE_ID = "p4-human-ai-continuity"
AI_MARKER = "AI_MARKER: completed"
HUMAN_NOTE = "HUMAN_NOTE: preserve-this"


def _settings(data_dir: Path) -> Settings:
    # No request is made in this deterministic test; the endpoint is deliberately invalid.
    return Settings(
        llm_api_key="not-used",
        llm_base_url="http://127.0.0.1:9/v1",
        llm_model="p4-no-model",
        data_dir=str(data_dir),
        max_iterations=8,
        cache_hit_show_in_answer=False,
        summary_mode="off",
    )


def _write_fixture(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 7):
        (workspace / f"item{idx}.txt").write_text(
            f"ITEM: {idx}\nSTATUS: pending\nKEEP: keep-{idx}\n",
            encoding="utf-8",
        )


def _versioned_ai_edit(engine, sid: str, workspace: Path, relative_path: str, round_no: int) -> None:
    """Exercise the same durable effect path used by the model tool loop."""
    engine.registry.set_session_id(sid)
    token = current_workspace_root.set(str(workspace))
    try:
        read_call = ToolCall(
            id=f"read-{round_no}",
            name="read_file",
            arguments={"path": relative_path, "snapshot": True},
        )
        read_result = engine.registry.execute(read_call)
        assert read_result.status.value == "success"
        assert read_result.artifact_facts
        snapshot_ref = str(read_result.artifact_facts[0]["artifact_ref"])

        edit_call = ToolCall(
            id=f"edit-{round_no}",
            name="edit_file",
            arguments={
                "path": relative_path,
                "old_string": "STATUS: pending\n",
                "new_string": f"STATUS: reviewed\n{AI_MARKER}\n",
                "expected_snapshot_ref": snapshot_ref,
            },
        )
        sess = engine.session.load(sid)
        execution_id = engine._tool_execution_declared(sess, edit_call, round_no=round_no)  # noqa: SLF001
        assert engine._tool_execution_started(  # noqa: SLF001
            sid, execution_id=execution_id, round_no=round_no, call=edit_call
        )
        journal = engine._tool_execution_journal()  # noqa: SLF001
        with journal.effect_bindings(
            session_id=sid,
            execution_ids={edit_call.id: execution_id},
            round_no=round_no,
            calls=[edit_call],
            workspace_root=str(workspace),
        ):
            result = engine.registry.execute(edit_call)
        assert result.status.value == "success", result.content
        tool_message = tool_result_to_message(
            result, failure_guidance_enabled=engine.registry.failure_guidance_enabled
        )
        state_sha = engine._tool_execution_finished(  # noqa: SLF001
            sid,
            execution_id=execution_id,
            round_no=round_no,
            call=edit_call,
            tool_message=tool_message,
        )
        assert state_sha
        assert engine._tool_execution_receipt_committed(  # noqa: SLF001
            sid,
            execution_id=execution_id,
            round_no=round_no,
            tool_call_id=edit_call.id,
            tool_name=edit_call.name,
            result_state_sha256=state_sha,
            tool_message=tool_message,
        )
    finally:
        current_workspace_root.reset(token)


def test_p4_sequential_human_ai_handoff_survives_engine_reconstruction(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    _write_fixture(workspace)

    first = build_engine(_settings(data_dir))
    first.set_workspace(str(workspace), workspace_id=WORKSPACE_ID)
    sid = first.session.create()
    human = first.human_file_operations
    assert human is not None

    # A stale human draft exists before the model changes item1.
    stale_item1 = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="item1.txt"
    )

    # Model-side coordinated writes for the first two items.
    _versioned_ai_edit(first, sid, workspace, "item1.txt", 1)
    _versioned_ai_edit(first, sid, workspace, "item2.txt", 2)

    # Human takes over item2 from a fresh observation and adds durable content.
    item2_obs = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="item2.txt"
    )
    human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="p4-human-item2",
        relative_path="item2.txt",
        expected_snapshot_ref=item2_obs.snapshot_ref,
        content=item2_obs.content + HUMAN_NOTE + "\n",
        file_contract_version=1,
    )

    # A stale draft cannot overwrite item1 after the model has changed it.
    with pytest.raises(HumanFileOperationError, match="version_conflict"):
        human.edit(
            session_id=sid,
            workspace_scope=str(workspace),
            request_id="p4-stale-item1",
            relative_path="item1.txt",
            expected_snapshot_ref=stale_item1.snapshot_ref,
            content=stale_item1.content + "STALE: must-not-land\n",
            file_contract_version=1,
        )
    assert "STALE: must-not-land" not in (workspace / "item1.txt").read_text(encoding="utf-8")

    # Process/Engine reconstruction: new objects, same durable data/session/workspace.
    del human
    del first
    resumed = build_engine(_settings(data_dir))
    resumed.set_workspace(str(workspace), workspace_id=WORKSPACE_ID)
    assert resumed.session.exists(sid)

    effects = resumed.file_effect_query
    assert effects is not None
    page = effects.query(session_id=sid, workspace_scope=str(workspace), limit=50)
    origins = [receipt.origin for receipt in page.receipts]
    assert origins.count("model_tool") >= 2
    assert origins.count("authenticated_user") >= 2  # successful save + stale rejection
    assert any(r.path == "item2.txt" and r.origin == "authenticated_user" for r in page.receipts)

    # Continue the remaining mechanical work after reconstruction.
    for round_no, idx in enumerate(range(3, 7), start=3):
        _versioned_ai_edit(resumed, sid, workspace, f"item{idx}.txt", round_no)

    for idx in range(1, 7):
        text = (workspace / f"item{idx}.txt").read_text(encoding="utf-8")
        assert "STATUS: reviewed" in text
        assert text.count(AI_MARKER) == 1
        assert f"KEEP: keep-{idx}" in text
        if idx == 2:
            assert HUMAN_NOTE in text
        else:
            assert HUMAN_NOTE not in text

    # The handoff does not fabricate conversation messages.
    stored = resumed.session.load(sid)
    assert stored.messages == []
