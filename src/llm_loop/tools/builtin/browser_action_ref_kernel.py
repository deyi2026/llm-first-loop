"""Hidden non-provider compile bridge for P4-LIVE ActionRef.

This module performs no Browser execution.  It accepts one already-resolved ActionRef
and delegates its exact hidden GroundingRef to the existing semantic compiler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from llm_loop.browser.action_ref import ActionRefResolution


class _BrowserSemanticCompiler(Protocol):
    def compile_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]: ...


class ActionRefSemanticCompileError(RuntimeError):
    """Stable mechanical rejection for hidden ActionRef compiler-basis drift."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True)
class CompiledActionRefMutation:
    semantic_action: dict[str, Any]
    grounding_ref: str
    observed_snapshot_id: str
    browser_target_id_sha256: str


class ActionRefSemanticCompileBridge:
    """Delegate one exact resolved GroundingRef to the existing compiler authority."""

    def __init__(self, *, compiler: _BrowserSemanticCompiler) -> None:
        self._compiler = compiler

    def compile_resolved(
        self,
        *,
        session_id: str,
        resolution: ActionRefResolution,
        verb: str,
        args: dict[str, Any],
    ) -> CompiledActionRefMutation:
        grounding_ref = str(resolution.grounding_ref or "")
        observed_snapshot_id = str(resolution.observed_snapshot_id or "")
        browser_target_id_sha256 = str(resolution.browser_target_id_sha256 or "")
        if not grounding_ref or not observed_snapshot_id or not browser_target_id_sha256:
            raise ActionRefSemanticCompileError(
                "action_ref_compile_basis_incomplete",
                "resolved ActionRef is missing exact compiler/target basis",
            )

        semantic_action = self._compiler.compile_request(
            session_id,
            {
                "verb": str(verb),
                "target_ref": grounding_ref,
                "args": dict(args),
            },
        )
        compiled_expected_version = str(semantic_action.get("expected_version") or "")
        if compiled_expected_version != observed_snapshot_id:
            raise ActionRefSemanticCompileError(
                "action_ref_expected_version_mismatch",
                "existing compiler expected_version differs from ActionRef observation",
            )
        if not str(semantic_action.get("action_id") or ""):
            raise ActionRefSemanticCompileError(
                "action_ref_inner_action_id_missing",
                "existing compiler returned no deterministic inner action_id",
            )
        return CompiledActionRefMutation(
            semantic_action=dict(semantic_action),
            grounding_ref=grounding_ref,
            observed_snapshot_id=observed_snapshot_id,
            browser_target_id_sha256=browser_target_id_sha256,
        )
