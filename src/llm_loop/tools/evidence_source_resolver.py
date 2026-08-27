"""Evidence-aware source resolution for probeable sources.

R9 deliberately resolves only probeable FILE reads.  It never reasons from user prose or
repeat fingerprints: owner, source identity, freshness and source coverage are the complete
eligibility contract.  Non-file source kinds remain physical acquisitions unless explicitly
recovered through the Evidence control plane.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from llm_loop.core.message import RecoverabilityStatus, ToolCall, ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    Coverage,
    EvidenceFreshness,
    EvidenceLedgerStore,
    EvidenceRecord,
    FreshnessState,
    OwnerScope,
    SourceKind,
    SourceVersionPolicy,
)
from llm_loop.tools.evidence_shadow import source_for_call


class EvidenceSourceResolver:
    """Resolve a source-data request from already-current Evidence when safe."""

    def __init__(
        self,
        ledger: EvidenceLedgerStore,
        *,
        freshness: EvidenceFreshness,
        owner_resolver: Callable[[], OwnerScope],
    ) -> None:
        self.ledger = ledger
        self.freshness = freshness
        self.owner_resolver = owner_resolver

    def resolve(self, call: ToolCall) -> ToolResult | None:
        if call.name != "read_file" or not isinstance(call.arguments, dict):
            return None
        if bool(call.arguments.get("force_refresh", False)):
            return None
        try:
            source, requested = source_for_call(call)
        except (TypeError, ValueError):
            return None
        if (
            source.kind is not SourceKind.FILE
            or source.version_policy is not SourceVersionPolicy.PROBEABLE
        ):
            return None

        owner = self.owner_resolver()
        for record in self.ledger.find_by_source(owner, source.locator):
            if not self._record_can_cover(record, requested):
                continue
            state = self.freshness.refresh(owner=owner, evidence_ref=record.evidence_ref)
            if state.freshness is not FreshnessState.VERIFIED_CURRENT:
                continue
            return self._reuse_result(call, record, requested)
        return None

    @staticmethod
    def _record_can_cover(record: EvidenceRecord, requested: Coverage) -> bool:
        if (
            record.tool_name != "read_file"
            or record.source.kind is not SourceKind.FILE
            or record.source.version_policy is not SourceVersionPolicy.PROBEABLE
            or record.coverage.unit != requested.unit
        ):
            return False
        existing = record.coverage
        if existing.source_complete:
            return True
        if (
            requested.source_complete
            or existing.end_exclusive is None
            or requested.end_exclusive is None
        ):
            return False
        return (
            existing.start <= requested.start and requested.end_exclusive <= existing.end_exclusive
        )

    @staticmethod
    def _reuse_result(call: ToolCall, record: EvidenceRecord, requested: Coverage) -> ToolResult:
        payload = {
            "schema": "evidence_source_resolution_v1",
            "kind": "source_resolution",
            "mode": "evidence_reuse",
            "source_execution": False,
            "transport": {
                "evidence_ref": record.evidence_ref.ref,
                "role": "recovery_handle",
                "is_domain_content": False,
            },
            "freshness": {"state": "verified_current", "currentness": "current"},
            "coverage": {
                "existing": record.coverage.to_dict(),
                "requested": requested.to_dict(),
            },
            "policy": {
                "reason": "current_evidence_covers_request",
                "recover": ["search_evidence", "read_evidence"],
                "force_refresh": False,
            },
        }
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            tool_call_id=call.id,
            tool_name=call.name,
            recoverability_status=RecoverabilityStatus.RECORDED,
            evidence_ref=record.evidence_ref.ref,
            evidence_representation="ref_only",
            evidence_projection_complete=False,
            source_resolution_mode="evidence_reuse",
            source_execution_performed=False,
        )
