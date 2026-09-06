#!/usr/bin/env python3
"""Deterministic S0 selective-evidence shadow contract benchmark.

This benchmark accepts evidence IDs as if they came from a model checkpoint response,
then measures only identity/size mechanics. It never changes provider history, never
persists a checkpoint, and never chooses evidence on behalf of the model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from llm_loop.core.episode_history import (
    collect_active_evidence_groups,
    evidence_candidate_set_digest,
    measure_evidence_selection_shadow,
)
from llm_loop.core.message import Message, MessageSource, ToolResultStatus


def _assistant(call_id: str, tool_name: str, arguments: dict[str, Any]) -> Message:
    return Message(
        role="assistant",
        content="checking",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                },
            }
        ],
        model_used="shadow-fixture",
        metadata={"answer_origin": "model"},
    )


def _tool(call_id: str, tool_name: str, chars: int) -> Message:
    prefix = f"call={call_id};tool={tool_name};"
    content = prefix + (call_id[-1:].upper() or "X") * max(0, chars - len(prefix))
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=ToolResultStatus.SUCCESS,
        tool_name=tool_name,
        metadata={
            "recoverability_status": "recorded",
            "evidence_ref": f"evidence://v1/shadow-{call_id}",
        },
    )


def _wire_digest(messages: list[Message]) -> str:
    wire = [message.to_llm_dict() for message in messages]
    payload = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_fixture(raw_chars: int) -> list[Message]:
    messages = [Message(role="user", content="shadow selection fixture", source=MessageSource.USER)]
    specs = [
        ("c1", "read_file", {"path": "src/a.py"}),
        ("c2", "grep", {"pattern": "alpha"}),
        ("c3", "read_file", {"path": "src/b.py"}),
        ("c4", "git_diff", {"path": "src/b.py"}),
    ]
    for call_id, tool_name, arguments in specs:
        messages.append(_assistant(call_id, tool_name, arguments))
        messages.append(_tool(call_id, tool_name, raw_chars))
    messages.append(
        Message(
            role="assistant",
            content="evidence acquired",
            source=MessageSource.USER,
            model_used="shadow-fixture",
            metadata={"answer_origin": "model"},
        )
    )
    return messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected-ids", nargs="+", default=["e2", "e4"])
    parser.add_argument("--raw-chars", type=int, default=4096)
    args = parser.parse_args()

    messages = build_fixture(max(1, args.raw_chars))
    before = _wire_digest(messages)
    groups = collect_active_evidence_groups(messages)
    stats = measure_evidence_selection_shadow(groups, args.selected_ids)
    after = _wire_digest(messages)
    result = {
        "candidate_set_digest": evidence_candidate_set_digest(groups),
        "catalog": [group.descriptor.to_catalog_dict() for group in groups],
        "selection": stats.to_dict(),
        "provider_history_changed": before != after,
        "provider_history_sha256": after,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not stats.selection_valid or before != after:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
