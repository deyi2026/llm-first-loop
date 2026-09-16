"""Model-facing read-only Browser SMC perception tool.

The tool observes only a page already bound by the host backend and hydrates exact
GroundingRefs. It performs no navigation or mutation. Provider-facing wait is a flat,
root-discriminated read-only branch that compiles mechanically to internal typed waits;
poll cadence stays runtime-owned. Host/runtime activation is a separate integration decision.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from llm_loop.browser.method_card import SEMANTIC_OPERATION_METHOD_REF
from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.builtin.browser_wait import (
    BrowserWaitObjectStateTool,
    BrowserWaitObjectTextTool,
    BrowserWaitScopeReadyTool,
    BrowserWaitScopeUrlTool,
)


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


class BrowserPerceiveTool:
    name = "browser_perceive"
    description = (
        "Browser 只读感知：snapshot 读取 host 已绑定当前页面，hydrate 精确水合既有 ref，"
        "diff 比较两张 exact snapshot，wait 只读等待页面 ready/URL 或已观察对象 state/text。"
        "页面 wait 机械绑定当前 host-bound page；对象 wait 必须使用 exact grounding_ref。"
        "运行时拥有轮询节奏和默认超时；不导航、不 mutation、不 fuzzy/latest/rebind/retry，"
        "不判断 task completion，也不暴露 selector/坐标/CDP node id/AX index。"
        f"method_ref={SEMANTIC_OPERATION_METHOD_REF}。"
    )
    _PROVIDER_BRANCHES = [
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["snapshot"]},
                "projection_limit": {"type": "integer", "minimum": 1, "maximum": 500},
                "projection_kinds": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "projection_cursor": {"type": "integer", "minimum": 0},
                "vision": {"type": "string", "enum": ["evidence"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["hydrate"]},
                "grounding_ref": {"type": "string", "minLength": 1},
            },
            "required": ["action", "grounding_ref"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["diff"]},
                "from_version": {"type": "string", "minLength": 1},
                "to_version": {"type": "string", "minLength": 1},
            },
            "required": ["action", "from_version", "to_version"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "kind": {"type": "string", "enum": ["page_ready"]},
                "state": {"type": "string", "enum": ["loading", "interactive", "complete"]},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "state"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "kind": {"type": "string", "enum": ["page_url"]},
                "match": {
                    "type": "string",
                    "enum": ["equals", "contains", "starts_with", "ends_with"],
                },
                "expected_url": {"type": "string"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "match", "expected_url"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "kind": {"type": "string", "enum": ["object_state"]},
                "grounding_ref": {"type": "string", "minLength": 1},
                "state": {
                    "type": "string",
                    "enum": [
                        "exists",
                        "enabled",
                        "checked",
                        "selected",
                        "expanded",
                        "focused",
                        "editable",
                    ],
                },
                "value": {"type": "boolean"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "grounding_ref", "state", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "kind": {"type": "string", "enum": ["object_text"]},
                "grounding_ref": {"type": "string", "minLength": 1},
                "field": {"type": "string", "enum": ["name", "value_text"]},
                "match": {
                    "type": "string",
                    "enum": ["equals", "contains", "starts_with", "ends_with"],
                },
                "text": {"type": "string"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "grounding_ref", "field", "match", "text"],
            "additionalProperties": False,
        },
    ]
    parameters = {
        "type": "object",
        # Keep the shallow union for provider compatibility, while oneOf branches below
        # are the authority for action-specific closed fields.
        "properties": {
            "action": {"type": "string", "enum": ["snapshot", "hydrate", "diff", "wait"]},
            "projection_kinds": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "仅 snapshot（EVO-20260918-c69527a1）：按 SemanticObject.kind 过滤投影"
                    "（如 button/input/select/link）；matched_total/next_cursor 支持模型驱动分页；"
                    "零程序策略，服务端只机械限幅并如实回执"
                ),
            },
            "projection_cursor": {
                "type": "integer",
                "minimum": 0,
                "description": "仅 snapshot：配合 projection_kinds/limit 的投影窗口起点（0-based）",
            },
            "vision": {
                "type": "string",
                "enum": ["evidence"],
                "description": (
                    "仅 snapshot（EVO-20260918-f2310800）：请求视觉证据。固定参数截图（PNG）落盘并"
                    "在回执 vision 块返回 ref+path+sha256；视觉输出永远停在证据层，不进 objects/"
                    "grounding/version；模型用 read_image 消费并自行裁决"
                ),
            },
            "projection_limit": {"type": "integer", "minimum": 1, "maximum": 500},
            "grounding_ref": {"type": "string", "minLength": 1},
            "from_version": {"type": "string", "minLength": 1},
            "to_version": {"type": "string", "minLength": 1},
            "kind": {
                "type": "string",
                "enum": ["page_ready", "page_url", "object_state", "object_text"],
            },
            "state": {"type": "string"},
            "match": {
                "type": "string",
                "enum": ["equals", "contains", "starts_with", "ends_with"],
            },
            "expected_url": {"type": "string"},
            "value": {"type": "boolean"},
            "field": {"type": "string", "enum": ["name", "value_text"]},
            "text": {"type": "string"},
            "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
        },
        "required": ["action"],
        "oneOf": _PROVIDER_BRANCHES,
        "additionalProperties": False,
    }

    # Generic lazy projection drops oneOf. This explicit provider schema preserves the
    # exact same root-direct branch structure on the stable prefix.
    lazy_parameters = parameters

    _FLAT_WAIT_FIELDS = {
        "page_ready": {"action", "kind", "state", "within_ms"},
        "page_url": {"action", "kind", "match", "expected_url", "within_ms"},
        "object_state": {"action", "kind", "grounding_ref", "state", "value", "within_ms"},
        "object_text": {
            "action",
            "kind",
            "grounding_ref",
            "field",
            "match",
            "text",
            "within_ms",
        },
    }

    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: BrowserCaptureBackend | None,
        session_id_getter: Callable[[], str],
        exact_ref_hydrator: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._backend = backend
        self._session_id_getter = session_id_getter
        self._exact_ref_hydrator = exact_ref_hydrator
        common_wait = {
            "adapter": adapter,
            "backend": backend,
            "session_id_getter": session_id_getter,
        }
        self._wait_scope_ready = BrowserWaitScopeReadyTool(**common_wait)
        self._wait_scope_url = BrowserWaitScopeUrlTool(**common_wait)
        self._wait_object_state = BrowserWaitObjectStateTool(**common_wait)
        self._wait_object_text = BrowserWaitObjectTextTool(**common_wait)

    def _json_result(self, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
            tool_call_id="",
            tool_name=self.name,
        )

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )


    def _field_mismatch(self, action: str, kwargs: dict[str, Any]) -> ToolResult | None:
        allowed_by_action = {
            "snapshot": {
                "action",
                "projection_limit",
                "projection_kinds",
                "projection_cursor",
                "vision",
            },
            "hydrate": {"action", "grounding_ref"},
            "diff": {"action", "from_version", "to_version"},
        }
        if action == "wait":
            # Historical nested condition remains executable for frozen evidence and
            # deterministic compatibility, but it is absent from the provider schema.
            if "condition" in kwargs:
                allowed = {"action", "condition", "within_ms"}
            else:
                kind = str(kwargs.get("kind") or "").strip()
                allowed = self._FLAT_WAIT_FIELDS.get(kind)
                if allowed is None:
                    return self._fail(f"[browser_perceive:wait] kind 不受支持: {kind or '<missing>'}。")
        else:
            allowed = allowed_by_action.get(action)
        if allowed is None:
            return None
        extras = sorted(set(kwargs) - allowed)
        if extras:
            return self._fail(
                f"[browser_perceive:{action}] fields_mismatch: action 不接受字段 {extras}。"
            )
        return None

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        if (
            action == "wait"
            and "condition" not in kwargs
            and str(kwargs.get("kind") or "").strip() == "page_url"
            and "expected_url" not in kwargs
            and "url" in kwargs
        ):
            # Hidden compatibility for historical/internal direct callers.  The
            # provider contract exposes only expected_url so destination navigation
            # and observed-URL waiting no longer share the same argument role.
            kwargs = dict(kwargs)
            kwargs["expected_url"] = kwargs.pop("url")
        if (
            action == "wait"
            and "condition" not in kwargs
            and str(kwargs.get("kind") or "").strip() in {"object_state", "object_text"}
            and "grounding_ref" not in kwargs
            and "object_ref" in kwargs
        ):
            # Hidden compatibility for historical/internal direct callers.  The
            # provider contract exposes only grounding_ref so the model sees the
            # same exact-ref name on snapshot objects, hydrate, and object waits.
            kwargs = dict(kwargs)
            kwargs["grounding_ref"] = kwargs.pop("object_ref")
        session_id = str(self._session_id_getter() or "").strip()
        if not session_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[browser_perceive] 当前 session identity 不可用；未执行 Browser observation。",
                tool_call_id="",
                tool_name=self.name,
            )
        mismatch = self._field_mismatch(action, dict(kwargs))
        if mismatch is not None:
            return mismatch
        if action == "wait":
            condition = kwargs.get("condition")
            if condition is None:
                condition = {
                    key: value
                    for key, value in kwargs.items()
                    if key not in {"action", "within_ms"}
                }
            elif not isinstance(condition, dict):
                return self._fail("[browser_perceive:wait] condition 必须是闭合 object。")
            else:
                condition = dict(condition)
                if (
                    str(condition.get("kind") or "").strip() == "page_url"
                    and "expected_url" not in condition
                    and "url" in condition
                ):
                    # Historical nested-condition compatibility is execution-only; it
                    # is absent from both lazy and full provider schemas.
                    condition["expected_url"] = condition.pop("url")
                if (
                    str(condition.get("kind") or "").strip() in {"object_state", "object_text"}
                    and "grounding_ref" not in condition
                    and "object_ref" in condition
                ):
                    # Historical nested object_ref remains execution-only.  It is
                    # normalized mechanically to the exact GroundingRef field.
                    condition["grounding_ref"] = condition.pop("object_ref")
            try:
                timeout_ms = int(kwargs.get("within_ms", 60_000) or 60_000)
            except (TypeError, ValueError):
                return self._fail("[browser_perceive:wait] within_ms 必须是整数 1..60000。")
            if not 1 <= timeout_ms <= 60_000:
                return self._fail("[browser_perceive:wait] within_ms 必须在 1..60000。")
            interval_ms = min(250, timeout_ms)
            kind = str(condition.get("kind") or "").strip()
            if kind in {"page_ready", "page_url"}:
                if self._backend is None:
                    return self._fail(
                        "[browser_perceive:wait] read-only Browser backend unavailable; no polling started."
                    )
                try:
                    seed = self._adapter.snapshot(
                        session_id, self._backend.capture(), projection_limit=1
                    )
                    page_scope = next(
                        item
                        for item in list(seed.get("scope_facts") or [])
                        if isinstance(item, dict) and item.get("kind") == "page"
                    )
                    scope_ref = str(page_scope.get("scope_ref") or "").strip()
                except Exception as exc:  # noqa: BLE001 - observation failure must stay explicit.
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=(
                            "[browser_perceive:wait] page binding observation failed; "
                            f"error_type={type(exc).__name__}; error={exc}"
                        ),
                        tool_call_id="",
                        tool_name=self.name,
                        error_type=type(exc).__name__,
                        error_detail=str(exc),
                    )
                if not scope_ref:
                    return self._fail("[browser_perceive:wait] host-bound page scope unavailable.")
                if kind == "page_ready":
                    request = {
                        "scope_ref": scope_ref,
                        "state": condition.get("state"),
                        "timeout_ms": timeout_ms,
                        "interval_ms": interval_ms,
                    }
                    result = self._wait_scope_ready.execute_request(session_id, request)
                else:
                    match_to_operator = {
                        "equals": "eq",
                        "contains": "contains",
                        "starts_with": "prefix",
                        "ends_with": "suffix",
                    }
                    match = str(condition.get("match") or "").strip()
                    operator = match_to_operator.get(match)
                    if operator is None:
                        return self._fail("[browser_perceive:wait] page_url match 不受支持。")
                    request = {
                        "scope_ref": scope_ref,
                        "operator": operator,
                        "value": condition.get("expected_url"),
                        "timeout_ms": timeout_ms,
                        "interval_ms": interval_ms,
                    }
                    result = self._wait_scope_url.execute_request(session_id, request)
            elif kind == "object_state":
                request = {
                    "object_ref": condition.get("grounding_ref"),
                    "property": condition.get("state"),
                    "value": condition.get("value"),
                    "timeout_ms": timeout_ms,
                    "interval_ms": interval_ms,
                }
                result = self._wait_object_state.execute_request(session_id, request)
            elif kind == "object_text":
                match_to_operator = {
                    "equals": "eq",
                    "contains": "contains",
                    "starts_with": "prefix",
                    "ends_with": "suffix",
                }
                match = str(condition.get("match") or "").strip()
                operator = match_to_operator.get(match)
                if operator is None:
                    return self._fail("[browser_perceive:wait] object_text match 不受支持。")
                request = {
                    "object_ref": condition.get("grounding_ref"),
                    "property": condition.get("field"),
                    "operator": operator,
                    "value": condition.get("text"),
                    "timeout_ms": timeout_ms,
                    "interval_ms": interval_ms,
                }
                result = self._wait_object_text.execute_request(session_id, request)
            else:
                return self._fail(
                    "[browser_perceive:wait] condition.kind 必须是 "
                    "page_ready/page_url/object_state/object_text。"
                )
            return ToolResult(
                status=result.status,
                content=result.content,
                tool_call_id="",
                tool_name=self.name,
                error_type=result.error_type,
                error_detail=result.error_detail,
                partial_output=result.partial_output,
            )
        if action == "hydrate":
            ref = str(kwargs.get("grounding_ref") or "").strip()
            if not ref:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:hydrate] grounding_ref 为空；必须给精确 GroundingRef。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if ref.startswith("browser-operation-receipt://") and self._exact_ref_hydrator is not None:
                hydrated = self._exact_ref_hydrator(session_id, ref)
            else:
                hydrated = self._adapter.hydrate(session_id, ref)
            return self._json_result({"action": "hydrate", **hydrated})
        if action == "diff":
            from_version = str(kwargs.get("from_version") or "").strip()
            to_version = str(kwargs.get("to_version") or "").strip()
            if not from_version or not to_version:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[browser_perceive:diff] from_version/to_version 必须都是精确 Browser snapshot_id。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            try:
                return self._json_result(
                    self._adapter.diff(session_id, from_version, to_version)
                )
            except Exception as exc:  # noqa: BLE001 - exact diff failure must remain visible.
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "[browser_perceive:diff] exact snapshot diff failed; "
                        f"error_type={type(exc).__name__}; error={exc}"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                )
        if action == "snapshot":
            if self._backend is None:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[browser_perceive:snapshot] read-only Browser backend unavailable; "
                        "未执行 navigation/legacy playwright fallback。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            try:
                projection_limit = int(kwargs.get("projection_limit", 200) or 200)
            except (TypeError, ValueError):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] projection_limit 必须是整数 1..500。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            projection_limit = max(1, min(projection_limit, 500))
            projection_kinds_raw = kwargs.get("projection_kinds")
            projection_kinds: list[str] | None = None
            if projection_kinds_raw is not None:
                if not isinstance(projection_kinds_raw, list) or not all(
                    isinstance(item, str) and item.strip() for item in projection_kinds_raw
                ):
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content="[browser_perceive:snapshot] projection_kinds 必须是非空字符串数组。",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                projection_kinds = [str(item).strip() for item in projection_kinds_raw]
            try:
                projection_cursor = int(kwargs.get("projection_cursor", 0) or 0)
            except (TypeError, ValueError):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] projection_cursor 必须是 >=0 的整数。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if projection_cursor < 0:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] projection_cursor 必须是 >=0 的整数。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            vision_request = str(kwargs.get("vision") or "").strip() or None
            if vision_request is not None and vision_request != "evidence":
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] vision 只接受 evidence。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            try:
                raw = self._backend.capture()
                result = self._adapter.snapshot(
                    session_id,
                    raw,
                    projection_limit=projection_limit,
                    projection_kinds=projection_kinds,
                    projection_cursor=projection_cursor,
                )
                if vision_request == "evidence":
                    # EVO-20260918-f2310800: evidence-layer vision only. The
                    # DOM+AX snapshot above already succeeded; vision failure is
                    # reported in the vision block and never masks the main result.
                    capture_vision = getattr(self._backend, "capture_vision_evidence", None)
                    if not callable(capture_vision):
                        result["vision"] = {"status": "unavailable"}
                    else:
                        try:
                            payload = capture_vision()
                        except Exception as vision_exc:  # noqa: BLE001 - vision failure must stay visible, non-fatal.
                            result["vision"] = {
                                "status": "failed",
                                "error_type": type(vision_exc).__name__,
                                "error": str(vision_exc),
                            }
                        else:
                            if not isinstance(payload, bytes):
                                # Mechanical payload boundary: the backend declared
                                # the capability but did not return raw bytes.
                                result["vision"] = {
                                    "status": "unavailable",
                                    "reason": "payload_not_bytes",
                                }
                            else:
                                result["vision"] = {
                                    "status": "ok",
                                    **self._adapter.store_vision_evidence(session_id, payload),
                                }
                return self._json_result(result)
            except Exception as exc:  # noqa: BLE001 - observation failure must remain explicit.
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "[browser_perceive:snapshot] observation failed; "
                        f"error_type={type(exc).__name__}; error={exc}"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                )
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[browser_perceive] action 必须是 snapshot、hydrate、diff 或 wait。",
            tool_call_id="",
            tool_name=self.name,
        )
