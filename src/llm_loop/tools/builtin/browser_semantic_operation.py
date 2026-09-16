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
        "Model-friendly bounded Browser semantic operation：模型一次声明1..8个 ordered steps；"
        "do=navigate|click|set_text|append_text|select|scroll，target 只写 exact semantic "
        "identity(kind/name，可选role)；wait 直接声明 target + 一个 typed property/value + within_ms。"
        "程序仅机械编译到既有 exact grounding/version guard/typed Predicate/single-dispatch/ActionReceipt；"
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
                "wait": {
                    "type": "object",
                    "properties": {
                        "target": _SHORT_TARGET_SCHEMA,
                        "property": {
                            "type": "string",
                            "enum": [
                                "exists", "enabled", "checked", "selected", "expanded",
                                "focused", "editable", "name", "value_text",
                            ],
                        },
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "contains", "prefix", "suffix", "ge", "le"],
                        },
                        "value": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "boolean"},
                                {"type": "integer"},
                            ]
                        },
                    },
                    "required": ["target", "property", "value"],
                    "additionalProperties": False,
                },
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
            },
            "required": ["wait", "within_ms"],
            "additionalProperties": False,
        },
    ]
    parameters = {
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
    # Keep the short contract intact on the lazy/provider path rather than stripping
    # discriminated oneOf branches and forcing a schema-repair round trip.
    lazy_parameters = parameters

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

    def execute_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise BrowserSemanticOperationContractError("session_id_missing")
        if set(request) == {"steps"}:
            clauses = self._validate_clauses(self._compile_short_steps(request["steps"]))
        elif set(request) == {"clauses"}:
            # Legacy/internal primitive retained for deterministic historical qualification
            # and backend reuse.  It is no longer the provider-facing MF schema.
            clauses = self._validate_clauses(request["clauses"])
        else:
            raise BrowserSemanticOperationContractError("operation_fields_mismatch")
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
