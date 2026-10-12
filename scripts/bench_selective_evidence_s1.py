#!/usr/bin/env python3
"""Deterministic provider-free S1 selective-evidence restart canary.

This exercises only mechanical protocol/session behavior:
Session checkpoint persistence -> JSON/event-log restart -> selected raw exemption
-> unselected receipt projection. It never asks a program policy to select evidence.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from llm_loop.core.episode_history import (
    build_working_state_checkpoint,
    project_active_tool_working_set_with_stats,
    resolve_working_state_checkpoint,
)
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.session import Session, SessionStore
from llm_loop.event_log.store import EventStore


def assistant(call_id: str) -> Message:
    return Message(
        role="assistant",
        content="checking",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
        model_used="canary-model",
        metadata={"answer_origin": "model"},
    )


def tool(call_id: str, content: str, *, ref: str | None) -> Message:
    metadata = {}
    if ref is not None:
        metadata = {"recoverability_status": "recorded", "evidence_ref": ref}
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=ToolResultStatus.SUCCESS,
        tool_name="read_file",
        metadata=metadata,
    )


def followup() -> Message:
    return Message(
        role="assistant",
        content="continue",
        source=MessageSource.USER,
        model_used="canary-model",
        metadata={"answer_origin": "model"},
    )


def messages() -> list[Message]:
    return [
        Message(role="user", content="mechanical canary", source=MessageSource.USER),
        assistant("c1"),
        tool("c1", "SELECTED_RAW_" * 500, ref=None),
        followup(),
        assistant("c2"),
        tool("c2", "UNSELECTED_RAW_" * 500, ref="evidence://v1/unselected"),
        followup(),
        assistant("c3"),
        tool("c3", "LATEST_RAW_" * 500, ref="evidence://v1/latest"),
    ]


def run() -> dict[str, object]:
    old_receipts = os.environ.get("LFL_TOOL_WORKING_SET_RECEIPTS")
    old_batch = os.environ.get("LFL_TOOL_WORKING_SET_BATCH_CHARS")
    old_grace = os.environ.get("LFL_TOOL_WORKING_SET_GRACE_GROUPS")
    os.environ["LFL_TOOL_WORKING_SET_RECEIPTS"] = "1"
    os.environ["LFL_TOOL_WORKING_SET_BATCH_CHARS"] = "4096"
    os.environ["LFL_TOOL_WORKING_SET_GRACE_GROUPS"] = "0"
    try:
        with tempfile.TemporaryDirectory(prefix="lfl-s1-canary-") as tmp:
            root = Path(tmp)
            event_store = EventStore(root / "event_logs", enabled=True)
            store = SessionStore(root / "sessions", event_store=event_store)
            raw = messages()
            session = Session(session_id="s1-canary", messages=raw)
            store.save(session)
            checkpoint = build_working_state_checkpoint(
                session_id=session.session_id,
                messages=session.messages,
                provider_id="deepseek",
                model="deepseek/model",
                selected_ids=["e1"],
                state_text='{"verdict":"ready","next":"final"}',
                state_char_limit=1024,
                selected_raw_char_limit=20000,
            )
            session.working_state_checkpoint = checkpoint
            store.save(session)

            json_loaded = SessionStore(root / "sessions").load(session.session_id)
            event_loaded = SessionStore(
                root / "sessions",
                event_store=event_store,
                read_path_source="event_log",
            ).load(session.session_id)
            if json_loaded.working_state_checkpoint != checkpoint:
                raise RuntimeError("session_json checkpoint restart mismatch")
            if event_loaded.working_state_checkpoint != checkpoint:
                raise RuntimeError("event_log checkpoint restart mismatch")
            if any(m.content == checkpoint["state_text"] for m in json_loaded.messages):
                raise RuntimeError("checkpoint state leaked into Session messages")

            resolution = resolve_working_state_checkpoint(
                json_loaded.working_state_checkpoint,
                session_id=json_loaded.session_id,
                messages=json_loaded.messages,
                provider_id="deepseek",
                model="deepseek/model",
            )
            if not resolution.eligible:
                raise RuntimeError(f"checkpoint ineligible after restart: {resolution.reason}")
            projected, stats = project_active_tool_working_set_with_stats(
                json_loaded.messages,
                preserve_group_digests=resolution.preserve_group_digests,
            )
            selected_raw = projected[2].content == json_loaded.messages[2].content
            unselected_receipt = "tool_result_receipt" in projected[5].content
            latest_raw = projected[8].content == json_loaded.messages[8].content
            if not (selected_raw and unselected_receipt and latest_raw):
                raise RuntimeError("selected/raw receipt projection contract failed")
            return {
                "eligible": resolution.eligible,
                "selected_group_count": len(resolution.preserve_group_digests),
                "selected_raw_chars": resolution.selected_raw_chars,
                "folded_groups": stats.folded_groups,
                "selected_raw": selected_raw,
                "unselected_receipt": unselected_receipt,
                "latest_raw": latest_raw,
                "json_restart": True,
                "event_log_restart": True,
                "session_message_count": len(json_loaded.messages),
                "state_in_session_messages": False,
            }
    finally:
        for key, value in (
            ("LFL_TOOL_WORKING_SET_RECEIPTS", old_receipts),
            ("LFL_TOOL_WORKING_SET_BATCH_CHARS", old_batch),
            ("LFL_TOOL_WORKING_SET_GRACE_GROUPS", old_grace),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
