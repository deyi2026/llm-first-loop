"""Bounded Browser semantic-operation orchestration.

The model declares every semantic clause.  This tool only expands those clauses into
canonical observation, exact-unique grounding, typed predicate wait, and the already
qualified single-dispatch semantic executor.  It never chooses a target, fuzzily matches,
retries a mutation, substitutes an identity, or decides task completion.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from llm_loop.browser.perception import SEMANTIC_OBJECT_KINDS, BrowserPerceptionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_wait import BrowserWaitObjectTool

_MAX_CLAUSES = 8
_IDENTITY_KEYS = {"kind", "role", "name"}
_OBJECT_VERBS = {"click", "fill", "select", "scroll"}
_MUTATION_VERBS = _OBJECT_VERBS | {"navigate"}

_OPERATION_RECEIPT_PREFIX = "browser-operation-receipt://v0.1/"
_OPERATION_RECEIPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class BrowserSemanticOperationReceiptStore:
    """Immutable, session-fenced full receipts behind compact model projections."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str, receipt_id: str) -> Path:
        return self.root / _session_hash(session_id) / f"{receipt_id}.json"

    def persist(self, session_id: str, receipt: dict[str, Any]) -> str:
        if not session_id:
            raise ValueError("session_id is required")
        canonical = json.dumps(
            receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        content_sha = hashlib.sha256(canonical).hexdigest()
        receipt_id = hashlib.sha256(
            (_session_hash(session_id) + ":" + content_sha).encode("utf-8")
        ).hexdigest()[:32]
        ref = f"{_OPERATION_RECEIPT_PREFIX}{receipt_id}"
        doc = {
            "schema": "smc.browser_semantic_operation_full_receipt.v0.1",
            "owner_session_sha256": _session_hash(session_id),
            "receipt_ref": ref,
            "content_sha256": content_sha,
            "content": receipt,
        }
        path = self._path(session_id, receipt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != doc:
                raise RuntimeError("semantic operation receipt hash collision")
            return ref
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return ref

    def hydrate(self, session_id: str, receipt_ref: str) -> dict[str, Any]:
        ref = str(receipt_ref or "").strip()
        if not ref.startswith(_OPERATION_RECEIPT_PREFIX):
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "invalid_ref"}
        receipt_id = ref[len(_OPERATION_RECEIPT_PREFIX) :]
        if _OPERATION_RECEIPT_ID_RE.fullmatch(receipt_id) is None:
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "invalid_ref"}
        path = self._path(session_id, receipt_id)
        if not path.is_file():
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "unavailable"}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "corrupt"}
        if doc.get("owner_session_sha256") != _session_hash(session_id):
            return {"grounding_ref": ref, "availability": "unauthorized", "reason": "session_scope"}
        content = doc.get("content")
        if not isinstance(content, dict):
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "corrupt"}
        canonical = json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != doc.get("content_sha256"):
            return {"grounding_ref": ref, "availability": "unavailable", "reason": "integrity_mismatch"}
        return {
            "grounding_ref": ref,
            "availability": "available",
            "content_sha256": doc["content_sha256"],
            "content": content,
        }


_MODEL_FRIENDLY_WAIT_STATES = (
    "exists",
    "enabled",
    "checked",
    "selected",
    "expanded",
    "focused",
    "editable",
)
_MODEL_FRIENDLY_DEFAULT_WAIT_MS = 60_000
_MODEL_FRIENDLY_WAIT_INTERVAL_MS = 250
_MODEL_FRIENDLY_WAIT_TEXT_FIELDS = ("name", "value_text")
_MODEL_FRIENDLY_WAIT_TEXT_MATCH = {
    "equals": "eq",
    "contains": "contains",
    "starts_with": "prefix",
    "ends_with": "suffix",
}


# Module-level because Python class-body comprehensions do not close over class locals.
# The class exposes the same schema value below for introspection/tests.
_SHORT_TARGET_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(SEMANTIC_OBJECT_KINDS)},
        "name": {"type": "string", "minLength": 1},
        "role": {"type": "string", "minLength": 1},
    },
    "required": ["kind", "name"],
    "additionalProperties": False,
}


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


class BrowserSemanticOperationContractError(ValueError):
    """Closed-contract failure before an undeclared side effect can occur."""


def _strip_first_call_schema(spec: Any) -> Any:
    """Strip prose while preserving the executable schema facts used by FC2-C."""
    if isinstance(spec, list):
        return [_strip_first_call_schema(item) for item in spec]
    if not isinstance(spec, dict):
        return spec
    keep_scalar = {
        "type",
        "const",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "additionalProperties",
    }
    out = {key: value for key, value in spec.items() if key in keep_scalar}
    enum = spec.get("enum")
    if isinstance(enum, list):
        out["enum"] = list(enum)
    required = spec.get("required")
    if isinstance(required, list):
        out["required"] = list(required)
    properties = spec.get("properties")
    if isinstance(properties, dict):
        out["properties"] = {
            str(name): _strip_first_call_schema(child)
            for name, child in properties.items()
            if isinstance(child, dict)
        }
    items = spec.get("items")
    if isinstance(items, dict):
        out["items"] = _strip_first_call_schema(items)
    for key in ("oneOf", "anyOf"):
        variants = spec.get(key)
        if isinstance(variants, list):
            out[key] = [_strip_first_call_schema(item) for item in variants]
    return out


