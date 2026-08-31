"""Evidence-aware source resolution for probeable sources.

R9 deliberately resolves only probeable FILE reads.  It never reasons from user prose or
repeat fingerprints: owner, source identity, freshness and source coverage are the complete
eligibility contract.  Non-file source kinds remain physical acquisitions unless explicitly
recovered through the Evidence control plane.

R8.24-C C-D9 (r-p-r P1-2): a ``current_evidence_covers_request`` hit MUST inline the
observation text into the tool receipt (the receipt body is the actual output).  A hit
that cannot inline (blob read failure / budget exceeded) is reported as ``failure``
instead of ``success`` with a metadata-only JSON body — silent content swallowing is
forbidden ("information is never lost" core promise).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from llm_loop.core.message import RecoverabilityStatus, ToolCall, ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
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

logger = logging.getLogger(__name__)


class EvidenceSourceResolver:
    """Resolve a source-data request from already-current Evidence when safe."""

    def __init__(
        self,
        ledger: EvidenceLedgerStore,
        *,
        freshness: EvidenceFreshness,
        owner_resolver: Callable[[], OwnerScope],
        blobs: BlobStore | None = None,
        inline_budget_chars: int = 5000,
    ) -> None:
        self.ledger = ledger
        self.freshness = freshness
        self.owner_resolver = owner_resolver
        # R8.24-C C-D9: 内联正文所需 blob 读取面（None=无法内联——命中即如实 failure）
        self.blobs = blobs
        self.inline_budget_chars = inline_budget_chars

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

    def _inline_observation(self, record: EvidenceRecord, requested: Coverage) -> str | None:
        """内联命中 Evidence 的完整 observation（fail 失败返回 None → 如实 failure）.

        blob 是该次工具调用的完整观察（含行号/元信息头，Coverage 声明其对底层
        source 的覆盖范围；_record_can_cover 已保证覆盖本请求范围）。内联完整
        观察即提供含请求范围的正文——无重排、无伪造；超预算/读取失败如实 failure。
        """
        if self.blobs is None:
            return None
        try:
            text = self.blobs.read_text(record.blob_ref)
        except Exception:  # noqa: BLE001 — blob 读取失败属基础设施故障，如实 failure
            logger.warning(
                "evidence_reuse inline read failed (fail-closed to failure receipt)",
                exc_info=True,
            )
            return None
        if len(text) > self.inline_budget_chars:
            logger.info(
                "event=evidence_reuse_inline_over_budget chars=%d budget=%d ref=%s",
                len(text),
                self.inline_budget_chars,
                record.evidence_ref.ref,
            )
            return None
        return text

    def _reuse_result(self, call: ToolCall, record: EvidenceRecord, requested: Coverage) -> ToolResult:
        # R8.24-C C-D9: 命中必须内联正文；无法内联（无 blob 面/读取失败/超预算）→
        # status=failure 如实回执（success + 无正文 + 仅元数据 = 0，静默吞正文禁止）。
        segment = self._inline_observation(record, requested)
        if segment is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[复用失败] verified-current Evidence 已覆盖该读取范围，但正文无法内联"
                    "（blob 读取失败或超出内联预算）。"
                    f"evidence_ref={record.evidence_ref.ref}；"
                    "force_refresh=true 参数语义为显式物理重读。"
                ),
                tool_call_id=call.id,
                tool_name=call.name,
                recoverability_status=RecoverabilityStatus.RECORDED,
                evidence_ref=record.evidence_ref.ref,
                evidence_representation="ref_only",
                evidence_projection_complete=False,
                source_resolution_mode="evidence_reuse",
                source_execution_performed=False,
            )
        # 正文即 actual output（C-D1 白名单）；单行事实行陈述复用来源（非程序建议）。
        _cov = record.coverage.to_dict()
        fact_line = (
            f"[evidence_reuse] freshness=verified_current ref={record.evidence_ref.ref} "
            f"coverage_unit={_cov.get('unit')} coverage_start={_cov.get('start')} "
            f"coverage_end={_cov.get('end_exclusive')} source_complete={_cov.get('source_complete')}"
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"{segment}\n{fact_line}",
            tool_call_id=call.id,
            tool_name=call.name,
            recoverability_status=RecoverabilityStatus.RECORDED,
            evidence_ref=record.evidence_ref.ref,
            evidence_representation="ref_only",
            evidence_projection_complete=False,
            source_resolution_mode="evidence_reuse",
            source_execution_performed=False,
        )
