"""Typed P4-LIVE ActionRef Browser mutation facades.

The five model-facing tools expose only an opaque ActionRef plus verb-specific semantic
arguments. All identity/version/execution facts come from qualified mechanical
authorities; this module performs no target search, matching, rebinding, or retry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from llm_loop.browser.action import BrowserActionAdapter
from llm_loop.browser.action_ref import ActionRefResolveContext, ActionRefResolver
from llm_loop.browser.action_ref_execution import ActionRefExecutionBridgeStore
from llm_loop.browser.action_ref_recovery import ActionRefCrashCorrelator
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.tool_execution_journal import current_action_ref_effect_binding_authority
from llm_loop.tools.builtin.browser_action_ref_kernel import ActionRefSemanticCompileBridge

TargetKind = Literal["object", "resource"]


class ActionRefMutationError(RuntimeError):
    """Stable mechanical rejection before or during a typed ActionRef mutation."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


class ActionRefMutationKernel:
    """Compose S1/S2/S3 primitives in the frozen G2-S4 order."""

    def __init__(
        self,
        *,
        resolver: ActionRefResolver,
        compiler: ActionRefSemanticCompileBridge,
        execution_bridge: ActionRefExecutionBridgeStore,
        crash_correlator: ActionRefCrashCorrelator,
        action_adapter: BrowserActionAdapter,
    ) -> None:
        self._resolver = resolver
        self._compiler = compiler
        self._execution_bridge = execution_bridge
        self._crash_correlator = crash_correlator
        self._action_adapter = action_adapter

    def execute(
        self,
        *,
        action_ref: str,
        verb: str,
        args: dict[str, Any],
        expected_kind: TargetKind,
    ) -> dict[str, Any]:
        opaque_ref = str(action_ref or "").strip()
        if not opaque_ref:
            raise ActionRefMutationError("action_ref_missing", "ActionRef is required")

        with current_action_ref_effect_binding_authority() as outer:
            resolution = self._resolver.resolve(
                opaque_ref,
                context=ActionRefResolveContext(
                    session_id=outer.session_id,
                    workspace_scope=outer.workspace_root,
                    current_run_generation=outer.origin_run_generation,
                    run_active=True,
                ),
                expected_kind=expected_kind,
            )
            compiled = self._compiler.compile_resolved(
                session_id=outer.session_id,
                resolution=resolution,
                verb=verb,
                args=dict(args),
            )
            expected_outer_execution = outer.execution_id
            expected_session = outer.session_id

        prepared = self._execution_bridge.prepare_current(
            resolution=resolution,
            inner_action_id=str(compiled.semantic_action["action_id"]),
            expected_version=str(compiled.semantic_action["expected_version"]),
        )
        if (
            str(prepared.get("execution_id") or "") != expected_outer_execution
            or str(prepared.get("session_id") or "") != expected_session
        ):
            raise ActionRefMutationError(
                "action_ref_execution_binding_drift",
                "PREPARED bridge no longer matches the exact outer execution",
            )

        with current_action_ref_effect_binding_authority() as outer:
            if (
                outer.execution_id != expected_outer_execution
                or outer.session_id != expected_session
            ):
                raise ActionRefMutationError(
                    "action_ref_execution_binding_drift",
                    "current outer execution changed before Browser entry",
                )
            self._crash_correlator.arm_receipt_cursor(
                outer.session_id, outer.execution_id
            )
            self._action_adapter.bind_observed_target(
                resolution.browser_target_id_sha256
            )

        # Existing BrowserActionAdapter remains the sole fresh version/stable identity,
        # running receipt/effect authority/single-dispatch/terminal receipt authority.
        return self._action_adapter.execute(
            expected_session, dict(compiled.semantic_action)
        )


@dataclass(frozen=True)
class _ToolContract:
    name: str
    verb: str
    expected_kind: TargetKind
    properties: dict[str, Any]
    required: tuple[str, ...]


_CONTRACTS = (
    _ToolContract(
        "browser_semantic_click",
        "click",
        "object",
        {"action_ref": {"type": "string", "minLength": 1}},
        ("action_ref",),
    ),
    _ToolContract(
        "browser_semantic_fill",
        "fill",
        "object",
        {
            "action_ref": {"type": "string", "minLength": 1},
            "text": {"type": "string"},
            "mode": {"type": "string", "enum": ["replace", "append"]},
        },
        ("action_ref", "text", "mode"),
    ),
    _ToolContract(
        "browser_semantic_select",
        "select",
        "object",
        {
            "action_ref": {"type": "string", "minLength": 1},
            "value": {"type": "string"},
        },
        ("action_ref", "value"),
    ),
    _ToolContract(
        "browser_semantic_scroll",
        "scroll",
        "object",
        {
            "action_ref": {"type": "string", "minLength": 1},
            "delta_pages": {"type": "number"},
        },
        ("action_ref", "delta_pages"),
    ),
    _ToolContract(
        "browser_semantic_navigate",
        "navigate",
        "resource",
        {
            "action_ref": {"type": "string", "minLength": 1},
            "url": {"type": "string", "minLength": 1},
        },
        ("action_ref", "url"),
    ),
)


class TypedActionRefMutationTool:
    """One closed-schema verb facade over the shared exact mutation kernel."""

    def __init__(self, *, kernel: ActionRefMutationKernel, contract: _ToolContract) -> None:
        self._kernel = kernel
        self._contract = contract
        self.name = contract.name
        self.description = (
            f"P4-LIVE typed Browser {contract.verb}: use only an exact ActionRef from "
            "the current browser_perceive snapshot; no target search/rebind/retry."
        )
        self.parameters = {
            "type": "object",
            "properties": dict(contract.properties),
            "required": list(contract.required),
            "additionalProperties": False,
        }

    def _semantic_args(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if set(kwargs) != set(self._contract.required):
            raise ActionRefMutationError(
                "action_ref_typed_args_mismatch",
                f"{self.name} requires exactly {','.join(self._contract.required)}",
            )
        if self._contract.verb == "click":
            return {}
        if self._contract.verb == "fill":
            return {"text": kwargs["text"], "mode": kwargs["mode"]}
        if self._contract.verb == "select":
            return {"value": kwargs["value"]}
        if self._contract.verb == "scroll":
            return {"delta_pages": kwargs["delta_pages"]}
        return {"url": kwargs["url"]}

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            receipt = self._kernel.execute(
                action_ref=str(kwargs.get("action_ref") or ""),
                verb=self._contract.verb,
                args=self._semantic_args(dict(kwargs)),
                expected_kind=self._contract.expected_kind,
            )
        except Exception as exc:  # noqa: BLE001 - mechanical rejection stays explicit.
            code = str(getattr(exc, "code", type(exc).__name__))
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[{self.name}] rejected before successful mutation; reason_code={code}; "
                    "no automatic retry/search/rebind."
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        status = str(receipt.get("status") or "")
        return ToolResult(
            status=(
                ToolResultStatus.SUCCESS
                if status == "ok"
                else ToolResultStatus.FAILURE
            ),
            content=json.dumps(
                receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            tool_call_id="",
            tool_name=self.name,
        )


def build_typed_action_ref_mutation_tools(
    kernel: ActionRefMutationKernel,
) -> tuple[TypedActionRefMutationTool, ...]:
    return tuple(
        TypedActionRefMutationTool(kernel=kernel, contract=item) for item in _CONTRACTS
    )
