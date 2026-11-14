"""Mechanical pre-send check for the latest completed tool observation.

This initial batch proves only an exact, paired raw exchange in the provider
view. It deliberately does not treat durable storage, arbitrary evidence://
text, repeat hints or a matching tool-call ID as proof of model visibility.
A validated owner-scoped exact-ref projection is a separate gated capability;
until it exists, missing raw observations must HOLD before Provider send.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any


def _field(message: Any, name: str) -> Any:
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def _role(message: Any) -> str:
    return str(_field(message, "role") or "")


def _call_signature(call: Any) -> tuple[str, str, str]:
    if isinstance(call, dict):
        fn = call.get("function") or call
        call_id = call.get("id")
        name = fn.get("name") if isinstance(fn, dict) else ""
        args = fn.get("arguments") if isinstance(fn, dict) else None
    else:
        call_id = getattr(call, "id", None)
        name = getattr(call, "name", "")
        args = getattr(call, "arguments", None)
    if isinstance(args, str):
        with contextlib.suppress(ValueError, TypeError):
            args = json.loads(args)
    encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return str(call_id or ""), str(name or ""), encoded


def _calls(message: Any) -> tuple[tuple[str, str, str], ...]:
    return tuple(_call_signature(call) for call in (_field(message, "tool_calls") or ()))


def latest_completed_tool_group(messages: list[Any], after_ref: int | None) -> dict | None:
    """Return latest same-run group and its *exact* persisted observations.

    None means no assistant tool call after the known current-run ingress. An
    incomplete/ambiguous group is returned as invalid, never treated as absent.
    Unknown ingress identity must not scan and confuse earlier Runs.
    """
    if not isinstance(after_ref, int) or not 0 <= after_ref < len(messages):
        return None
    latest: dict | None = None
    for index in range(after_ref + 1, len(messages)):
        assistant = messages[index]
        if _role(assistant) != "assistant":
            continue
        calls = _calls(assistant)
        if not calls:
            continue
        ids = [call[0] for call in calls]
        latest = {"index": index, "call_ids": ids, "valid": False}
        if not all(ids) or len(ids) != len(set(ids)):
            continue
        receipts: dict[str, str] = {}
        j = index + 1
        while j < len(messages) and _role(messages[j]) == "tool":
            tool_id = str(_field(messages[j], "tool_call_id") or "")
            if not tool_id or tool_id not in ids or tool_id in receipts:
                break
            receipts[tool_id] = str(_field(messages[j], "content") or "")
            j += 1
        if set(receipts) == set(ids) and all(receipts.values()):
            latest = {
                "index": index,
                "call_ids": ids,
                "calls": calls,
                "receipts": receipts,
                "valid": True,
            }
    return latest


def group_visible_in_provider_view(
    group: dict | None,
    provider_messages: list[dict],
    *,
    active_ingress_ref: str = "",
) -> bool:
    """Compare exact source call arguments and tool contents after active ingress.

    A same-ID but altered/truncated/placeholder result is NOT raw visibility.
    An unverified ref string is NOT raw visibility. All tool receipts must be
    consecutive and protocol-paired, with no duplicates or foreign IDs.
    """
    if group is None:
        return True
    if not group.get("valid"):
        return False
    start = 0
    if active_ingress_ref:
        for i, message in enumerate(provider_messages):
            if str(message.get("_active_run_ingress_ref") or "") == active_ingress_ref:
                start = i + 1
                break
        else:
            return False
    expected_calls = group["calls"]
    expected_receipts = group["receipts"]
    for i in range(start, len(provider_messages)):
        assistant = provider_messages[i]
        if _role(assistant) != "assistant" or _calls(assistant) != expected_calls:
            continue
        segment = provider_messages[i + 1 : i + 1 + len(expected_receipts)]
        if len(segment) != len(expected_receipts):
            continue
        observed: dict[str, str] = {}
        for tool in segment:
            if _role(tool) != "tool":
                break
            tool_id = str(_field(tool, "tool_call_id") or "")
            content = str(_field(tool, "content") or "")
            if tool_id not in expected_receipts or tool_id in observed:
                break
            observed[tool_id] = content
        if observed == expected_receipts:
            return True
    return False
