"""如实反馈管道（design.md §2.1.3.7 机制六 / FR-HON 系列）.

统一收敛所有降级/标注/如实反馈构造（FR-HON-03 不静默降级）：
错误完整透传（FR-FBK-02）、压缩标注、记忆不可用标注、回答中断标注。

AI-first（T21）: 所有反馈消息统一"事实 + 原因 + 建议下一步"三件套格式，
AI 无需二次推理即可决策。
"""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.errors import is_quota_error

# 统一标注常量（FR-HON-03: 任何兜底/降级带显式来源标注）
MEMORY_UNAVAILABLE = "[记忆不可用] 记忆服务异常，本次未注入记忆"
ANSWER_INTERRUPTED = "[回答中断] 回答生成不完整"
MAX_ITERATIONS_NOTE = "[已达轮数上限] 已达到最大循环轮数，已输出当前进展"


def compression_message(archived_count: int, archived_chars: int) -> Message:
    """上下文压缩时的如实标注（T22: 另存提取替代截断）.

    事实: 已压缩 N 条消息；原因: 上下文预算；建议: 可用 search_archive 检索找回。
    """
    return Message(
        role="system",
        content=(
            f"[上下文压缩] 事实: 已将最早的 {archived_count} 条消息（约 {archived_chars} 字符）"
            f"另存至压缩档案（含关键事实与完整原文）。\n"
            f"原因: 适配上下文预算。\n"
            f"建议: 如需找回被压缩的早期信息，可调用 search_archive 检索（信息未丢失）。"
        ),
        source=MessageSource.SYSTEM,
    )


def llm_error_text(error: Exception) -> str:
    """LLM 调用异常如实反馈文本（DFX-REL-02，不伪造回答，三件套）.

    M18 AA15: Message 版 llm_error_message 与 memory_unavailable_message 已删除
    （均无消费方——记忆故障走 _fault_feedback → program_error_message）；统一为 str 版
    供 loop.py LLM 异常出口直接作为 final_answer。

    EVO-20260812-fb50ab78: 识别 provider 配额耗尽（403 access_terminated_error 等）
    → 专门文案（本周期不可恢复，非配置/网络问题），避免泛化建议误导排查方向。
    """
    # 配额耗尽: 专门反馈（billing 周期用尽，换模型/检查配置均无用）
    if is_quota_error(error):  # type: ignore[arg-type]
        return (
            f"[LLM 调用异常] 事实: LLM 调用失败。\n"
            f"原因: {type(error).__name__}: {error}\n"
            f"建议: API 配额周期已用尽（billing quota exhausted），本周期内无法继续；"
            f"非网络/Key/模型配置问题。请等待配额刷新或升级套餐后重试；本次未能获得回答。"
        )
    return (
        f"[LLM 调用异常] 事实: LLM 调用失败。\n"
        f"原因: {type(error).__name__}: {error}\n"
        f"建议: 检查网络/Key/模型名配置后重试；本次未能获得回答。"
    )


def model_unavailable_text(model_ref: str, error: Exception) -> str:
    """模型不可用如实反馈（M50：模型不在注册表/凭据缺失，三件套）.

    供 loop.py 在 per-call 模型（Web 切换）解析失败时直接作为 final_answer，
    不静默降级到默认模型（对齐 PREFERENCE_1 如实反馈）。
    """
    return (
        f"[模型不可用] 事实: 模型 {model_ref} 不可用。\n"
        f"原因: {type(error).__name__}: {error}\n"
        f"建议: 请从可用模型目录中选择模型后重试（输入栏下方下拉 / /model 命令）。"
    )


def max_iterations_feedback(trace: list[str]) -> Message:
    """达最大轮数如实结束（已执行轨迹 + 说明 + 续做引导）."""
    trace_str = "; ".join(trace[-10:]) if trace else "（无动作记录）"
    return Message(
        role="system",
        content=(
            f"[已达轮数上限] 事实: 已达到最大循环轮数。\n"
            f"原因: 已执行轨迹: {trace_str}。\n"
            f"建议: 请基于现有信息给出最终回答；若任务尚未完成，请如实说明"
            f"已完成/未完成与下一步——用户可直接在同一会话继续发消息（历史保留，"
            f"循环会以新消息重新进入）；或用户调大 LLM_MAX_ITERATIONS 后重试。"
        ),
        source=MessageSource.SYSTEM,
    )


