"""Model-facing SMC Browser mutation tool.

The tool accepts only the frozen SemanticAction v0.1 fields.  Backend selectors,
coordinates, scripts, CDP methods, and physical node identifiers are never model inputs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from llm_loop.browser.action import BrowserActionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus


class BrowserActionTool:
    name = "browser_action"
    description = (
        "SMC Browser Phase 1 写操作（显式 opt-in）。仅支持 click/fill/select/navigate/scroll。"
        "必须提交完整 SemanticAction v0.1 与 expected_version/version_scope；runtime 会在 dispatch 前"
        "重新只读观察、核对 exact Semantic ID/version，只在机械 match 时单次 dispatch。"
        "stale/indeterminate/identity ambiguity 会 rejected；同一 action_id 不会再次执行。"
        "所有 mutation idempotency=unknown、atomicity=single_dispatch，绝不自动 retry/replay/rebind。"
        "ActionReceipt 只表示机械执行/观察事实，不代表任务完成或语义成功。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "schema": {"type": "string", "enum": ["smc.semantic_action.v0.1"]},
            "domain": {"type": "string", "enum": ["browser"]},
            "scope_ref": {"type": "string", "minLength": 1},
            "action_id": {"type": "string", "minLength": 1},
            "verb": {"type": "string", "enum": ["click", "fill", "select", "navigate", "scroll"]},
            "target_id": {"type": "string", "minLength": 1},
            "args": {"type": "object", "description": "verb-specific closed args; runtime cross-field validates exact keys"},
            "operation_class": {"type": "string", "enum": ["mutate"]},
            "idempotency_class": {"type": "string", "enum": ["unknown"]},
            "atomicity_class": {"type": "string", "enum": ["single_dispatch"]},
            "expected_version": {"type": "string", "minLength": 1},
            "version_scope": {"type": "string", "enum": ["object", "resource", "snapshot"]},
            "version_precondition": {"type": "string", "enum": ["required"]},
        },
        "required": [
            "schema", "domain", "scope_ref", "action_id", "verb", "target_id", "args",
            "operation_class", "idempotency_class", "atomicity_class", "expected_version",
            "version_scope", "version_precondition",
        ],
        "additionalProperties": False,
    }

    def __init__(self, *, adapter: BrowserActionAdapter, session_id_getter: Callable[[], str]) -> None:
        self._adapter = adapter
        self._session_id_getter = session_id_getter

    def execute(self, **kwargs: Any) -> ToolResult:
        session_id = str(self._session_id_getter() or "").strip()
        if not session_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[browser_action] current session unavailable; mutation not dispatched.",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            receipt = self._adapter.execute(session_id, dict(kwargs))
        except Exception as exc:  # noqa: BLE001 - adapter implementation faults are tool errors.
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[browser_action] adapter error; no implicit retry. error_type={type(exc).__name__}; error={exc}",
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
