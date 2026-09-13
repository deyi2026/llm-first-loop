"""Bounded Browser semantic-operation orchestration.

The model declares every semantic clause.  This tool only expands those clauses into
canonical observation, exact-unique grounding, typed predicate wait, and the already
qualified single-dispatch semantic executor.  It never chooses a target, fuzzily matches,
retries a mutation, substitutes an identity, or decides task completion.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from llm_loop.browser.perception import SEMANTIC_OBJECT_KINDS, BrowserPerceptionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_wait import BrowserWaitObjectTool

_MAX_CLAUSES = 8
_IDENTITY_KEYS = {"kind", "role", "name"}
_OBJECT_VERBS = {"click", "fill", "select", "scroll"}
_MUTATION_VERBS = _OBJECT_VERBS | {"navigate"}


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
        "Bounded Browser semantic operation v0.1：模型一次声明1..8个 clauses；每个对象 target "
        "只允许 exact identity(kind/role/name) 严格匹配，程序对当前 canonical SemanticObject "
        "计数，恰好1个才继续，0或>1立即停止；wait clause 使用既有 typed Predicate polling；"
        "mutate args 固定为 click={}、fill={text,mode(replace|append)}、select={value}、"
        "scroll={delta_pages}、navigate={url}；委托 browser_semantic_execute / single-dispatch / "
        "version guard / ActionReceipt。不 fuzzy/best-match，不 auto-target/latest/rebind/retry，"
        "不判断 task completion。"
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
    parameters = {
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

    lazy_parameters = _build_first_call_parameters(parameters)

    def __init__(
        self,
        *,
        perception: BrowserPerceptionAdapter,
        capture_backend: BrowserCaptureBackend,
        semantic_execute: BrowserSemanticExecuteTool,
        session_id_getter: Callable[[], str],
    ) -> None:
        self._perception = perception
        self._capture_backend = capture_backend
        self._semantic_execute = semantic_execute
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

    def execute_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise BrowserSemanticOperationContractError("session_id_missing")
        if set(request) != {"clauses"}:
            raise BrowserSemanticOperationContractError("operation_fields_mismatch")
        clauses = self._validate_clauses(request["clauses"])
        receipt = self._base_receipt()

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
                        return receipt
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
                    return receipt
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
                    return receipt
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
                    return receipt
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
                    return receipt
                continue

            raise BrowserSemanticOperationContractError("clause_kind_not_supported")

        receipt["execution_status"] = "clauses_exhausted"
        return receipt

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