def max_iterations_decision_message(rounds: int, budget: int) -> Message:
    """[轮次决策请求] 轮数耗尽时注入一次的归因/续跑决策轮（2026-08-15 用户需求）.

    耗尽有两种典型情形，判断归 AI（RULE-AI-00，程序不自动续跑）：
    ① 工具使用错误/空转（参数错/选错工具/无效重试）→ 如实归因 + 正确做法 + 当前结论收尾；
    ② 正常任务推进但步骤多 → adjust_strategy 调大 max_iterations（≤500 硬上限）续跑。
    决策轮仅一次（per-session 标志）；AI 未调大且仍耗竭 → 回到罐装如实终止。
    """
    return Message(
        role="system",
        content=(
            f"[轮次决策请求] 事实: 已达轮数上限 {budget}（已执行 {rounds} 轮）。\n"
            f"原因: 轮数耗尽可能有两类成因——① 工具使用错误/空转（参数错误、选错工具、"
            f"无效重复重试）；② 任务正常推进但步骤较多、预算不足。\n"
            f"建议: 请先归因再行动——\n"
            f"- 若属 ① 工具使用错误：不要调大轮数。请在回答中如实归因（哪一步错、"
            f"正确做法是什么），并基于已有信息给出当前结论与未完成项。\n"
            f"- 若属 ② 正常推进：调用 adjust_strategy 将 max_iterations 调大"
            f"（白名单可调，硬上限 500）后继续完成任务；或压缩剩余步骤，"
            f"在最终回答中如实列出已完成/未完成与下一步。\n"
            f"程序不会自动续跑——是否继续由你判断。"
        ),
        source=MessageSource.SYSTEM,
    )


def max_iterations_warning_message(rounds: int, budget: int) -> Message:
    """[轮数预警] 轮数接近上限时注入一次（R10：如实告知事实，决策归 AI）.

    AI 可自主决定：继续按当前节奏收尾 / 调用 adjust_strategy 调大 max_iterations /
    直接给出最终回答。程序只提供事实，不强制任何选择。
    2026-08-18（DSH 009 ③）: 追加"拆分后台"引导——长任务重活应委托后台
    （execute_command 后台 job / dsh_task background / spawn_subagent / workflow 扇出），
    主循环只调度轮询，勿单循环硬跑（实证：12 实例逐个 execute_command → 40 轮耗尽）。
    """
    return Message(
        role="system",
        content=(
            f"[轮数预警] 事实: 本轮已执行 {rounds} 轮，接近轮数上限 {budget}。\n"
            f"原因: 任务所需工具调用较多时，剩余轮数可能不足以完成全部步骤。\n"
            f"建议: 若预计还需多轮工具调用，可调用 adjust_strategy 将 max_iterations "
            f"调大（白名单可调，上限 500）后继续；或压缩剩余步骤、优先完成关键动作，"
            f"在最终回答中如实说明未完成部分。\n"
            f"⚠️ 若任务含大量可并行/独立子步骤（多实例修复、批量处理等），优先拆分为"
            f"后台任务（execute_command run_in_background=true / dsh_task background / "
            f"workflow_run 扇出 / spawn_subagent 委派）再轮询汇总（job_output/结果通知）——"
            f"主循环只做调度，勿单循环逐个硬跑（易耗尽轮数且串行低效）。"
        ),
        source=MessageSource.SYSTEM,
    )


def stagnation_reminder_message(tool_name: str, streak: int) -> Message:
    """[停滞提醒] 连续相同指纹工具调用提醒（EVO-20260814-aab7eb0b P2，阈值 3）."""
    return Message(
        role="system",
        content=(
            f"[停滞提醒] 事实: 你已连续 {streak} 次以相同参数调用工具 {tool_name}。\n"
            f"原因: 重复调用不产生新信息，只会空耗轮数预算（max_iterations 硬边界）。\n"
            f"建议: 停止重复调用，基于已有回执给出回答；若信息确实不足，请换用不同参数或其他工具。"
        ),
        source=MessageSource.SYSTEM,
    )


def stagnation_feedback(tool_name: str, streak: int, trace: list[str]) -> Message:
    """[停滞熔断] 连续相同指纹工具调用熔断如实结束（EVO-20260814-aab7eb0b P2，阈值 5）."""
    trace_str = "; ".join(trace[-10:]) if trace else "（无动作记录）"
    return Message(
        role="system",
        content=(
            f"[停滞熔断] 事实: 已连续 {streak} 次以相同参数调用工具 {tool_name}，循环被程序如实终止。\n"
            f"原因: 重复调用无法产生新信息，继续执行只会耗尽轮数预算。已执行轨迹: {trace_str}。\n"
            f"建议: 基于已获得的信息给出最终回答；若确需继续，请明确说明还需要什么、换不同参数或不同工具。"
        ),
        source=MessageSource.SYSTEM,
    )


