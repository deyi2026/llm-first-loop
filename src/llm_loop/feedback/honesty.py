"""如实反馈管道（design.md §2.1.3.7 机制六 / FR-HON 系列）.

统一收敛所有降级/标注/如实反馈构造（FR-HON-03 不静默降级）：
错误完整透传（FR-FBK-02）、压缩标注、记忆不可用标注、回答中断标注。

AI-first（T21）: 所有反馈消息统一"事实 + 原因 + 建议下一步"三件套格式，
AI 无需二次推理即可决策。
"""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource

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
    """
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
    """达最大轮数如实结束（已执行轨迹 + 说明）."""
    trace_str = "; ".join(trace[-10:]) if trace else "（无动作记录）"
    return Message(
        role="system",
        content=(
            f"[已达轮数上限] 事实: 已达到最大循环轮数。\n"
            f"原因: 已执行轨迹: {trace_str}。\n"
            f"建议: 请基于现有信息给出最终回答。"
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
