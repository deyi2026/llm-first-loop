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