def architecture_report_message(fact: str, reason: str, suggestion: str) -> Message:
    """[架构上报] 推送式如实上报（design.md §2.1.4.3 通道二）.

    格式统一"事实 + 原因 + 建议下一步"三件套（AI-first 设计准则）。
    """
    return Message(
        role="system",
        content=f"[架构上报] 事实: {fact}\n原因: {reason}\n建议: {suggestion}",
        source=MessageSource.SYSTEM,
    )


def session_deleted_message(session_id: str) -> str:
    """会话删除成功如实反馈（T26）."""
    return f"[会话已删除] 事实: 会话 {session_id[:8]} 已删除。\n原因: 用户确认删除操作。\n建议: 如需继续可新建会话。"


def session_not_found_message(session_id: str) -> str:
    """会话不存在如实反馈（不静默创建新会话）."""
    return f"[会话不存在] 事实: 未找到会话 {session_id}。\n原因: 会话标识不存在或已删除。\n建议: 可用 list 查看现有会话，或新建会话。"


def session_archived_message(session_id: str, archived: bool) -> str:
    """归档/取消归档如实反馈."""
    verb = "已归档" if archived else "已取消归档"
    return f"[会话{verb}] 会话 {session_id[:8]} {verb}。归档仅从活跃列表隐藏，原始内容保留可检索。"


def program_error_message(
    component: str,
    error: Exception,
    classification=None,
    healable: bool | None = None,
    suggested_actions: tuple[str, ...] = (),
    budget_remaining: int | None = None,
) -> Message:
    """程序组件故障统一反馈（T39 基线 + M12 增强: 可修复行动建议）.

    M12 FR-AUTO-SELFHEAL-01/02: 按 FaultClassification 附加可修复行动建议与
    可自愈性类别（向后兼容：无分类信息时维持 T39 三件套语义）。
    """
    content = (
        f"[程序异常] 事实: 程序辅助组件 {component} 发生故障（{type(error).__name__}: {error}）。\n"
        f"原因: 该组件为辅助功能，非核心决策链路。\n"
    )
    # M12 增强: 可自愈性分类 + 可修复行动建议
    if classification is not None:
        content += f"可自愈性: {'可自愈' if healable is not False else '不可自愈'}（{classification.note}）\n"
        if suggested_actions:
            content += (
                f"可修复行动建议: 可调用修正工具 {' 或 '.join(suggested_actions)} 尝试修复。\n"
            )
        if budget_remaining is not None:
            content += (
                f"自愈预算剩余: {budget_remaining} 次（耗尽后将按'基于现有上下文继续'处理）。\n"
            )
    content += "建议: 若尝试修复无效，请基于现有上下文继续作答，或换用其他信息途径；程序会如实反馈，不会静默。"
    return Message(role="system", content=content, source=MessageSource.SYSTEM)


def overflow_feedback(
    exc: Exception,
    breakdown: dict | None = None,
    model_window: dict | None = None,
) -> str:
    """R4: overflow 如实反馈（不自动重试，决策权归 AI）.

    告知 AI: 错误事实 + 当前占用 + 模型窗口 + 可选动作（AI 自主选择）。
    程序不替 AI 压缩/重试（避免丢信息影响大模型决策）。
    """
    lines = [
        f"[上下文溢出] 事实: provider 返回 overflow 错误: {exc}",
        "原因: 当前上下文超过模型窗口上限。",
        "程序未自动压缩重试（避免丢信息影响你的决策），请自主选择:",
        "① search_archive(query=\"关键词\") 检索被压内容，确认关键信息是否在上下文",
        "② adjust_strategy(history_budget=更小值) 主动压缩历史",
        "③ switch_model(更大窗口模型) 切换模型",
        "④ 开新会话（旧会话历史已另存可经 search_archive 找回）",
    ]
    if breakdown:
        total = breakdown.get("total", {})
        lines.append(
            f"当前占用: {total.get('chars', 0)} 字符"
            f" / 预算 {breakdown.get('budget', 0)}"
            f"（比例 {breakdown.get('ratio', 'N/A')}）"
        )
    if model_window:
        lines.append(
            f"模型窗口: {model_window.get('label', '?')} context={model_window.get('context', '?')}"
        )
    return "\n".join(lines)
