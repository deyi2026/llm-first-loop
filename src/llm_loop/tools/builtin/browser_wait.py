"""Typed model-facing Browser predicate wait tools.

The model owns the semantic condition.  These tools compile only fixed/mechanical
Predicate identity fields and delegate polling/evaluation to the already-qualified
Browser perception adapter.  They never mutate the browser, choose a target, refresh a
reference, retry an action, or decide task completion.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.browser.predicate import PREDICATE_SPECS, validate_predicate
from llm_loop.core.message import ToolResult, ToolResultStatus

_MAX_WAIT_MS = 60_000
_MAX_INTERVAL_MS = 5_000
_SCOPE_PROPERTIES = tuple(
    name for name, spec in PREDICATE_SPECS.items() if spec.get("target_kind") == "scope"
)
_OBJECT_PROPERTIES = tuple(
    name
    for name, spec in PREDICATE_SPECS.items()
    if spec.get("target_kind") == "semantic_object"
)
_OPERATORS = ("eq", "contains", "prefix", "suffix", "ge", "le")
_COMMON_REQUEST_FIELDS = {
    "property",
    "operator",
    "value",
    "timeout_ms",
    "interval_ms",
}


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _bounded_wait_int(raw: Any, *, name: str, maximum: int) -> tuple[int | None, str | None]:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None, f"{name} 必须是整数 1..{maximum}"
    if raw < 1 or raw > maximum:
        return None, f"{name} 必须在 1..{maximum}"
    return raw, None


def _wait_parameter_schema(*, ref_name: str, properties: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            ref_name: {"type": "string", "minLength": 1},
            "property": {"type": "string", "enum": list(properties)},
            "operator": {"type": "string", "enum": list(_OPERATORS)},
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "boolean"},
                    {"type": "integer"},
                ]
            },
            "timeout_ms": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_WAIT_MS,
            },
            "interval_ms": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_INTERVAL_MS,
            },
        },
        "required": [
            ref_name,
            "property",
            "operator",
            "value",
            "timeout_ms",
            "interval_ms",
        ],
        "additionalProperties": False,
    }


class BrowserPredicateWaiter:
    """Canonical read-only polling engine for an already-compiled Browser Predicate."""

    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: BrowserCaptureBackend | None,
    ) -> None:
        self._adapter = adapter
        self._backend = backend

    @staticmethod
    def _failure(*, tool_name: str, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[{tool_name}] {content}",
            tool_call_id="",
            tool_name=tool_name,
        )

    def wait(
        self,
        session_id: str,
        *,
        predicate: dict[str, Any],
        timeout_ms: Any,
        interval_ms: Any,
        tool_name: str,
    ) -> ToolResult:
        if self._backend is None:
            return self._failure(
                tool_name=tool_name,
                content="read-only Browser backend unavailable; 未执行 mutation/legacy fallback。",
            )
        validation_error = validate_predicate(predicate)
        if validation_error is not None:
            return self._failure(
                tool_name=tool_name,
                content=f"predicate contract rejected: {validation_error}",
            )

        bounded_timeout, timeout_error = _bounded_wait_int(
            timeout_ms, name="timeout_ms", maximum=_MAX_WAIT_MS
        )
        if timeout_error is not None or bounded_timeout is None:
            return self._failure(tool_name=tool_name, content=str(timeout_error))
        bounded_interval, interval_error = _bounded_wait_int(
            interval_ms, name="interval_ms", maximum=_MAX_INTERVAL_MS
        )
        if interval_error is not None or bounded_interval is None:
            return self._failure(tool_name=tool_name, content=str(interval_error))

        start_mono = time.monotonic()
        deadline_mono = start_mono + bounded_timeout / 1000.0
        deadline_epoch = time.time() + bounded_timeout / 1000.0
        deadline = _iso_utc(deadline_epoch)
        sample_count = 0
        observer_error_count = 0
        observed_at = _iso_utc(time.time())
        observation: dict[str, Any] = {
            "result": "indeterminate",
            "snapshot_id": None,
            "scope_ref": str(predicate["scope_ref"]),
            "target": str(predicate["target"]),
            "property": str(predicate["property"]),
            "observed_value": None,
            "coverage_complete": False,
            "reason": "observer_error",
            "objects_ref": "",
        }

        while True:
            if sample_count > 0 and time.monotonic() >= deadline_mono:
                break
            sample_count += 1
            try:
                raw = self._backend.capture()
                snapshot_result = self._adapter.snapshot(
                    session_id,
                    raw,
                    projection_limit=1,
                )
            except Exception as exc:  # noqa: BLE001 - observer failure is a tri-state fact.
                observer_error_count += 1
                observed_at = _iso_utc(time.time())
                observation = {
                    "result": "indeterminate",
                    "snapshot_id": None,
                    "scope_ref": str(predicate["scope_ref"]),
                    "target": str(predicate["target"]),
                    "property": str(predicate["property"]),
                    "observed_value": None,
                    "coverage_complete": False,
                    "reason": "observer_error",
                    "observer_error_type": type(exc).__name__,
                    "objects_ref": "",
                }
            else:
                snapshot = dict(snapshot_result.get("snapshot") or {})
                snapshot_id = str(snapshot.get("snapshot_id") or "")
                observed_at = str(snapshot.get("observed_at") or "") or _iso_utc(time.time())
                try:
                    observation = self._adapter.evaluate_predicate(
                        session_id,
                        snapshot_id,
                        predicate,
                    )
                except Exception as exc:  # noqa: BLE001 - evaluator faults are implementation errors.
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=(
                            f"[{tool_name}] predicate evaluation failed; "
                            f"error_type={type(exc).__name__}; error={exc}"
                        ),
                        tool_call_id="",
                        tool_name=tool_name,
                        error_type=type(exc).__name__,
                        error_detail=str(exc),
                    )
                if observation.get("result") == "satisfied":
                    break

            now = time.monotonic()
            if now >= deadline_mono:
                break
            remaining = deadline_mono - now
            time.sleep(min(bounded_interval / 1000.0, remaining))

        predicate_result = {
            "result": str(observation.get("result") or "indeterminate"),
            "evaluation_mode": "polling",
            "observed_at": observed_at,
            "deadline": deadline,
            "interval_ms": bounded_interval,
            "sample_count": sample_count,
            "observer_error_count": observer_error_count,
        }
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(
                {
                    "action": "wait",
                    "predicate": predicate,
                    "predicate_result": predicate_result,
                    "observation": observation,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=1,
            ),
            tool_call_id="",
            tool_name=tool_name,
        )


class _BrowserTypedWaitTool:
    ref_name: str
    allowed_properties: tuple[str, ...]
    name: str
    parameters: dict[str, Any]

    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: BrowserCaptureBackend | None,
        session_id_getter: Callable[[], str],
    ) -> None:
        self._adapter = adapter
        self._waiter = BrowserPredicateWaiter(adapter=adapter, backend=backend)
        self._session_id_getter = session_id_getter

    def _failure(self, reason: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[{self.name}] semantic predicate compile rejected; reason={reason}; no polling started.",
            tool_call_id="",
            tool_name=self.name,
            error_type="BrowserPredicateCompileError",
            error_detail=reason,
        )

    def _normalize_common(
        self,
        request: dict[str, Any],
        *,
        allowed_fields: set[str],
    ) -> tuple[str, str, Any, int, int]:
        if set(request) != allowed_fields:
            raise ValueError("wait_fields_mismatch")
        property_name = str(request.get("property") or "").strip()
        if property_name not in self.allowed_properties:
            raise ValueError("predicate_property_target_kind_mismatch")
        operator = str(request.get("operator") or "").strip()
        value = request.get("value")
        timeout_ms, timeout_error = _bounded_wait_int(
            request.get("timeout_ms"), name="timeout_ms", maximum=_MAX_WAIT_MS
        )
        if timeout_error is not None or timeout_ms is None:
            raise ValueError(timeout_error or "timeout_ms_invalid")
        interval_ms, interval_error = _bounded_wait_int(
            request.get("interval_ms"), name="interval_ms", maximum=_MAX_INTERVAL_MS
        )
        if interval_error is not None or interval_ms is None:
            raise ValueError(interval_error or "interval_ms_invalid")
        return property_name, operator, value, timeout_ms, interval_ms

    def _compile_predicate(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def compile_predicate(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id_missing")
        return self._compile_predicate(session_id, dict(request))

    def execute_request(self, session_id: str, request: dict[str, Any]) -> ToolResult:
        try:
            predicate = self.compile_predicate(session_id, request)
            _, _, _, timeout_ms, interval_ms = self._normalize_common(
                request,
                allowed_fields={self.ref_name, *_COMMON_REQUEST_FIELDS},
            )
        except ValueError as exc:
            return self._failure(str(exc))
        return self._waiter.wait(
            session_id,
            predicate=predicate,
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
            tool_name=self.name,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        session_id = str(self._session_id_getter() or "").strip()
        if not session_id:
            return self._failure("session_id_missing")
        return self.execute_request(session_id, dict(kwargs))


class BrowserWaitScopeTool(_BrowserTypedWaitTool):
    name = "browser_wait_scope"
    ref_name = "scope_ref"
    allowed_properties = _SCOPE_PROPERTIES
    description = (
        "Browser 只读 scope wait：模型从当前 observation 选择 exact scope_ref 和条件；"
        "property 仅限 url/document_ready_state/object_count。工具机械补 Predicate schema/domain/"
        "target=scope_ref 后轮询；timeout 是 observation，不执行 mutation/target selection/retry/latest/rebind，"
        "也不判断任务完成。"
    )
    parameters = _wait_parameter_schema(ref_name=ref_name, properties=allowed_properties)

    def _compile_predicate(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        del session_id  # Scope identity is evaluated mechanically against later observations.
        property_name, operator, value, _, _ = self._normalize_common(
            request,
            allowed_fields={self.ref_name, *_COMMON_REQUEST_FIELDS},
        )
        scope_ref = str(request.get(self.ref_name) or "").strip()
        if not scope_ref:
            raise ValueError("scope_ref_missing")
        predicate = {
            "schema": "smc.predicate.v0.1",
            "domain": "browser",
            "scope_ref": scope_ref,
            "target": scope_ref,
            "property": property_name,
            "operator": operator,
            "value": value,
        }
        validation_error = validate_predicate(predicate)
        if validation_error is not None:
            raise ValueError(validation_error)
        return predicate


class BrowserWaitObjectTool(_BrowserTypedWaitTool):
    name = "browser_wait_object"
    ref_name = "object_ref"
    allowed_properties = _OBJECT_PROPERTIES
    description = (
        "Browser 只读 object wait：模型从当前 observation 选择 exact SemanticObject GroundingRef 和条件；"
        "工具仅按该 ref 做 session-fenced exact hydrate，机械派生 Semantic ID/scope 并编译 Predicate 后轮询。"
        "不按名称找对象，不 fallback/rebind/latest，不执行 mutation/retry，也不判断任务完成。"
    )
    parameters = _wait_parameter_schema(ref_name=ref_name, properties=allowed_properties)

    def _compile_predicate(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        property_name, operator, value, _, _ = self._normalize_common(
            request,
            allowed_fields={self.ref_name, *_COMMON_REQUEST_FIELDS},
        )
        object_ref = str(request.get(self.ref_name) or "").strip()
        if not object_ref:
            raise ValueError("object_ref_missing")
        hydrated = self._adapter.hydrate(session_id, object_ref)
        availability = str(hydrated.get("availability") or "unavailable")
        if availability != "available":
            reason = str(hydrated.get("reason") or availability)
            raise ValueError(f"object_ref_{availability}:{reason}")
        content = hydrated.get("content")
        if not isinstance(content, dict):
            raise ValueError("object_ref_projection_mismatch")
        semantic_object = content.get("semantic_object")
        if not isinstance(semantic_object, dict):
            raise ValueError("object_ref_projection_mismatch")
        if str(semantic_object.get("grounding_ref") or "") != object_ref:
            raise ValueError("object_ref_identity_mismatch")
        target = str(semantic_object.get("id") or "").strip()
        scope_ref = str(semantic_object.get("scope_ref") or "").strip()
        if not target or not scope_ref:
            raise ValueError("object_ref_incomplete")
        predicate = {
            "schema": "smc.predicate.v0.1",
            "domain": "browser",
            "scope_ref": scope_ref,
            "target": target,
            "property": property_name,
            "operator": operator,
            "value": value,
        }
        validation_error = validate_predicate(predicate)
        if validation_error is not None:
            raise ValueError(validation_error)
        return predicate
