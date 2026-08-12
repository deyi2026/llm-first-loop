"""self_evaluate 工具实现（M16 审计 FR-AUDIT-AI-14 拆分: corrections.py → tools_eval.py）.

self_evaluate: AI 主动发起自我评估（EVAL-01/04/05），五维指标来源可溯。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

SELF_EVALUATE_TOOL_DEF: dict = {
    "name": "self_evaluate",
    "description": "主动发起自我评估（五维指标: 成功率/工具效率/诚实性/停滞率/异常率，来源可溯）。何时用: 发现运行异常/完成阶段性任务/希望沉淀经验时。评估结果落盘可检索（search_records kind=self_eval），可基于评估结果 submit_evolution 提交改进建议（evidence 引用 'eval:<评估ID>'）。何时不用: 仅需查状态用 architecture_status；无需评估时不必调用（评估有成本）。失败对策: 样本不足时结果会标注“样本不足”，请基于现有数据解读，不强行下结论。",
    "parameters": {
        "type": "object",
        "properties": {
            "trigger": {
                "type": "string",
                "enum": ["periodic", "milestone", "anomaly", "manual"],
                "description": "触发原因（默认 manual）",
            }
        },
    },
}

_VALID_TRIGGERS = {"periodic", "milestone", "anomaly", "manual"}


def run_self_evaluate(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """self_evaluate: AI 主动发起自我评估（EVAL-01/04/05）.

    audit: 审计落盘 callable（corrections._audit 注入，保持共用 self_correction_log）。
    """
    evaluator = getattr(ctx, "evaluator", None)
    if evaluator is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[自我评估不可用] 事实: 自我评估器未装配。原因: SELF_EVAL_ENABLED=0 或未注入。建议: 检查配置。",
            tool_call_id="",
            tool_name="self_evaluate",
        )
    trigger = str(args.get("trigger", "manual")).strip() or "manual"
    # M19 FIX-04: 非法 trigger 不再静默回退 manual → 显式 FAILURE 三件套（RULE-AI-02 参数引导精神）
    if trigger not in _VALID_TRIGGERS:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[参数错误] 事实: trigger 收到非法值 '{trigger}'。\n"
                "原因: trigger 需为 periodic/milestone/anomaly/manual 之一。\n"
                "建议: 更正 trigger 后重试（如 trigger='manual'）。"
            ),
            tool_call_id="",
            tool_name="self_evaluate",
        )
    try:
        report = evaluator.evaluate(session_id=ctx.session_id, trigger=trigger)
    except Exception as exc:  # noqa: BLE001 — 评估异常如实降级（fail-open）
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[自我评估失败] 事实: 评估异常。原因: {exc}。建议: 稍后重试或检查数据源。",
            tool_call_id="",
            tool_name="self_evaluate",
        )
    audit("self_evaluate", {"eval_id": report.eval_id}, "success")
    lines = [f"[自我评估] {report.eval_id}（trigger={trigger}）"]
    for m in report.metrics:
        if m.value is None:
            lines.append(f"  {m.name}: N/A（{m.note}）")
        else:
            lines.append(f"  {m.name}: {m.value:.2f}（来源 {m.source}，样本 {m.sample_size}）")
    lines.append(f"评估已落盘: {report.eval_id}（可 search_records(kind=self_eval) 检索）。")
    lines.append(
        "提示: 如发现改进机会，可 submit_evolution 提交（evidence 引用本评估 ID "
        f"'eval:{report.eval_id}'）。"
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="\n".join(lines),
        tool_call_id="",
        tool_name="self_evaluate",
    )
