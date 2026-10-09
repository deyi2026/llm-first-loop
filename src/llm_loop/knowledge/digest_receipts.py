"""Mechanical joins of recorded transport facts; no attention or benefit verdict."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from llm_loop.event_log.model import Event


def event_ref(event: Event) -> str:
    return f"event:{event.session_id}:{event.event_id}"


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def observation(event: Event) -> dict[str, Any]:
    return {"event_ref": event_ref(event), "seq": event.seq,
            "payload_sha256": payload_sha256(event.payload), "payload": dict(event.payload)}


def transport_pairs(events: list[Event]) -> list[dict[str, Any]]:
    if len({e.session_id for e in events}) > 1:
        raise ValueError("mixed session scope")
    groups: dict[tuple[str, str], dict[str, list[Event]]] = defaultdict(
        lambda: {"opened": [], "settled": []}
    )
    prepared: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for event in events:
        p = event.payload
        if event.type == "knowledge.reference_prepared":
            prepared[(str(p.get("run_ref", "")), str(p.get("knowledge_event_key", "")))].append(event)
        if event.type in {"provider.transport.opened", "provider.transport.settled"}:
            key = str(p.get("call_id") or ""), str(p.get("attempt_id") or "")
            groups[key][event.type.rsplit(".", 1)[1]].append(event)
    return [_pair(key, group, prepared) for key, group in groups.items()]


def _pair(
    key: tuple[str, str], group: dict[str, list[Event]],
    prepared: dict[tuple[str, str], list[Event]],
) -> dict[str, Any]:
    opens, settles = group["opened"], group["settled"]
    result: dict[str, Any] = {
        "call_id": key[0], "attempt_id": key[1], "pairing": "unknown",
        "opened_refs": [event_ref(e) for e in opens], "settled_refs": [event_ref(e) for e in settles],
        "knowledge_delivery": "unknown", "model_attention": "unknown",
        "usage": None, "usage_observations": None, "references": [],
        "usage_state": "unknown",
    }
    if not all(key) or len(opens) != 1 or len(settles) != 1 or opens[0].seq >= settles[0].seq:
        result["detail"] = "missing, ambiguous or out-of-order transport identity"
        return result
    opened, settled = opens[0].payload, settles[0].payload
    result.update(pairing="matched", outcome=settled.get("outcome"),
                  status_code=settled.get("status_code"), usage=settled.get("usage"),
                  usage_observations=settled.get("usage_observations"),
                  model_id=opened.get("model_id"), provider_id=opened.get("provider_id"))
    observations = settled.get("usage_observations")
    if (isinstance(observations, int) and not isinstance(observations, bool)
            and observations > 0 and isinstance(settled.get("usage"), dict)):
        result["usage_state"] = "observed"
    facts = opened.get("prepared")
    refs = facts.get("knowledge_references") if isinstance(facts, dict) else None
    if not isinstance(refs, list) or not refs:
        result["knowledge_delivery"] = "not_observed"
        return result
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        run = ref.get("run_ref")
        binding = ref.get("knowledge_event_key")
        candidates = prepared.get((str(run or ""), str(binding or "")), [])
        sha = ref.get("reference_sha256")
        if (
            len(candidates) == 1 and run and binding
            and candidates[0].seq < opens[0].seq
            and candidates[0].payload.get("refs") == ref.get("refs")
            and candidates[0].payload.get("reference_chars") == ref.get("reference_chars")
            and isinstance(sha, str) and re.fullmatch("[0-9a-f]{64}", sha)
        ):
            result["references"].append({**ref, "prepared_event_ref": event_ref(candidates[0])})
    code = settled.get("status_code")
    if len(result["references"]) == len(refs):
        if isinstance(code, int) and 200 <= code < 300 and settled.get("outcome") == "success":
            result["knowledge_delivery"] = "http_success_observed"
        elif isinstance(code, int) and code >= 400:
            result["knowledge_delivery"] = "http_error_observed"
    return result
