"""evolution_complete 工具实现（M17 FR-REVIEW-AI-01 闭环修复 / design §8.1）.

AI 执行完成登记（executing→executed，executor=ai）: 程序只提供"入口 + 状态推进 + 审计落盘"，
执行动作/验证/回滚仍交 AI（M16 移交语义不倒退，RULE-AI-06 子规则 4 承载）。

- CompleteRequest: 入参（suggestion_id/note/actions，frozen）
- CompleteResult: 出参（status=executed/executor=ai/verify_result/registered/error，frozen，如实）
- run_evolution_complete: 工具层前置校验（非 executing 如实原因防重复登记）→ 调
  EvolutionExecutor.complete() → CompleteResult（registered 核验落盘；fail-open 如实标注）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from llm_loop.core.message import ToolResult, ToolResultStatus


@dataclass(frozen=True)
class CompleteRequest:
    """evolution_complete 工具入参（frozen，类型安全）."""

    suggestion_id: str
    note: str  # 验证结论/执行说明（如实回传，RULE-AI-06 子规则 1/2 汇报）
    actions: tuple[dict, ...] = ()  # 已登记执行动作列表（可选，如实留痕）


@dataclass(frozen=True)
class CompleteResult:
    """evolution_complete 工具出参（frozen，如实回执）.

    M19 FIX-01: error 字段透传执行器层标注（"状态未推进（建议不存在）"等），
    registered=状态推进成功且无 error（消除"不存在也报登记成功"的假回执）。
    """

    suggestion_id: str
    status: Literal["executed"]
    executor: Literal["ai"]
    verify_result: Literal["unverified", "ai_reported"]
    note: str
    registered: bool  # 登记是否成功落盘（fail-open 如实标注）
    error: str = ""  # 登记失败原因（registered=False 时如实填充）


EVOLUTION_COMPLETE_TOOL_DEF: dict = {
    "name": "evolution_complete",
    "description": (
        "登记演进执行完成（executing→executed，executor=ai）。何时用: 你经修正工具"
        "（adjust_strategy/retry_tool/refresh_config/恢复工具）落地了 executing 状态的演进建议"
        "（RULE-AI-06 子规则 4），执行完成后调用本工具登记'已完成 + 验证结论'。"
        "何时不用: 建议尚在执行中（未完成修正动作）或你不确定是否完成时不要登记。"
        "note 需如实回传验证结论（按子规则 1 对比执行前后架构状态），未验证如实标注 unverified。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "suggestion_id": {
                "type": "string",
                "description": "演进建议 ID（EVO-...，executing 状态）",
            },
            "note": {
                "type": "string",
                "description": "执行说明 + 验证结论（如实回传，落盘 evolution_exec_log）",
            },
            "actions": {
                "type": "array",
                "items": {"type": "object"},
                "description": "已执行动作列表（可选）",
            },
        },
        "required": ["suggestion_id", "note"],
    },
}


def run_evolution_complete(ctx: Any, executor: Any, audit: Any, args: dict) -> ToolResult:
    """evolution_complete: 登记演进执行完成（executor=ai，fail-open 如实标注）.

    ctx: CorrectionContext（evolution_store 用于前置校验）;
    executor: EvolutionExecutor（complete() 状态推进 + 审计）;
    audit: 审计落盘 callable（self_correction_log 记录工具调用）。
    """
    suggestion_id = str(args.get("suggestion_id", "")).strip()
    note = str(args.get("note", "")).strip()
    if not suggestion_id or not note:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 缺少必填参数 'suggestion_id'/'note'（登记演进执行完成需提供建议 ID 与执行说明）",
            tool_call_id="",
            tool_name="evolution_complete",
        )
    # 工具层前置校验（design 8.12.1 + M19 FIX-01 三态区分）:
    # 不存在（list 正常返回但无该 id）→ FAILURE 引导；存在但非 executing → 拒绝；
    # 读取失败（OSError）→ fail-open 放行（DFX-REL-08，不误判"建议不存在"）
    store = getattr(ctx, "evolution_store", None)
    if store is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[演进建议不可用] 事实: 演进建议存储未装配。原因: EVOLVE_ENABLED=0。建议: 检查配置。",
            tool_call_id="",
            tool_name="evolution_complete",
        )
    current_status = None
    found = False  # M19 FIX-01: 显式 found 标志区分"不存在"与"读取失败"
    read_failed = False  # M19 FIX-01: 读取失败第三态（fail-open 放行，不误判"不存在"）
    try:
        for entry in store.list():
            if entry.get("id") == suggestion_id:
                current_status = entry.get("status")
                found = True
                break
    except OSError:
        read_failed = True  # fail-open: 读取失败放行（DFX-REL-08，不误判"建议不存在"）
    if not found and not read_failed:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[建议不存在] 事实: 建议 {suggestion_id} 不存在。"
                "原因: suggestion_id 可能拼写错误或已被移除。"
                "建议: 用 `search_records(kind=evolution)` 查询正确 ID 后重试。"
            ),
            tool_call_id="",
            tool_name="evolution_complete",
        )
    if found and current_status != "executing":
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[无需登记] 事实: 建议 {suggestion_id} 当前状态 '{current_status}'。"
                "原因: 仅 executing 状态需登记完成（防重复登记/乱登记）。"
                '建议: 如需人工标记涉边界演进完成，请用 CLI `evolve-complete <id> "<结果说明>"`。'
            ),
            tool_call_id="",
            tool_name="evolution_complete",
        )
    # 调 EvolutionExecutor.complete()（状态推进 executing→executed + evolution_exec_log 审计）
    try:
        outcome = executor.complete(
            suggestion_id,
            actions=list(args.get("actions") or [])
            if isinstance(args.get("actions"), list)
            else [],
            note=note,
        )
    except Exception as exc:  # noqa: BLE001 — 登记异常如实降级（fail-open）
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[登记失败] 事实: 建议 {suggestion_id} 完成登记异常。原因: {exc}。"
                "建议: 稍后重试；如持续失败请检查审计目录可写性（执行完成登记不可用不影响已执行修正动作）。"
            ),
            tool_call_id="",
            tool_name="evolution_complete",
        )
    audit("evolution_complete", {"suggestion_id": suggestion_id, "note": note[:200]}, "success")
    error = getattr(outcome, "error", "") or ""
    result = CompleteResult(
        suggestion_id=suggestion_id,
        status="executed",
        executor="ai",
        verify_result="ai_reported" if note.strip() else "unverified",
        note=note,
        registered=outcome.status == "executed" and not error,  # M19 FIX-01: 状态推进成功且无 error
        error=error,
    )
    if error:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[登记失败] 事实: 建议 {suggestion_id} 状态未推进（{error}）。"
                "原因: 建议不存在或状态不匹配。"
                "建议: 用 `search_records(kind=evolution)` 查询正确 ID 后重试。"
            ),
            tool_call_id="",
            tool_name="evolution_complete",
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[演进执行完成登记] id={result.suggestion_id} 状态={result.status} "
            f"executor={result.executor} verify={result.verify_result} registered={result.registered}。\n"
            f"note: {result.note[:300]}\n"
            "登记已落盘 evolution_exec_log（可 search_records(kind=evolution_exec) 检索）。"
        ),
        tool_call_id="",
        tool_name="evolution_complete",
    )
