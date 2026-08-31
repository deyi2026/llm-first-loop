"""ERC Phase3 canonical capture-before-projection adapter.

Unlike the Phase2 shadow recorder, this adapter is allowed to change model-visible output:
the source action returns an unprojected Tool Observation, durable Evidence capture commits
first, then a bounded ProjectionEngine view plus deterministic recovery capsule is emitted.
Capture failure never rewrites the source action status and never re-executes the action.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from llm_loop.core.message import RecoverabilityStatus, ToolCall, ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    EvidenceCapture,
    OwnerScope,
    ProjectionEngine,
    Provenance,
    make_capture_request,
)
from llm_loop.tools.evidence_shadow import source_for_call


class EvidenceEnforcer:
    def __init__(
        self,
        capture: EvidenceCapture,
        *,
        projection: ProjectionEngine,
        owner_resolver: Callable[[], OwnerScope],
        clock: Callable[[], datetime] | None = None,
        projection_budget_chars: int = 5000,
    ) -> None:
        if projection_budget_chars < 128:
            raise ValueError("projection_budget_chars must be >= 128")
        self.capture = capture
        self.projection = projection
        self.owner_resolver = owner_resolver
        self.clock = clock or (lambda: datetime.now(UTC))
        self.projection_budget_chars = projection_budget_chars

    def apply(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        budget_chars: int | None = None,
        temperature: str = "hot",
    ) -> ToolResult:
        """Capture raw observation first, then replace content with a bounded projection."""
        # R8.24-C 止血（design D2 status 门）：非 SUCCESS 回执（FAILURE/ERROR/TIMEOUT/BLOCKED，
        # 含 status 缺失的保守跳过）不再 capture/投影——失败回执附带的 recover 胶囊会构成
        # 递归诱饵（read_file 误读 evidence:// 死循环实证），且失败内容无恢复价值。
        _status = getattr(result, "status", None)
        if _status is None or str(_status) != ToolResultStatus.SUCCESS:
            return result
        raw = result.raw_observation if result.raw_observation is not None else result.content
        source, coverage = source_for_call(call, result)
        budget = max(128, budget_chars or self.projection_budget_chars)
        try:
            captured = self.capture.capture(
                make_capture_request(
                    owner=self.owner_resolver(),
                    stable_capture_id=call.id,
                    raw_observation=raw,
                    acquired_at=self.clock(),
                    tool_name=call.name,
                    tool_call_id=call.id,
                    source=source,
                    coverage=coverage,
                    provenance=Provenance(
                        producer="tool_registry_enforce",
                        authority="tool_observation",
                        scope=result.status.value,
                    ),
                )
            )
        except Exception:
            # Action truth is already fixed by the completed tool execution.  Do not turn a
            # recoverability failure into a tool failure and do not repeat the source action.
            result.recoverability_status = RecoverabilityStatus.FAILED
            result.evidence_ref = None
            result.evidence_representation = None
            result.evidence_projection_complete = None
            result.content = self._capture_failure_view(raw, budget_chars=budget)
            return result

        try:
            projection = self.projection.project(
                raw,
                evidence_ref=captured.evidence_ref,
                source_label=f"{call.name}:{source.safe_locator}",
                coverage_label=coverage.label,
                budget_chars=budget,
                temperature=temperature,
            )
        except Exception:
            # The Evidence blob is durable even if projection rendering fails.  Keep the
            # source action truth and expose a minimal exact recovery handle instead of
            # pretending recoverability failed or re-running the source.
            result.recoverability_status = RecoverabilityStatus.RECORDED
            result.evidence_ref = captured.evidence_ref.ref
            result.evidence_representation = "ref_only"
            result.evidence_projection_complete = False
            result.content = (
                "[evidence projection failed] ACTION ALREADY EXECUTED; durable Evidence is "
                f"available at {captured.evidence_ref.ref}; recover=read_evidence"
            )
            return result

        result.content = f"{projection.content}\n{projection.model_capsule}"
        result.recoverability_status = RecoverabilityStatus.RECORDED
        result.evidence_ref = captured.evidence_ref.ref
        result.evidence_representation = projection.metadata.representation.value
        result.evidence_projection_complete = projection.metadata.projection_complete
        return result

    @staticmethod
    def _capture_failure_view(raw: str, *, budget_chars: int) -> str:
        notice = (
            "[recoverability: failed] ACTION ALREADY EXECUTED; durable Evidence capture failed. "
            "Do not automatically re-run the source action solely to recover this output."
        )
        if len(raw) + len(notice) + 1 <= budget_chars:
            return f"{raw}\n{notice}"
        return notice
