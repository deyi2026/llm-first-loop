"""Prompt-neutral runtime causality substrate.

The recorder exists to preserve mechanical provenance for later diagnosis without
changing model-visible messages/tools or introducing hidden model calls.  Expensive
comparison/diagnosis is intentionally deferred to read-only tooling.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import llm_loop
from llm_loop.runtime.manifest import read_manifest


@dataclass(frozen=True, slots=True)
class RuntimeCausalSnapshot:
    """One process/source/config identity snapshot, built outside request hot paths."""

    snapshot_id: str
    pid: int
    git_head: str
    config_hash: str
    providers_effective_hash: str
    source_tree_fp: str
    tool_registry_fp: str
    rules_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=1)
def source_tree_fingerprint() -> str:
    """Hash loaded package source tree once per process; never rescan per request."""
    root = Path(llm_loop.__file__).resolve().parent
    digest = hashlib.sha256()
    try:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(rel).to_bytes(4, "big"))
            digest.update(rel)
            raw = path.read_bytes()
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    except OSError:
        return ""
    return digest.hexdigest()


def _rules_version() -> str:
    workspace = Path(llm_loop.__file__).resolve().parents[2]
    path = workspace / "docs" / "ai_rules.lite.md"
    try:
        head = path.read_text(encoding="utf-8")[:512]
    except OSError:
        return ""
    match = re.search(r"version\s*=\s*(\d+)", head)
    return match.group(1) if match else ""


def _tool_registry_fingerprint(registry: Any, *, lazy: bool) -> str:
    try:
        schemas = registry.schemas(lazy=lazy)
        raw = json.dumps(
            schemas,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    except Exception:  # noqa: BLE001 - observability must not block engine construction
        return ""
    return _sha256_bytes(raw)


def build_runtime_causal_snapshot(settings: Any, registry: Any) -> RuntimeCausalSnapshot:
    """Build one immutable runtime identity card outside provider request hot paths."""
    manifest = read_manifest(getattr(settings, "data_dir", "")) or {}
    payload = {
        "pid": os.getpid(),
        "git_head": str(manifest.get("git_head") or ""),
        "config_hash": str(manifest.get("config_hash") or ""),
        "providers_effective_hash": str(manifest.get("providers_effective_hash") or ""),
        "source_tree_fp": source_tree_fingerprint(),
        "tool_registry_fp": _tool_registry_fingerprint(
            registry, lazy=bool(getattr(settings, "tool_schema_lazy", False))
        ),
        "rules_version": _rules_version(),
    }
    snapshot_id = _sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )[:24]
    return RuntimeCausalSnapshot(snapshot_id=snapshot_id, **payload)


def effective_generation_contract(client: Any) -> dict[str, Any]:
    """Return mechanical effective client values only; no quality/capability inference."""
    return {
        "provider": str(getattr(client, "provider", "") or ""),
        "model": str(getattr(client, "model", "") or ""),
        "max_tokens": getattr(client, "max_tokens", None),
        "temperature": getattr(client, "temperature", None),
        "top_p": getattr(client, "top_p", None),
        "top_k": getattr(client, "top_k", None),
        "min_p": getattr(client, "min_p", None),
        "wire_protocol": str(getattr(client, "wire_protocol", "") or ""),
        "send_tool_choice": bool(getattr(client, "send_tool_choice", True)),
        "reasoning_split": bool(getattr(client, "reasoning_split", False)),
    }


def background_run_generation_fact(engine: Any, session_id: str) -> dict[str, str]:
    """Observe exact BackgroundRunner generation without granting resume authority.

    No/disabled runner or no active background handle means this provider request is not
    mechanically bound to a background generation. Observation faults stay explicit as
    ``unknown``; they never become permission to resume/rebind.
    """
    runner = getattr(engine, "runner", None)
    if runner is None or not bool(getattr(runner, "enabled", False)):
        return {"state": "not_background", "generation": ""}
    getter = getattr(runner, "get_handle", None)
    if not callable(getter):
        return {"state": "unknown", "generation": ""}
    try:
        snap = getter(session_id)
    except Exception:  # noqa: BLE001 - observability only
        return {"state": "unknown", "generation": ""}
    if snap is None:
        return {"state": "not_background", "generation": ""}
    if not isinstance(snap, dict):
        return {"state": "unknown", "generation": ""}
    generation = str(snap.get("run_generation") or "")
    if generation and str(snap.get("status") or "") == "running":
        return {"state": "bound", "generation": generation}
    return {"state": "unknown", "generation": ""}


def build_run_integrity_receipt(
    *,
    session_id: str,
    background_run: dict[str, Any],
    origin_ingress_channel: str,
    current_ingress_channel: str,
    current_ingress_entry: str,
    workspace_epoch: int,
    queue_id: str,
    routing_identity: dict[str, Any],
    provider: str,
    model: str,
    generation_contract: dict[str, Any],
    provider_call_id: str,
    attempt_id: str,
    system_fp: str,
    tools_fp: str,
    runtime_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build a thin immutable mechanical identity receipt for one provider attempt.

    This function classifies no task/content state and carries no admission/completion
    authority.  It only copies already-established run/request facts into one audit view.
    """
    state = str(background_run.get("state") or "unknown")
    if state not in {"bound", "not_background", "unknown"}:
        state = "unknown"
    generation = (
        str(background_run.get("generation") or "") if state == "bound" else ""
    )
    actual_provider = str(provider or "")
    actual_model = str(model or "")
    contract = dict(generation_contract or {})
    contract["provider"] = actual_provider
    contract["model"] = actual_model
    runtime = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    try:
        epoch = int(routing_identity.get("epoch") or 0)
    except (TypeError, ValueError):
        epoch = 0
    try:
        ws_epoch = int(workspace_epoch)
    except (TypeError, ValueError):
        ws_epoch = 0
    return {
        "schema": "run-integrity/v1",
        "session_id": str(session_id or ""),
        "background_run_generation": generation,
        "run_generation_state": state,
        "origin_ingress_channel": str(origin_ingress_channel or ""),
        "current_ingress_channel": str(current_ingress_channel or ""),
        "current_ingress_entry": str(current_ingress_entry or ""),
        "workspace_epoch": ws_epoch,
        "queue_id": str(queue_id or ""),
        "routing_epoch": epoch,
        "routing_registry_fp": str(routing_identity.get("registry_fp") or ""),
        "routing_transition": str(routing_identity.get("transition") or ""),
        "provider": actual_provider,
        "model": actual_model,
        "generation_contract": contract,
        "provider_call_id": str(provider_call_id or ""),
        "attempt_id": str(attempt_id or ""),
        "system_fp": str(system_fp or ""),
        "tools_fp": str(tools_fp or ""),
        "runtime_snapshot_id": str(runtime.get("snapshot_id") or ""),
        "tool_registry_fp": str(runtime.get("tool_registry_fp") or ""),
    }



