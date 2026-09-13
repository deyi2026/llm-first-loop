"""Model-facing Browser semantic execution tool.

The semantic compiler is deliberately encapsulated inside this tool.  The model chooses
an exact observed GroundingRef and a verb; the tool derives only mechanical action fields
and delegates safety/version/single-dispatch enforcement to BrowserActionAdapter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from llm_loop.browser.action import BrowserActionAdapter
from llm_loop.browser.method_card import SEMANTIC_OPERATION_METHOD_CARD
from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus

_OBJECT_VERBS = {"click", "fill", "select", "scroll"}
_SUPPORTED_VERBS = _OBJECT_VERBS | {"navigate"}


class BrowserSemanticExecuteCompileError(ValueError):
    """Mechanical compile failure before any Browser mutation dispatch."""


class BrowserSemanticExecuteTool:
    name = "browser_semantic_execute"
    description = (
        SEMANTIC_OPERATION_METHOD_CARD
        + " 用法：必须先 browser_perceive(action=snapshot) 观察并取得 exact ref；没有 snapshot/ref 不要调用。"
        "模型按用户意图选择一个 exact "
        "GroundingRef；对象操作调用 browser_semantic_execute(verb=click|fill|select|scroll, "
        "target_ref=<SemanticObject.grounding_ref>, args=<verb 参数>)；navigate 使用该 snapshot "
        "返回的 resource_ref；不要把 URL、名称或 scope_ref 猜作 target_ref。读取 ActionReceipt 后，再 browser_perceive(action=snapshot) "
        "Re-observe/Verify。例：点击 Commit 时，先从 snapshot 选择 Commit 对象的 GroundingRef，"
        "再调用 verb=click,target_ref=<该ref>,args={}。fill args={text,mode}，mode=replace|append；"
        "select args={value}；navigate args={url}；scroll args={delta_pages}。工具内部只把模型已选择的"
        "exact ref 编译为 SemanticAction 的 scope/version/target/action_id 等机械字段，并交给既有"
        "single-dispatch/version guard；不自动选择目标，不自动 retry，不自动 rebind/latest，"
        "ActionReceipt ok 不等于任务完成，工具不判断任务完成。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "verb": {
                "type": "string",
                "enum": ["click", "fill", "select", "navigate", "scroll"],
            },
            "target_ref": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "先 snapshot；对象操作传当前 observation 中被模型选定 SemanticObject.grounding_ref；"
                    "navigate 传该 snapshot 的 resource_ref。必须是 exact ref；不要把 URL、名称或 scope_ref 当 target_ref。"
                ),
            },
            "args": {
                "type": "object",
                "description": (
                    "closed verb args: click={}；fill={text,mode} mode=replace|append；"
                    "select={value}；navigate={url}；scroll={delta_pages}"
                ),
            },
        },
        "required": ["verb", "target_ref", "args"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        perception: BrowserPerceptionAdapter,
        action_adapter: BrowserActionAdapter,
        session_id_getter: Callable[[], str],
    ) -> None:
        self._perception = perception
        self._action_adapter = action_adapter
        self._session_id_getter = session_id_getter

    @staticmethod
    def _action_id(*, verb: str, target_ref: str, args: dict[str, Any]) -> str:
        # The exact GroundingRef contains the immutable observation version. Repeating the
        # same semantic request therefore reuses the same action_id and is rejected by the
        # existing reservation store rather than silently dispatching twice. A fresh
        # observation yields a fresh ref and thus a new explicit model action opportunity.
        wire = json.dumps(
            {"verb": verb, "target_ref": target_ref, "args": args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sact-{hashlib.sha256(wire).hexdigest()[:24]}"

    @staticmethod
    def _normalize_request(
        request: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        if set(request) != {"verb", "target_ref", "args"}:
            raise BrowserSemanticExecuteCompileError("semantic_execute_fields_mismatch")
        verb = str(request.get("verb") or "").strip()
        if verb not in _SUPPORTED_VERBS:
            raise BrowserSemanticExecuteCompileError("verb_not_in_browser_mutation_profile")
        target_ref = str(request.get("target_ref") or "").strip()
        if not target_ref:
            raise BrowserSemanticExecuteCompileError("target_ref_missing")
        args = request.get("args")
        if not isinstance(args, dict):
            raise BrowserSemanticExecuteCompileError("args_must_be_object")
        args = dict(args)
        # Deterministic mechanical normalization (FC1 fix, 2026-09-13 ruling): the fully
        # unambiguous wrapper shape {"<verb>": {canonical args}} is unwrapped by the
        # compiler. Everything else (multi-key, extra top-level keys, non-dict wrapper
        # value, inner keys outside the verb contract) stays fail-closed and is rejected
        # by the adapter as before. The value is carried verbatim; nothing is guessed.
        args_normalization = {"applied": False, "rule": None}
        if set(args) == {verb} and isinstance(args[verb], dict):
            args = dict(args[verb])
            args_normalization = {"applied": True, "rule": "verb_wrapper_unwrap"}
        return verb, target_ref, args, args_normalization

    def compile_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        """Mechanically compile one already-selected exact ref; never recapture or choose."""
        if not session_id:
            raise BrowserSemanticExecuteCompileError("session_id_missing")
        verb, target_ref, args, args_normalization = self._normalize_request(request)
        hydrated = self._perception.hydrate(session_id, target_ref)
        availability = str(hydrated.get("availability") or "unavailable")
        if availability != "available":
            reason = str(hydrated.get("reason") or availability)
            raise BrowserSemanticExecuteCompileError(
                f"target_ref_{availability}:{reason}"
            )
        content = hydrated.get("content")
        if not isinstance(content, dict):
            raise BrowserSemanticExecuteCompileError("target_ref_projection_mismatch")

        if verb in _OBJECT_VERBS:
            semantic_object = content.get("semantic_object")
            if not isinstance(semantic_object, dict):
                raise BrowserSemanticExecuteCompileError("target_ref_projection_mismatch")
            if str(semantic_object.get("grounding_ref") or "") != target_ref:
                raise BrowserSemanticExecuteCompileError("target_ref_identity_mismatch")
            target_id = str(semantic_object.get("id") or "").strip()
            scope_ref = str(semantic_object.get("scope_ref") or "").strip()
            expected_version = str(semantic_object.get("observed_version") or "").strip()
            version_scope = "object"
        else:
            if (
                content.get("schema") != "smc.browser_resource_grounding.v0.1"
                or content.get("kind") != "page"
            ):
                raise BrowserSemanticExecuteCompileError("target_ref_projection_mismatch")
            if str(content.get("grounding_ref") or "") != target_ref:
                raise BrowserSemanticExecuteCompileError("target_ref_identity_mismatch")
            scope_ref = str(content.get("scope_ref") or "").strip()
            expected_version = str(content.get("observed_version") or "").strip()
            target_id = scope_ref
            version_scope = "resource"

        if not target_id or not scope_ref or not expected_version:
            raise BrowserSemanticExecuteCompileError("target_ref_incomplete")
        return {
            "schema": "smc.semantic_action.v0.1",
            "domain": "browser",
            "scope_ref": scope_ref,
            "action_id": self._action_id(verb=verb, target_ref=target_ref, args=args),
            "verb": verb,
            "target_id": target_id,
            "args": args,
            "args_normalization": dict(args_normalization),
            "operation_class": "mutate",
            "idempotency_class": "unknown",
            "atomicity_class": "single_dispatch",
            "expected_version": expected_version,
            "version_scope": version_scope,
            "version_precondition": "required",
        }

    def execute_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._action_adapter.execute(session_id, self.compile_request(session_id, request))

    def execute(self, **kwargs: Any) -> ToolResult:
        session_id = str(self._session_id_getter() or "").strip()
        if not session_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[browser_semantic_execute] current session unavailable; no mutation dispatched.",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            receipt = self.execute_request(session_id, dict(kwargs))
        except BrowserSemanticExecuteCompileError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[browser_semantic_execute] exact semantic compile rejected; "
                    f"reason={exc}; no mutation dispatched; no automatic retry/rebind. "
                    "RECOVERY CONTRACT (this is a rejection of your declared action, "
                    "NOT an unmet wait condition; do not answer it with any wait tool): "
                    "(1) call browser_perceive(action=snapshot) on the current scope; "
                    "(2) from that snapshot result take resource_ref for verb=navigate "
                    "or the target SemanticObject.grounding_ref for object verbs; "
                    "(3) re-dispatch this same verb with that exact ref and the same args."
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - adapter implementation faults are tool errors.
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    "[browser_semantic_execute] adapter error; no implicit retry. "
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
