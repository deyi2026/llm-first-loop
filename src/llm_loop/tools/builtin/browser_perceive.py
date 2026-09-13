"""Model-facing read-only Browser SMC perception tool.

The tool can snapshot only a page already bound by the host backend and hydrate exact
GroundingRefs.  It intentionally has no URL/script/selector/action parameter and performs
no navigation or mutation. The action discriminator is limited to snapshot/hydrate/diff; typed wait lives in separate tools. Host/runtime activation is a separate integration decision.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from llm_loop.browser.method_card import SEMANTIC_OPERATION_METHOD_CARD
from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


class BrowserPerceiveTool:
    name = "browser_perceive"
    description = (
        SEMANTIC_OPERATION_METHOD_CARD
        + " "
        "SMC Browser Phase 1 只读感知。snapshot=读取 host 已绑定的当前页面 DOM+AX，返回"
        "WorldSnapshot + SemanticObject；hydrate=按精确 GroundingRef 水合历史 observation；"
        "diff=仅比较两张已落盘 exact snapshot。该工具不 wait、不导航、不点击/输入/滚动、"
        "不执行模型提供的脚本或自动重试；wait 使用 typed browser_wait_scope_url/"
        "scope_ready/scope_count/object_state/object_text。"
        "ref 过期/跨 session/不可用会如实返回。模型面不暴露 CSS/XPath/坐标/CDP node id/AX index。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["snapshot", "hydrate", "diff"],
                "description": (
                    "snapshot=当前已绑定页面只读 DOM+AX 感知；"
                    "hydrate=精确水合 grounding_ref；diff=比较两张 exact snapshot"
                ),
            },
            "projection_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "description": "仅 snapshot：首屏投影对象上限；不改变底层 observation completeness",
            },
            "grounding_ref": {
                "type": "string",
                "description": "仅 hydrate：精确 grounding://browser/v0.1/... 引用",
            },
            "from_version": {
                "type": "string",
                "description": "仅 diff：起点精确 Browser snapshot_id",
            },
            "to_version": {
                "type": "string",
                "description": "仅 diff：终点精确 Browser snapshot_id",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }


    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: BrowserCaptureBackend | None,
        session_id_getter: Callable[[], str],
    ) -> None:
        self._adapter = adapter
        self._backend = backend
        self._session_id_getter = session_id_getter

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
            "snapshot": {"action", "projection_limit"},
            "hydrate": {"action", "grounding_ref"},
            "diff": {"action", "from_version", "to_version"},
        }
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
        if action == "hydrate":
            ref = str(kwargs.get("grounding_ref") or "").strip()
            if not ref:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:hydrate] grounding_ref 为空；必须给精确 GroundingRef。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            return self._json_result(
                {"action": "hydrate", **self._adapter.hydrate(session_id, ref)}
            )
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
            try:
                raw = self._backend.capture()
                return self._json_result(
                    self._adapter.snapshot(
                        session_id,
                        raw,
                        projection_limit=projection_limit,
                    )
                )
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
            content="[browser_perceive] action 必须是 snapshot、hydrate 或 diff。",
            tool_call_id="",
            tool_name=self.name,
        )