def provider_message_shape(messages: list[dict]) -> dict[str, int]:
    """Return cheap provider-message shape facts without serializing message content."""
    tail_user_run = 0
    for message in reversed(messages):
        if message.get("role") != "user":
            break
        tail_user_run += 1
    return {
        "messages_count": len(messages),
        "tail_user_run": tail_user_run,
    }

def exceptional_attempt_payload(
    *,
    attempt_id: str,
    kind: str,
    attempt_index: int,
    round_no: int,
    client: Any,
    messages: list[dict],
    tools: list[dict],
    transform: dict[str, Any] | None = None,
    provider_call_id: str | None = None,
) -> dict[str, Any]:
    """Build bounded facts for a real non-primary provider attempt.

    Exceptional paths may pay one serialization because they are not the normal hot path.
    """
    history_chars = sum(len(str(m.get("content", "") or "")) for m in messages)
    reasoning_chars = sum(len(str(m.get("reasoning_content", "") or "")) for m in messages)
    try:
        serialized = json.dumps(
            {"messages": messages, "tools": tools},
            ensure_ascii=False, separators=(",", ":"), default=str,
        )
        visible_chars = len(serialized)
        structure_fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    except (TypeError, ValueError):
        visible_chars = history_chars + reasoning_chars
        structure_fp = ""
    contract = effective_generation_contract(client)
    message_shape = provider_message_shape(messages)
    return {
        "round": int(round_no or 0),
        "attempt_id": str(attempt_id or ""),
        "provider_call_id": str(provider_call_id or ""),
        "attempt_kind": str(kind or "unknown"),
        "attempt_index": int(attempt_index or 0),
        "provider": contract["provider"],
        "model": contract["model"],
        "tools_count": len(tools),
        **message_shape,
        "history_chars": history_chars,
        "reasoning_chars": reasoning_chars,
        "provider_visible_chars": visible_chars,
        "provider_structure_fp": structure_fp,
        "generation_contract": contract,
        "transform": dict(transform or {}),
    }