def _const_to_singleton_enum(spec: Any) -> Any:
    """Use the already-qualified lazy enum vocabulary instead of adding const to provider wire."""
    if isinstance(spec, list):
        return [_const_to_singleton_enum(item) for item in spec]
    if not isinstance(spec, dict):
        return spec
    out = {key: _const_to_singleton_enum(value) for key, value in spec.items() if key != "const"}
    if "const" in spec:
        out.setdefault("type", "string")
        out["enum"] = [spec["const"]]
    return out


def _build_first_call_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Derive a compact three-branch call grammar from the six-branch full contract."""
    schema = _strip_first_call_schema(parameters)
    clauses = schema["properties"]["clauses"]
    branches = clauses["items"]["oneOf"]
    object_mutations = [
        branch
        for branch in branches
        if branch["properties"].get("kind", {}).get("const") == "mutate"
        and branch["properties"].get("verb", {}).get("const") != "navigate"
    ]
    navigate = next(
        branch
        for branch in branches
        if branch["properties"].get("verb", {}).get("const") == "navigate"
    )
    wait = next(
        branch
        for branch in branches
        if branch["properties"].get("kind", {}).get("const") == "wait"
    )
    if len(object_mutations) != 4:
        raise RuntimeError("bounded semantic operation object-mutation schema drift")
    mutate_required = list(object_mutations[0].get("required") or [])
    if not mutate_required or any(
        list(branch.get("required") or []) != mutate_required
        for branch in [*object_mutations, navigate]
    ):
        raise RuntimeError("bounded semantic operation mutate field-set drift")
    wait_required = list(wait.get("required") or [])
    wait_properties = wait.get("properties") or {}
    if not wait_required or "verb" in wait_properties or "args" in wait_properties:
        raise RuntimeError("bounded semantic operation wait field-set drift")
    clauses["description"] = (
        "Exact clause fields: "
        f"mutate={{{','.join(mutate_required)}}}; "
        f"wait={{{','.join(wait_required)}}}; "
        "wait has no verb/args."
    )

    object_mutation = _const_to_singleton_enum(object_mutations[0])
    object_mutation["properties"]["verb"] = {
        "type": "string",
        "enum": [branch["properties"]["verb"]["const"] for branch in object_mutations],
    }
    object_mutation["properties"]["args"] = {
        "anyOf": [
            _const_to_singleton_enum(branch["properties"]["args"])
            for branch in object_mutations
        ]
    }
    clauses["items"]["oneOf"] = [
        object_mutation,
        _const_to_singleton_enum(navigate),
        _const_to_singleton_enum(wait),
    ]
    return schema


class BrowserSemanticOperationTool:
    name = "browser_semantic_operation"
    description = (
        "Browser semantic actuation：一次调用只表达一个已经决定的 mutation。"
        "do=navigate|click|set_text|append_text|select|scroll；对象 target 使用 exact semantic identity(kind/name，可选role)。"
        "wait 属于 browser_perceive，不在 actuation provider contract。"
        "程序仅机械编译到既有 exact grounding/version guard/single-dispatch/ActionReceipt；"
        "不 fuzzy/best-match，不 auto-target/latest/rebind/retry，不判断 task completion。"
    )
    _IDENTITY_SCHEMA = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(SEMANTIC_OBJECT_KINDS)},
            "role": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
        },
        "required": ["kind", "name"],
        "additionalProperties": False,
    }
    _OBJECT_TARGET_SCHEMA = {
        "type": "object",
        "properties": {
            "kind": {"const": "object"},
            "identity": _IDENTITY_SCHEMA,
        },
        "required": ["kind", "identity"],
        "additionalProperties": False,
    }
    _PAGE_TARGET_SCHEMA = {
        "type": "object",
        "properties": {"kind": {"const": "page"}},
        "required": ["kind"],
        "additionalProperties": False,
    }
    _CLAUSE_PARAMETERS = {
        "type": "object",
        "properties": {
            "clauses": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_CLAUSES,
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "mutate"},
                                "verb": {"const": "click"},
                                "target": _OBJECT_TARGET_SCHEMA,
                                "args": {
                                    "type": "object",
                                    "properties": {},
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["kind", "verb", "target", "args"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "mutate"},
                                "verb": {"const": "fill"},
                                "target": _OBJECT_TARGET_SCHEMA,
                                "args": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "mode": {"type": "string", "enum": ["replace", "append"]},
                                    },
                                    "required": ["text", "mode"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["kind", "verb", "target", "args"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "mutate"},
                                "verb": {"const": "select"},
                                "target": _OBJECT_TARGET_SCHEMA,
                                "args": {
                                    "type": "object",
                                    "properties": {"value": {"type": "string"}},
                                    "required": ["value"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["kind", "verb", "target", "args"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "mutate"},
                                "verb": {"const": "scroll"},
                                "target": _OBJECT_TARGET_SCHEMA,
                                "args": {
                                    "type": "object",
                                    "properties": {"delta_pages": {"type": "number"}},
                                    "required": ["delta_pages"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["kind", "verb", "target", "args"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "mutate"},
                                "verb": {"const": "navigate"},
                                "target": _PAGE_TARGET_SCHEMA,
                                "args": {
                                    "type": "object",
                                    "properties": {"url": {"type": "string", "minLength": 1}},
                                    "required": ["url"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["kind", "verb", "target", "args"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "wait"},
                                "target": _OBJECT_TARGET_SCHEMA,
                                "property": {"type": "string", "enum": ["exists", "enabled", "checked", "selected", "expanded", "focused", "editable", "name", "value_text"]},
                                "operator": {"type": "string", "enum": ["eq", "contains", "prefix", "suffix", "ge", "le"]},
                                "value": {"anyOf": [{"type": "string"}, {"type": "boolean"}, {"type": "integer"}]},
                                "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
                                "interval_ms": {"type": "integer", "minimum": 1, "maximum": 5000},
                            },
                            "required": ["kind", "target", "property", "operator", "value", "timeout_ms", "interval_ms"],
                            "additionalProperties": False,
                        },
                    ]
                },
                "description": "模型声明的有序semantic clauses；程序不新增或重排。",
            }
        },
        "required": ["clauses"],
        "additionalProperties": False,
    }

    _CLAUSE_LAZY_PARAMETERS = _build_first_call_parameters(_CLAUSE_PARAMETERS)

    # MF v0.2 model-facing wire.  This is deliberately a mechanical shorthand over
    # the already-qualified clause executor below; it does not add target selection,
    # retry, rebind, latest, or task-completion authority.
    _SHORT_TARGET_SCHEMA = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(SEMANTIC_OBJECT_KINDS)},
            "name": {"type": "string", "minLength": 1},
            "role": {"type": "string", "minLength": 1},
        },
        "required": ["kind", "name"],
        "additionalProperties": False,
    }
    _SHORT_STEP_VARIANTS = [
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["navigate"]},
                "url": {"type": "string", "minLength": 1},
            },
            "required": ["do", "url"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["click"]},
                "target": _SHORT_TARGET_SCHEMA,
            },
            "required": ["do", "target"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["set_text", "append_text"]},
                "target": _SHORT_TARGET_SCHEMA,
                "text": {"type": "string"},
            },
            "required": ["do", "target", "text"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["select"]},
                "target": _SHORT_TARGET_SCHEMA,
                "value": {"type": "string"},
            },
            "required": ["do", "target", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["scroll"]},
                "target": _SHORT_TARGET_SCHEMA,
                "delta_pages": {"type": "number"},
            },
            "required": ["do", "target", "delta_pages"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["wait"]},
                "target": _SHORT_TARGET_SCHEMA,
                "until": {"type": "string", "enum": list(_MODEL_FRIENDLY_WAIT_STATES)},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
            },
            "required": ["do", "target", "until"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "do": {"type": "string", "enum": ["wait_text"]},
                "target": _SHORT_TARGET_SCHEMA,
                "field": {"type": "string", "enum": list(_MODEL_FRIENDLY_WAIT_TEXT_FIELDS)},
                "match": {
                    "type": "string",
                    "enum": list(_MODEL_FRIENDLY_WAIT_TEXT_MATCH),
                },
                "text": {"type": "string"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
            },
            "required": ["do", "target", "field", "match", "text"],
            "additionalProperties": False,
        },
    ]
    _HISTORICAL_STEPS_PARAMETERS = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_CLAUSES,
                "items": {"oneOf": _SHORT_STEP_VARIANTS},
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    }

    # MF-5.3 provider normal form: one already-decided mutation per call.  The historical
    # steps compiler remains below as an internal/compatibility path for frozen evidence,
    # but wait and batching are no longer part of the provider-facing cognitive contract.
    _DIRECT_STEP_VARIANTS = _SHORT_STEP_VARIANTS[:5]
    parameters = {
        "type": "object",
        "properties": {
            "do": {
                "type": "string",
                "enum": ["navigate", "click", "set_text", "append_text", "select", "scroll"],
            },
            "url": {"type": "string", "minLength": 1},
            "target": _SHORT_TARGET_SCHEMA,
            "text": {"type": "string"},
            "value": {"type": "string"},
            "delta_pages": {"type": "number"},
        },
        "oneOf": _DIRECT_STEP_VARIANTS,
        "additionalProperties": False,
    }
    lazy_parameters = parameters

    def __init__(
        self,
        *,
        perception: BrowserPerceptionAdapter,
        capture_backend: BrowserCaptureBackend,
        semantic_execute: BrowserSemanticExecuteTool,
        receipt_store: BrowserSemanticOperationReceiptStore,
        session_id_getter: Callable[[], str],
    ) -> None:
        self._perception = perception
        self._capture_backend = capture_backend
        self._semantic_execute = semantic_execute
        self._receipt_store = receipt_store
        self._session_id_getter = session_id_getter
        self._wait_object = BrowserWaitObjectTool(
            adapter=perception,
            backend=capture_backend,
            session_id_getter=session_id_getter,
        )

    @staticmethod
    def _normalize_identity(target: Any) -> dict[str, str]:
        if not isinstance(target, dict) or set(target) != {"kind", "identity"}:
            raise BrowserSemanticOperationContractError("object_target_fields_mismatch")
        if target.get("kind") != "object" or not isinstance(target.get("identity"), dict):
            raise BrowserSemanticOperationContractError("object_target_contract_mismatch")
        identity = dict(target["identity"])
        if not {"kind", "name"}.issubset(identity) or not set(identity).issubset(_IDENTITY_KEYS):
            raise BrowserSemanticOperationContractError("identity_fields_mismatch")
        normalized: dict[str, str] = {}
        for key, value in identity.items():
            text = str(value or "").strip()
            if not text:
                raise BrowserSemanticOperationContractError(f"identity_{key}_missing")
            normalized[key] = text
        return normalized

    @staticmethod
    def _matches_identity(obj: dict[str, Any], identity: dict[str, str]) -> bool:
        raw_attrs = obj.get("attributes")
        attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
        for key, expected in identity.items():
            observed = obj.get("kind") if key == "kind" else attrs.get(key)
            if not isinstance(observed, str) or observed != expected:
                return False
        return True

    def _snapshot(self, session_id: str) -> dict[str, Any]:
        raw = self._capture_backend.capture()
        return self._perception.snapshot(session_id, raw, projection_limit=100)

    def _ground_object(
        self, session_id: str, target: Any
    ) -> tuple[str | None, int, dict[str, str], dict[str, Any]]:
        identity = self._normalize_identity(target)
        snapshot_result = self._snapshot(session_id)
        objects = [obj for obj in snapshot_result.get("objects", []) if isinstance(obj, dict)]
        matches = [obj for obj in objects if self._matches_identity(obj, identity)]
        if len(matches) != 1:
            return None, len(matches), identity, snapshot_result
        ref = str(matches[0].get("grounding_ref") or "").strip()
        if not ref:
            raise BrowserSemanticOperationContractError("exact_match_grounding_ref_missing")
        return ref, 1, identity, snapshot_result

    def _ground_page(self, session_id: str, target: Any) -> tuple[str, dict[str, Any]]:
        if target != {"kind": "page"}:
            raise BrowserSemanticOperationContractError("page_target_contract_mismatch")
        snapshot_result = self._snapshot(session_id)
        ref = str(snapshot_result.get("resource_ref") or "").strip()
        if not ref:
            raise BrowserSemanticOperationContractError("page_resource_ref_missing")
        return ref, snapshot_result

    @staticmethod
    def _base_receipt() -> dict[str, Any]:
        return {
            "schema": "smc.bounded_semantic_operation_receipt.v0.1",
            "domain": "browser",
            "execution_status": "running",
            "task_completion": "not_evaluated",
            "clauses": [],
            "halt_reason": None,
            "retry": {"attempt_count": 1, "automatic_retry_performed": False},
        }

    @staticmethod
    def _validate_clauses(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not (1 <= len(raw) <= _MAX_CLAUSES):
            raise BrowserSemanticOperationContractError("clauses_count_out_of_bounds")
        if not all(isinstance(item, dict) for item in raw):
            raise BrowserSemanticOperationContractError("clause_must_be_object")
        return [dict(item) for item in raw]

    @classmethod
    def _short_target_to_clause_target(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise BrowserSemanticOperationContractError("short_target_must_be_object")
        if not {"kind", "name"}.issubset(raw) or not set(raw).issubset(_IDENTITY_KEYS):
            raise BrowserSemanticOperationContractError("short_target_fields_mismatch")
        identity: dict[str, str] = {}
        for key in ("kind", "name", "role"):
            if key not in raw:
                continue
            value = str(raw.get(key) or "").strip()
            if not value:
                raise BrowserSemanticOperationContractError(f"short_target_{key}_missing")
            identity[key] = value
        return {"kind": "object", "identity": identity}

    @classmethod
    def _compile_short_steps(cls, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not (1 <= len(raw) <= _MAX_CLAUSES):
            raise BrowserSemanticOperationContractError("steps_count_out_of_bounds")
        clauses: list[dict[str, Any]] = []
        for step in raw:
            if not isinstance(step, dict):
                raise BrowserSemanticOperationContractError("step_must_be_object")
            if "do" in step:
                verb = str(step.get("do") or "").strip()
                if verb == "navigate":
                    if set(step) != {"do", "url"}:
                        raise BrowserSemanticOperationContractError("navigate_step_fields_mismatch")
                    url = str(step.get("url") or "").strip()
                    if not url:
                        raise BrowserSemanticOperationContractError("navigate_url_missing")
                    clauses.append({
                        "kind": "mutate",
                        "verb": "navigate",
                        "target": {"kind": "page"},
                        "args": {"url": url},
                    })
                    continue
                if verb == "click":
                    if set(step) != {"do", "target"}:
                        raise BrowserSemanticOperationContractError("click_step_fields_mismatch")
                    clauses.append({
                        "kind": "mutate",
                        "verb": "click",
                        "target": cls._short_target_to_clause_target(step.get("target")),
                        "args": {},
                    })
                    continue
                if verb in {"set_text", "append_text"}:
                    if set(step) != {"do", "target", "text"}:
                        raise BrowserSemanticOperationContractError("text_step_fields_mismatch")
                    clauses.append({
                        "kind": "mutate",
                        "verb": "fill",
                        "target": cls._short_target_to_clause_target(step.get("target")),
                        "args": {
                            "text": str(step.get("text") or ""),
                            "mode": "replace" if verb == "set_text" else "append",
                        },
                    })
                    continue
                if verb == "select":
                    if set(step) != {"do", "target", "value"}:
                        raise BrowserSemanticOperationContractError("select_step_fields_mismatch")
                    clauses.append({
                        "kind": "mutate",
                        "verb": "select",
                        "target": cls._short_target_to_clause_target(step.get("target")),
                        "args": {"value": str(step.get("value") or "")},
                    })
                    continue
                if verb == "scroll":
                    if set(step) != {"do", "target", "delta_pages"}:
                        raise BrowserSemanticOperationContractError("scroll_step_fields_mismatch")
                    delta = step.get("delta_pages")
                    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                        raise BrowserSemanticOperationContractError("scroll_delta_pages_invalid")
                    clauses.append({
                        "kind": "mutate",
                        "verb": "scroll",
                        "target": cls._short_target_to_clause_target(step.get("target")),
                        "args": {"delta_pages": delta},
                    })
                    continue
                if verb == "wait_text":
                    required = {"do", "target", "field", "match", "text"}
                    if not required.issubset(step) or not set(step).issubset(
                        required | {"within_ms"}
                    ):
                        raise BrowserSemanticOperationContractError("wait_text_step_fields_mismatch")
                    field = str(step.get("field") or "").strip()
                    if field not in _MODEL_FRIENDLY_WAIT_TEXT_FIELDS:
                        raise BrowserSemanticOperationContractError("wait_text_field_not_supported")
                    match = str(step.get("match") or "").strip()
                    operator = _MODEL_FRIENDLY_WAIT_TEXT_MATCH.get(match)
                    if operator is None:
                        raise BrowserSemanticOperationContractError("wait_text_match_not_supported")
                    timeout = step.get("within_ms", _MODEL_FRIENDLY_DEFAULT_WAIT_MS)
                    if (
                        isinstance(timeout, bool)
                        or not isinstance(timeout, int)
                        or not (1 <= timeout <= 60_000)
                    ):
                        raise BrowserSemanticOperationContractError("wait_timeout_invalid")
                    clauses.append({
                        "kind": "wait",
                        "target": cls._short_target_to_clause_target(step.get("target")),
                        "property": field,
                        "operator": operator,
                        "value": str(step.get("text") or ""),
                        "timeout_ms": timeout,
                        "interval_ms": min(_MODEL_FRIENDLY_WAIT_INTERVAL_MS, timeout),
                    })
                    continue
                if verb == "wait":
                    # Canonical model-facing path: ordinary state condition.  This is a
                    # closed deterministic alias into the already-qualified Predicate
                    # primitive, not natural-language interpretation or target inference.
                    if "until" in step:
                        required = {"do", "target", "until"}
                        if not required.issubset(step) or not set(step).issubset(
                            required | {"within_ms"}
                        ):
                            raise BrowserSemanticOperationContractError("wait_step_fields_mismatch")
                        prop = str(step.get("until") or "").strip()
                        if prop not in _MODEL_FRIENDLY_WAIT_STATES:
                            raise BrowserSemanticOperationContractError("wait_until_not_supported")
                        timeout = step.get("within_ms", _MODEL_FRIENDLY_DEFAULT_WAIT_MS)
                        if (
                            isinstance(timeout, bool)
                            or not isinstance(timeout, int)
                            or not (1 <= timeout <= 60_000)
                        ):
                            raise BrowserSemanticOperationContractError("wait_timeout_invalid")
                        clauses.append({
                            "kind": "wait",
                            "target": cls._short_target_to_clause_target(step.get("target")),
                            "property": prop,
                            "operator": "eq",
                            "value": True,
                            "timeout_ms": timeout,
                            "interval_ms": min(_MODEL_FRIENDLY_WAIT_INTERVAL_MS, timeout),
                        })
                        continue

                    # Compatibility-only path for MF-5.1 / historical deterministic
                    # callers.  It is intentionally not provider-visible.
                    required = {"do", "target", "property", "value", "within_ms"}
                    if not required.issubset(step) or not set(step).issubset(required | {"operator"}):
                        raise BrowserSemanticOperationContractError("wait_step_fields_mismatch")
                    prop = str(step.get("property") or "").strip()
                    operator = str(step.get("operator") or "eq").strip()
                    if prop not in {
                        "exists", "enabled", "checked", "selected", "expanded",
                        "focused", "editable", "name", "value_text",
                    }:
                        raise BrowserSemanticOperationContractError("wait_property_not_supported")
                    if operator not in {"eq", "contains", "prefix", "suffix", "ge", "le"}:
                        raise BrowserSemanticOperationContractError("wait_operator_not_supported")
                    timeout = step.get("within_ms")
                    if isinstance(timeout, bool) or not isinstance(timeout, int) or not (1 <= timeout <= 60000):
                        raise BrowserSemanticOperationContractError("wait_timeout_invalid")
                    clauses.append({
                        "kind": "wait",
                        "target": cls._short_target_to_clause_target(step.get("target")),
                        "property": prop,
                        "operator": operator,
                        "value": step.get("value"),
                        "timeout_ms": timeout,
                        "interval_ms": min(_MODEL_FRIENDLY_WAIT_INTERVAL_MS, timeout),
                    })
                    continue
                raise BrowserSemanticOperationContractError("short_operation_not_supported")

            if "wait" in step:
                if set(step) != {"wait", "within_ms"}:
                    raise BrowserSemanticOperationContractError("wait_step_fields_mismatch")
                wait = step.get("wait")
                if not isinstance(wait, dict) or "target" not in wait:
                    raise BrowserSemanticOperationContractError("wait_contract_mismatch")
                allowed_properties = {
                    "exists", "enabled", "checked", "selected", "expanded",
                    "focused", "editable", "name", "value_text"
                }
                allowed_operators = {"eq", "contains", "prefix", "suffix", "ge", "le"}
                # Provider-facing MF wire is target+property+value(+operator).  Accept the
                # earlier one-property shorthand only as a deterministic local compatibility
                # path for the MF-1 RED fixture; it is not exposed in ``parameters``.
                if {"property", "value"}.issubset(wait):
                    if not set(wait).issubset({"target", "property", "value", "operator"}):
                        raise BrowserSemanticOperationContractError("wait_fields_mismatch")
                    prop = str(wait.get("property") or "").strip()
                    value = wait.get("value")
                    operator = str(wait.get("operator") or "eq").strip()
                else:
                    predicates = [key for key in wait if key != "target"]
                    if len(predicates) != 1:
                        raise BrowserSemanticOperationContractError("wait_requires_one_predicate")
                    prop = predicates[0]
                    value = wait[prop]
                    operator = "eq"
                if prop not in allowed_properties:
                    raise BrowserSemanticOperationContractError("wait_property_not_supported")
                if operator not in allowed_operators:
                    raise BrowserSemanticOperationContractError("wait_operator_not_supported")
                timeout = step.get("within_ms")
                if isinstance(timeout, bool) or not isinstance(timeout, int) or not (1 <= timeout <= 60000):
                    raise BrowserSemanticOperationContractError("wait_timeout_invalid")
                clauses.append({
                    "kind": "wait",
                    "target": cls._short_target_to_clause_target(wait.get("target")),
                    "property": prop,
                    "operator": operator,
                    "value": value,
                    "timeout_ms": timeout,
                    "interval_ms": min(250, timeout),
                })
                continue
            raise BrowserSemanticOperationContractError("step_discriminator_missing")
        return clauses

    def _compact_projection(
        self, session_id: str, full_receipt: dict[str, Any], receipt_ref: str
    ) -> dict[str, Any]:
        execution_status = str(full_receipt.get("execution_status") or "halted")
        clauses = [x for x in list(full_receipt.get("clauses") or []) if isinstance(x, dict)]
        status = "completed" if execution_status == "clauses_exhausted" else "halted"
        compact: dict[str, Any] = {
            "schema": "smc.browser_semantic_operation_compact_receipt.v0.1",
            "status": status,
            "steps_executed": len(clauses),
            "task_completion": "not_evaluated",
            "receipt_ref": receipt_ref,
            "automatic_retry": False,
        }
        halt_reason = full_receipt.get("halt_reason")
        if status == "halted":
            reason = str(halt_reason or "halted")
            if reason == "exact_identity_match_count:0":
                reason = "target_not_found"
            elif reason.startswith("exact_identity_match_count:"):
                reason = "ambiguous_target"
            compact["halt_reason"] = reason
        last = clauses[-1] if clauses else {}
        if "exact_match_count" in last:
            compact["match_count"] = last.get("exact_match_count")
        action_receipt = last.get("action_receipt")
        if isinstance(action_receipt, dict):
            after_version = action_receipt.get("after_version")
            if after_version:
                compact["world_version"] = after_version
            observed = action_receipt.get("observed_effects")
            if isinstance(observed, dict) and observed.get("diff_ref"):
                diff_ref = str(observed["diff_ref"])
                compact["diff_ref"] = diff_ref
                hydrated = self._perception.hydrate(session_id, diff_ref)
                availability = str(hydrated.get("availability") or "unavailable")
                content = hydrated.get("content")
                if availability == "available" and isinstance(content, dict) and content.get(
                    "schema"
                ) == "smc.semantic_diff.v0.1":
                    completeness = content.get("completeness")
                    completeness = completeness if isinstance(completeness, dict) else {}

                    def count_or_none(value: Any) -> int | None:
                        return len(value) if isinstance(value, list) else None

                    compact["delta"] = {
                        "ref": diff_ref,
                        "comparable": bool(content.get("comparable")),
                        "scope_relation": str(content.get("scope_relation") or "unknown"),
                        "complete": bool(completeness.get("complete")),
                        "reasons": [
                            str(reason)
                            for reason in list(completeness.get("reasons") or [])[:8]
                        ],
                        "counts": {
                            "created": count_or_none(content.get("created")),
                            "removed": count_or_none(content.get("removed")),
                            "changed": count_or_none(content.get("changed")),
                        },
                    }
                else:
                    reason = str(hydrated.get("reason") or "projection_mismatch")
                    compact["delta"] = {
                        "ref": diff_ref,
                        "comparable": None,
                        "scope_relation": "unknown",
                        "complete": False,
                        "reasons": [f"diff_{availability}:{reason}"],
                        "counts": {"created": None, "removed": None, "changed": None},
                    }
            boundary_events = action_receipt.get("boundary_events")
            if isinstance(boundary_events, list) and boundary_events:
                compact["boundary_events"] = boundary_events
        return compact

    def execute_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise BrowserSemanticOperationContractError("session_id_missing")
        direct_verbs = {"navigate", "click", "set_text", "append_text", "select", "scroll"}
        direct_model_friendly = isinstance(request.get("do"), str) and "steps" not in request
        historical_steps = set(request) == {"steps"}
        model_friendly = direct_model_friendly or historical_steps
        if direct_model_friendly:
            verb = str(request.get("do") or "").strip()
            if verb not in direct_verbs:
                raise BrowserSemanticOperationContractError("direct_operation_not_supported")
            clauses = self._validate_clauses(self._compile_short_steps([request]))
        elif historical_steps:
            # Historical MF-5.x compatibility path.  It is deliberately absent from the
            # provider schema so old evidence remains mechanically replayable without
            # teaching batching/wait syntax to the model.
            clauses = self._validate_clauses(self._compile_short_steps(request["steps"]))
        elif set(request) == {"clauses"}:
            # Legacy/internal primitive retained for deterministic historical qualification
            # and backend reuse.  It is no longer the provider-facing MF schema.
            clauses = self._validate_clauses(request["clauses"])
        else:
            raise BrowserSemanticOperationContractError("operation_fields_mismatch")
        receipt = self._base_receipt()

        def finalize() -> dict[str, Any]:
            if not model_friendly:
                return receipt
            receipt_ref = self._receipt_store.persist(session_id, receipt)
            return self._compact_projection(session_id, receipt, receipt_ref)

        for index, clause in enumerate(clauses, start=1):
            kind = str(clause.get("kind") or "")
            if kind == "mutate":
                if set(clause) != {"kind", "verb", "target", "args"}:
                    raise BrowserSemanticOperationContractError("mutate_clause_fields_mismatch")
                verb = str(clause.get("verb") or "")
                if verb not in _MUTATION_VERBS:
                    raise BrowserSemanticOperationContractError("mutation_verb_not_supported")
                args = clause.get("args")
                if not isinstance(args, dict):
                    raise BrowserSemanticOperationContractError("mutation_args_must_be_object")
                if verb == "navigate":
                    target_ref, _ = self._ground_page(session_id, clause.get("target"))
                    exact_count = 1
                    identity: dict[str, str] | None = None
                else:
                    target_ref, exact_count, identity, _ = self._ground_object(
                        session_id, clause.get("target")
                    )
                    if exact_count != 1 or target_ref is None:
                        receipt["clauses"].append(
                            {
                                "index": index,
                                "kind": kind,
                                "verb": verb,
                                "identity": identity,
                                "exact_match_count": exact_count,
                                "status": "blocked",
                            }
                        )
                        receipt["execution_status"] = "halted"
                        receipt["halt_reason"] = f"exact_identity_match_count:{exact_count}"
                        return finalize()
                action_receipt = self._semantic_execute.execute_request(
                    session_id,
                    {"verb": verb, "target_ref": target_ref, "args": dict(args)},
                )
                clause_receipt = {
                    "index": index,
                    "kind": kind,
                    "verb": verb,
                    "identity": identity,
                    "exact_match_count": exact_count,
                    "status": "dispatched" if action_receipt.get("status") == "ok" else "blocked",
                    "action_receipt": action_receipt,
                }
                receipt["clauses"].append(clause_receipt)
                if action_receipt.get("status") != "ok":
                    receipt["execution_status"] = "halted"
                    receipt["halt_reason"] = f"action_receipt_status:{action_receipt.get('status')}"
                    return finalize()
                boundary_events = action_receipt.get("boundary_events")
                # The actuator has already mechanically classified these as Browser
                # boundary events.  A model-declared navigate is an explicit structural
                # transition and may continue with fresh grounding.  Any boundary caused
                # by another mutation is undeclared world-structure change: stop before
                # interpreting or executing a later semantic step.
                if verb != "navigate" and isinstance(boundary_events, list) and boundary_events:
                    receipt["execution_status"] = "halted"
                    receipt["halt_reason"] = "undeclared_structural_transition"
                    return finalize()
                continue

            if kind == "wait":
                required = {
                    "kind",
                    "target",
                    "property",
                    "operator",
                    "value",
                    "timeout_ms",
                    "interval_ms",
                }
                if set(clause) != required:
                    raise BrowserSemanticOperationContractError("wait_clause_fields_mismatch")
                target_ref, exact_count, identity, _ = self._ground_object(
                    session_id, clause.get("target")
                )
                if exact_count != 1 or target_ref is None:
                    receipt["clauses"].append(
                        {
                            "index": index,
                            "kind": kind,
                            "identity": identity,
                            "exact_match_count": exact_count,
                            "status": "blocked",
                        }
                    )
                    receipt["execution_status"] = "halted"
                    receipt["halt_reason"] = f"exact_identity_match_count:{exact_count}"
                    return finalize()
                wait_result = self._wait_object.execute_request(
                    session_id,
                    {
                        "object_ref": target_ref,
                        "property": clause["property"],
                        "operator": clause["operator"],
                        "value": clause["value"],
                        "timeout_ms": clause["timeout_ms"],
                        "interval_ms": clause["interval_ms"],
                    },
                )
                if wait_result.status != ToolResultStatus.SUCCESS:
                    receipt["clauses"].append(
                        {
                            "index": index,
                            "kind": kind,
                            "identity": identity,
                            "exact_match_count": 1,
                            "status": "blocked",
                            "wait_status": wait_result.status.value,
                            "wait_error": wait_result.error_detail,
                        }
                    )
                    receipt["execution_status"] = "halted"
                    receipt["halt_reason"] = "typed_wait_failed"
                    return finalize()
                wait_doc = json.loads(wait_result.content)
                predicate_result = dict(wait_doc.get("predicate_result") or {})
                observed = str(predicate_result.get("result") or "indeterminate")
                receipt["clauses"].append(
                    {
                        "index": index,
                        "kind": kind,
                        "identity": identity,
                        "exact_match_count": 1,
                        "status": "satisfied" if observed == "satisfied" else "blocked",
                        "predicate": wait_doc.get("predicate"),
                        "predicate_result": predicate_result,
                        "observation": wait_doc.get("observation"),
                    }
                )
                if observed != "satisfied":
                    receipt["execution_status"] = "halted"
                    receipt["halt_reason"] = f"predicate_result:{observed}"
                    return finalize()
                continue

            raise BrowserSemanticOperationContractError("clause_kind_not_supported")

        receipt["execution_status"] = "clauses_exhausted"
        return finalize()

    def execute(self, **kwargs: Any) -> ToolResult:
        session_id = str(self._session_id_getter() or "").strip()
        try:
            receipt = self.execute_request(session_id, dict(kwargs))
        except BrowserSemanticOperationContractError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[browser_semantic_operation] contract rejected; "
                    f"reason={exc}; no automatic retry/rebind/target substitution."
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - implementation/backend faults are explicit tool errors.
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    "[browser_semantic_operation] operation error; no automatic replay. "
                    f"error_type={type(exc).__name__}; error={exc}"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=1),
            tool_call_id="",
            tool_name=self.name,
        )
