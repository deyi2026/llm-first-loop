"""Qualification-only exact ActionRef hydration for P4-FCR v0.2.

This helper has no production registration, Browser execution, retry, target
selection, similarity matching, rebind or task-completion authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = runpy.run_path(str(ROOT / "evals/smc_semantic_logic_p4_fcr_v02/protocol.py"))
ARM_B_TOOLS: dict[str, dict[str, Any]] = PROTOCOL["ARM_B_TOOLS"]


class P4ActionRefError(ValueError):
    """ActionRef declaration or binding failed a mechanical exactness check."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_time(value: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


def seal_action_ref_binding(unsigned: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(unsigned)
    row["integrity"] = {
        "algorithm": "sha256",
        "digest": hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest(),
    }
    return row


def _integrity_ok(record: dict[str, Any]) -> bool:
    integrity = record.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        return False
    unsigned = {key: value for key, value in record.items() if key != "integrity"}
    return (
        integrity.get("digest") == hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
    )


class ActionRefBindingStore:
    """Exact in-memory binding store used only by deterministic qualification."""

    def __init__(
        self,
        records: list[dict[str, Any]],
        *,
        now_fn: Callable[[], str],
        version_getter: Callable[[str], str | None],
        authority_scope_getter: Callable[[str], str | None],
    ) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        for record in records:
            handle = str(record.get("action_ref") or "")
            if not handle or handle in self._records:
                raise P4ActionRefError("action_ref_binding_duplicate_or_empty")
            self._records[handle] = copy.deepcopy(record)
        self._now_fn = now_fn
        self._version_getter = version_getter
        self._authority_scope_getter = authority_scope_getter

    def resolve(
        self,
        *,
        session_id: str,
        action_ref: str,
        expected_kind: str,
    ) -> dict[str, Any]:
        record = self._records.get(action_ref)
        if record is None:
            raise P4ActionRefError("action_ref_unavailable")
        if record.get("session_id") != session_id:
            raise P4ActionRefError("action_ref_unauthorized")
        expected_authority = self._authority_scope_getter(session_id)
        if not expected_authority or record.get("authority_scope") != expected_authority:
            raise P4ActionRefError("action_ref_unauthorized")
        if not _integrity_ok(record):
            raise P4ActionRefError("action_ref_integrity_error")
        expires_at = record.get("expires_at")
        if not isinstance(expires_at, str) or _parse_time(self._now_fn()) >= _parse_time(
            expires_at
        ):
            raise P4ActionRefError("action_ref_expired")
        semantic_object_id = str(record.get("semantic_object_id") or "")
        current_version = self._version_getter(semantic_object_id)
        if current_version != record.get("observed_version"):
            raise P4ActionRefError("action_ref_stale")
        if record.get("target_kind") != expected_kind:
            raise P4ActionRefError("action_ref_kind_mismatch")
        grounding_ref = record.get("grounding_ref")
        if not isinstance(grounding_ref, str) or not grounding_ref:
            raise P4ActionRefError("action_ref_unavailable")
        return copy.deepcopy(record)


_TRANSLATION = {
    "browser_semantic_click": ("click", "object", ()),
    "browser_semantic_fill": ("fill", "object", ("text", "mode")),
    "browser_semantic_select": ("select", "object", ("value",)),
    "browser_semantic_scroll": ("scroll", "object", ("delta_pages",)),
    "browser_semantic_navigate": ("navigate", "resource", ("url",)),
}


def _validate_scalar(field: str, value: Any, spec: dict[str, Any]) -> None:
    expected_type = spec.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            raise P4ActionRefError(f"{field}_must_be_string")
        if len(value) < int(spec.get("minLength", 0)):
            raise P4ActionRefError(f"{field}_too_short")
    elif expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise P4ActionRefError(f"{field}_must_be_number")
    else:
        raise P4ActionRefError(f"{field}_unsupported_type")
    enum = spec.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise P4ActionRefError(f"{field}_not_in_enum")


def _validate_request(tool_name: str, request: dict[str, Any]) -> None:
    spec = ARM_B_TOOLS.get(tool_name)
    if spec is None:
        raise P4ActionRefError("typed_tool_not_in_v02_surface")
    params = spec["parameters"]
    required = list(params["required"])
    properties = dict(params["properties"])
    if set(request) != set(required):
        raise P4ActionRefError("typed_request_fields_mismatch")
    for field in required:
        _validate_scalar(field, request[field], properties[field])


class P4ActionRefCompiler:
    """Hydrate one model-selected ActionRef and delegate canonical compilation."""

    def __init__(
        self,
        semantic_execute: BrowserSemanticExecuteTool,
        bindings: ActionRefBindingStore,
    ) -> None:
        self._semantic_execute = semantic_execute
        self._bindings = bindings

    def canonical_request(
        self,
        session_id: str,
        tool_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise P4ActionRefError("typed_request_must_be_object")
        _validate_request(tool_name, request)
        verb, expected_kind, arg_fields = _TRANSLATION[tool_name]
        binding = self._bindings.resolve(
            session_id=session_id,
            action_ref=str(request["action_ref"]),
            expected_kind=expected_kind,
        )
        return {
            "verb": verb,
            "target_ref": str(binding["grounding_ref"]),
            "args": {field: request[field] for field in arg_fields},
        }

    def compile(
        self,
        session_id: str,
        tool_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        canonical = self.canonical_request(session_id, tool_name, request)
        return self._semantic_execute.compile_request(session_id, canonical)
