"""submit_evolution 工具实现（M16 审计 FR-AUDIT-AI-14 拆分: corrections.py → tools_evolution.py）.

M16 审计（FR-AUDIT-AI-07）: submit_evolution 为纯建议通道（无 kind/actions 参数），
accepted 后的落地执行由 AI 经修正工具自主完成（RULE-AI-06 子规则 4）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

SUBMIT_EVOLUTION_TOOL_DEF: dict = {
    "name": "submit_evolution",
    "description": "提交架构演进建议（结构化落盘供人工审阅）。何时用: 通过 architecture_status/search_records/self_evaluate 发现架构改进机会时（如冗余工具/重复模式/效率建议）。注意: 涉安全边界/协议硬约束的建议仅提交等待人工决策，AI 不得自行执行。evidence 可引用评估 ID（格式 'eval:SE-...'，EVAL-05 双向溯源）。",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "建议内容（改进点 + 期望效果）",
            },
            "evidence": {
                "type": "string",
                "description": "证据（架构状态/检索结果/观察；可引用评估 ID 'eval:SE-...'）",
            },
            "impact_scope": {
                "type": "string",
                "description": "影响范围（文件/模块/行为）",
            },
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["content"],
    },
}


def run_submit_evolution(
    ctx: Any,
    audit: Any,
    args: dict,
    audit_dir: str | None = None,
) -> ToolResult:
    """submit_evolution: 提交架构演进建议（EVOLVE-02/03/04，纯建议通道）.

    audit: 审计落盘 callable（corrections._audit 注入，保持共用 self_correction_log）。
    audit_dir: 审计目录（M19 FIX-05: eval_id 存在性校验数据源，读取失败 fail-open 跳过）。
    """
    content = str(args.get("content", "")).strip()
    if not content:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 缺少必填参数 'content'（建议内容）",
            tool_call_id="",
            tool_name="submit_evolution",
        )
    if ctx.evolution_store is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[演进建议不可用] 事实: 演进建议存储未装配。原因: EVOLVE_ENABLED=0。建议: 检查配置。",
            tool_call_id="",
            tool_name="submit_evolution",
        )
    evidence = str(args.get("evidence", "")).strip()
    # EVAL-05: 解析 eval_id（evidence 引用 "eval:SE-..." 格式 → 双向溯源）
    eval_id = ""
    if evidence.startswith("eval:"):
        eval_id = evidence.split("eval:", 1)[1].strip()
    # M19 FIX-05: eval_id 存在性轻量校验（O(1) 行匹配；读取失败 fail-open 跳过，不阻断落盘）
    eval_hint = ""
    if eval_id and audit_dir:
        exists = _eval_id_exists(audit_dir, eval_id)
        if exists is False:
            eval_hint = (
                f"\n[提示] evidence 引用的评估 ID '{eval_id}' 未在 self_eval_log 中找到"
                "（可能拼写错误），建议核对 eval_id 或先调用 self_evaluate 生成。"
            )
    suggestion = ctx.evolution_store.submit(
        content=content,
        evidence=evidence,
        impact_scope=str(args.get("impact_scope", "")),
        priority=str(args.get("priority", "medium")),
        session_id=ctx.session_id,
        eval_id=eval_id,
    )
    # 边界判定（EVOLVE-03/04），回执按权限级别如实说明（EXEC-01，级别 0 保持现状语义）
    level = int(getattr(ctx, "evolve_local_exec", 0) or 0)
    if suggestion.requires_human:
        note = "涉安全边界/协议硬约束，需人工决策，AI 不得自行执行。"
    elif level == 0:
        note = "权限分级: 当前为仅建议模式（EVOLVE_LOCAL_EXEC=0），执行由人工审阅后决定。"
    elif level == 1:
        note = "权限分级: 白名单局部执行（EVOLVE_LOCAL_EXEC=1），人工采纳后自动执行白名单内范围。"
    else:
        note = "权限分级: 全面执行（EVOLVE_LOCAL_EXEC=2），人工采纳后自动执行（涉边界仍仅人工）。"
    audit("submit_evolution", {"id": suggestion.id}, "success")
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[演进建议已提交] id={suggestion.id} 状态={suggestion.status}。\n"
            f"{note}\n建议: {suggestion.content[:200]}\n"
            "下一步: 建议已进入审阅队列（pending_review），等待人工 `evolve-review <id> accepted|rejected` 审阅；"
            "期间可继续循环，或经 `search_records(kind=evolution)` 查询状态。"
            f"{eval_hint}"
        ),
        tool_call_id="",
        tool_name="submit_evolution",
    )


def _eval_id_exists(audit_dir: str, eval_id: str) -> bool | None:
    """轻量校验 eval_id 是否存在于 self_eval_log.jsonl（O(1) 行匹配，不加载全文件）.

    返回: True=存在 / False=不存在 / None=读取失败（fail-open 跳过校验，不阻断落盘）。
    """
    from pathlib import Path

    path = Path(audit_dir) / "self_eval_log.jsonl"
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if eval_id in line:
                    return True
        return False
    except OSError:
        return None  # fail-open: 读取失败跳过校验（DFX-REL-10）
