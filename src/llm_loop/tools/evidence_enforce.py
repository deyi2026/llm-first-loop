"""ERC Phase3 canonical capture-before-projection adapter.

Unlike the Phase2 shadow recorder, this adapter is allowed to change model-visible output:
the source action returns an unprojected Tool Observation, durable Evidence capture commits
first, then a bounded ProjectionEngine view plus deterministic recovery capsule is emitted.
Capture failure never rewrites the source action status and never re-executes the action.
"""

from __future__ import annotations

import logging
import os
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

logger = logging.getLogger(__name__)


def _capsule_mode() -> str:
    """R8.24-C C-2.1（C-D4）: evidence capsule 投影模式（三态）.

    - "on":        capsule 照旧拼接
    - "shadow":    capsule 照旧投影 + 记"若 enforce 则省略 chars"计数事件
    - "off"（默认，R9-P0-01 批 1/3 切换 2026-09-01，前置=CORE9 终判已生效）:
                    complete=true 回执不拼接 capsule（metadata 六字段照落审计）；
                    complete=false 回执以单行事实行（C-D5 三元组）替换 capsule
    evidence.py render_capsule 本体与存储层零改动（R-4 红线）——开关只落在
    本调用方（与 D2 status 门 :52 叠加不冲突）。
    """
    raw = (os.environ.get("LFL_EVIDENCE_CAPSULE", "off") or "off").strip().lower()
    return raw if raw in {"on", "shadow", "off"} else "off"


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
            # R8.24-C C-2.3（C-G5）: 程序指令/喊话句式退出——纯事实（action 已执行 +
            # durable Evidence ref + representation/projection 状态事实）；恢复路由由
            # ref resolver 与 get_tool_schema 按需发现承载（C-D8），不在回执喊话。
            result.content = (
                "[evidence projection failed] ACTION ALREADY EXECUTED; durable Evidence is "
                f"available at {captured.evidence_ref.ref}; representation=ref_only; "
                "projection=failed"
            )
            return result

        result.recoverability_status = RecoverabilityStatus.RECORDED
        result.evidence_ref = captured.evidence_ref.ref
        result.evidence_representation = projection.metadata.representation.value
        result.evidence_projection_complete = projection.metadata.projection_complete
        # R8.24-C C-2.1/C-2.2（C-D4/C-D5）: capsule 投影三态开关（默认 on 现状逐字节一致）
        _mode = _capsule_mode()
        if _mode == "off":
            # capsule 完整字段（ref/source/coverage/projection/complete/recover）落
            # result metadata + 审计事件（不静默丢数据——§7.2 数据持久性强化项）
            result.evidence_source_label = f"{call.name}:{source.safe_locator}"
            result.evidence_coverage_label = coverage.label
            if projection.metadata.projection_complete:
                # complete=true 面（存量 1,534 条形态）: capsule chars=0
                result.content = projection.content
            else:
                # complete=false 面（存量 104 条形态）: 单行稳定事实行——C-D5 三元组
                # （≤1 行、仅含 result_truncated/omitted/recovery_ref 三字段；多行
                # capsule 模板与 recover= 喊话全部退出，路由由 ref resolver 承载）
                _fact_line = (
                    f"result_truncated=true omitted=true recovery_ref={captured.evidence_ref.ref}"
                )
                result.content = (
                    f"{projection.content}\n{_fact_line}"
                    if projection.content
                    else _fact_line
                )
            logger.info(
                "event=evidence_capsule_omitted tool=%s complete=%s omitted_chars=%d ref=%s",
                call.name,
                bool(projection.metadata.projection_complete),
                len(projection.model_capsule),
                captured.evidence_ref.ref,
            )
        else:
            if _mode == "shadow":
                logger.info(
                    "event=evidence_capsule_shadow_omittable tool=%s complete=%s "
                    "would_omit_chars=%d ref=%s",
                    call.name,
                    bool(projection.metadata.projection_complete),
                    len(projection.model_capsule),
                    captured.evidence_ref.ref,
                )
            result.content = f"{projection.content}\n{projection.model_capsule}"
        return result

    @staticmethod
    def _capture_failure_view(raw: str, *, budget_chars: int) -> str:
        # R8.24-C C-2.3（C-G5）: "Do not automatically re-run..." 类程序指令退出——
        # 保留 capture 失败的客观事实（什么动作、什么状态）；重跑与否的决策归模型/用户。
        notice = (
            "[recoverability: failed] ACTION ALREADY EXECUTED; durable Evidence capture "
            "failed; capture_status=failed; source_action_output=preserved."
        )
        if len(raw) + len(notice) + 1 <= budget_chars:
            return f"{raw}\n{notice}"
        return notice
