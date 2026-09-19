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
            content="[browser_perceive] action 必须是 snapshot、hydrate 或 diff。",
            tool_call_id="",
            tool_name=self.name,
        )
