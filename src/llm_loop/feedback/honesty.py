"""如实反馈管道（design.md §2.1.3.7 机制六 / FR-HON 系列）.

统一收敛所有降级/标注/如实反馈构造（FR-HON-03 不静默降级）：
错误完整透传（FR-FBK-02）、压缩标注、记忆不可用标注、回答中断标注。

AI-first（T21）: 所有反馈消息统一"事实 + 原因 + 建议下一步"三件套格式，
AI 无需二次推理即可决策。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

from llm_loop.core.injection_labels import (
    PROGRAM_RECOVERY_LABEL,
    STATUS_LABEL,
    InjectionLayer,
    origin_metadata,
    render_program_appendix,
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.errors import (
    LLMEmptyResponseError,
    LLMHTTPError,
    is_quota_error,
    parse_provider_error_code,
)

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
            f"[上下文压缩] 已将最早的 {archived_count} 条消息（约 {archived_chars} 字符）"
            "完整另存；旧正文未自动内联。\n"
            "ref=archive:search_archive"
        ),
        source=MessageSource.SYSTEM,
    )


# P0-B（2026-08-28 用户批准，specs/err1210_locating/P0-B-program-feedback-separation.md）:
# 程序反馈前缀清单——engine 收尾 source 判定 + memory extractor 过滤共用（单一真相源）。
# 覆盖: 错误/熔断/守卫/耗尽/压缩提醒等程序生成文本；pressure_block/routing refusal
# 等动态文案未覆盖（漏标时 source 保持 USER，行为与现状一致，不劣化）。
PROGRAM_FEEDBACK_PREFIXES = (
    STATUS_LABEL,
    PROGRAM_RECOVERY_LABEL,
    "[LLM 调用异常]",
    "[已达轮数上限]",
    "[停滞熔断]",
    "[停滞提醒]",
    "[缓存守卫拦截]",
    "[上下文超限]",
    "[上下文压缩]",
    "[搜索空结果提醒]",
    "[程序异常]",
    "（已停止——",
)


def _is_err1210(exc: Exception) -> bool:
    """口径对齐 core/loop/err1210.is_err1210（LLMHTTPError + status 400 + provider code 1210）.

    本地复用底层原语（llm/errors.py）实现，避免 feedback 模块拉入
    core.loop.err1210 重依赖链（feedback 被 memory/engine 广泛引用，防未来环）。
    """
    return (
        isinstance(exc, LLMHTTPError)
        and exc.status_code == 400
        and parse_provider_error_code(exc.body or "") == "1210"
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
    # 1210 结构性触发（err1210_locating 已定位: 会话尾部连续多条 user 消息触发
    # provider 结构校验，与内容无关）: 定向文案——非网络/Key/模型名问题；
    # 到达本出口时 err1210.recovery 降级（剥离注入/尾部聚合）已尝试且未恢复。
    if _is_err1210(error):
        return (
            f"[LLM 调用异常] 事实: LLM 调用失败。\n"
            f"原因: {type(error).__name__}: {error}\n"
            f"建议: 该错误码为结构性触发（会话尾部连续多条 user 消息触发 provider 校验），"
            f"非网络/Key/模型名问题；系统已自动尝试降级重试（剥离注入/尾部聚合）未恢复。"
            f"请直接重发本轮（下一轮上下文重建后通常自愈）；本次未能获得回答。"
        )
    # EVO-20260818-92bd97d6: 空响应专门文案（流被截断/模型抖动，重试可自愈）
    if isinstance(error, LLMEmptyResponseError):
        return (
            f"[LLM 调用异常] 事实: 模型返回空响应（无内容且无工具调用）。\n"
            f"原因: {type(error).__name__}: {error}\n"
            f"建议: 多为瞬态抖动（流被截断/模型异常），请直接重试；"
            f"本次未能获得回答。"
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
    """达最大轮数如实结束（R8.24-B B-D6 收口：纯事实终态，建议段已删除）.

    事实 = 已达轮数上限 N 轮 + 已执行轨迹；"用户可继续"为事实级提示
    （衔接 E 包 task_active 授权恢复）。§11.1 修订：不再注入建议性自然语言。
    """
    trace_str = "; ".join(trace[-10:]) if trace else "（无动作记录）"
    return Message(
        role="system",
        content=(
            f"[已达轮数上限] 事实: 已达到最大循环轮数。\n"
            f"原因: 已执行轨迹: {trace_str}。\n"
            f"用户可在同一会话继续发送消息（历史保留，循环以新消息重新进入）。"
        ),
        source=MessageSource.SYSTEM,
    )


def max_iterations_decision_message(rounds: int, budget: int) -> Message:  # noqa: ARG001
    """[轮次决策请求] —— R8.24-B B-D6 已退役（deprecated，无生产调用点）.

    到达轮数硬限不再花第 N+1 轮 LLM 调用问模型"是否继续"——硬边界直接
    结束/暂停 + UI 提示（B-G4: 第 N+1 轮 LLM call=0）。保留函数体仅供
    历史参照与测试反例自证；生产路径禁止调用（静态断言：
    tests/unit/test_runtime_zero_prompt_static.py）。
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


def max_iterations_warning_message(rounds: int, budget: int) -> Message:  # noqa: ARG001
    """[轮数预警] —— R8.24-B B-D6 已退役（deprecated，无生产调用点）.

    轮数预警注入取消（模型可见面零预警，B-G8）；到达硬限直接结束。
    保留函数体仅供历史参照与测试反例自证；生产路径禁止调用。
    """
    return Message(
        role="system",
        content=(
            f"[轮数预警] 事实: 本轮已执行 {rounds} 轮，接近轮数上限 {budget}。\n"
            f"原因: 任务所需工具调用较多时，剩余轮数可能不足以完成全部步骤。\n"
            f"建议: 若预计还需多轮工具调用，可调用 adjust_strategy 将 max_iterations "
            f"调大（白名单可调，上限 500）后继续；或压缩剩余步骤、优先完成关键动作，"
            f"在最终回答中如实说明未完成部分。"
        ),
        source=MessageSource.SYSTEM,
    )


def stagnation_reminder_message(tool_name: str, streak: int) -> Message:  # noqa: ARG001
    """[停滞提醒] —— R8.24-B B-D3 已退役（deprecated，无生产调用点）.

    停滞提醒 prompt 注入取消（总审计 §11.3 撤销判定）；计数/阈值/熔断保留，
    提醒改道事件观测（tool_exec._track_stagnation）。保留函数体仅供历史
    参照与测试反例自证；生产路径禁止调用。
    """
    return Message(
        role="system",
        content=(
            f"[停滞提醒] 事实: 你已连续 {streak} 次以相同参数调用工具 {tool_name}。\n"
            f"原因: 重复调用不产生新信息，只会空耗轮数预算（max_iterations 硬边界）。\n"
            f"建议: 停止重复调用，基于已有回执给出回答；若信息确实不足，请换用不同参数或其他工具。"
        ),
        source=MessageSource.SYSTEM,
    )


def empty_search_reminder_message(tool_name: str, streak: int) -> Message:  # noqa: ARG001
    """[搜索空结果提醒] —— R8.24-B B-D4 已退役（deprecated，无生产调用点）.

    空搜索建议层删除（真实空结果回执已是事实）；否定帧登记保留。
    保留函数体仅供历史参照与测试反例自证；生产路径禁止调用。
    """
    return Message(
        role="system",
        content=(
            f"[搜索空结果提醒] 事实: 搜索类工具 {tool_name} 已连续 {streak} 次返回空结果。\n"
            f"原因: 目标可能不存在、或搜索前提（记忆/路径）与实际不符——重复换参数搜同一目标不会产生新信息。\n"
            f"建议: 以工具回执为准：目标不存在即停止该目标搜索，标注'记忆待修正'，如实说明并询问用户；"
            f"确需继续请换全新目标或改向用户求证。"
        ),
        source=MessageSource.SYSTEM,
    )


def stagnation_feedback(
    tool_name: str, streak: int, trace: list[str], *, has_evidence: bool = True  # noqa: ARG001
) -> Message:
    """[停滞熔断] 熔断如实终止（R8.24-B B-D3 收口：纯事实终态）.

    B-D3: "三路径替代策略"建议文案取消（search_evidence 换路/get_tool_schema
    复核/基于回执作答——全部删除）；结束原因以 run 终态元数据/事实呈现：
    stagnation、连续 N 次、ref 各不相同。has_evidence 仅作事实区分
    （无成功回执时如实说明 unresolved，不给建议性指令——GPT 审计批次4
    证据有效性门的事实面保留）。
    """
    trace_str = "; ".join(trace[-10:]) if trace else "（无动作记录）"
    evidence_fact = (
        "本 run 已有成功的工具回执（历史回执可经检索复用）。"
        if has_evidence
        else "本 run 尚未获得任何成功的工具回执（无有效证据），任务未解决（unresolved）。"
    )
    return Message(
        role="system",
        content=(
            f"[停滞熔断] 事实: 已连续 {streak} 次以相同参数调用工具 {tool_name}，循环被程序如实终止。\n"
            f"原因: 重复调用无法产生新信息，继续执行只会耗尽轮数预算。已执行轨迹: {trace_str}。\n"
            f"{evidence_fact}"
        ),
        source=MessageSource.SYSTEM,
    )


def architecture_report_message(fact: str, reason: str, suggestion: str) -> Message:
    """[架构上报] 推送式如实上报（design.md §2.1.4.3 通道二）.

    格式统一"事实 + 原因 + 建议下一步"三件套（AI-first 设计准则）。
    """
    return Message(
        role="system",
        content=render_program_appendix(
            f"[架构上报] 事实: {fact}\n原因: {reason}\n建议: {suggestion}",
            InjectionLayer.STATUS,
        ),
        source=MessageSource.SYSTEM,
        metadata=origin_metadata(
            InjectionLayer.STATUS,
            injection_kind="architecture_report",
            injected_system=True,
        ),
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
    breakdown: dict | None = None,  # noqa: ARG001
    model_window: dict | None = None,  # noqa: ARG001
) -> str:
    """R4 → R8.24-B B-D5 已退役（deprecated，无生产调用点）.

    E17 overflow 改 runtime 确定性处理（compact/route/end + telemetry），
    模型可见面零 overflow 教程、零"继续/压缩"询问（B-G1 E17 分量）。
    保留函数体仅供历史参照与测试反例自证；生产路径禁止调用
    （静态断言: tests/unit/test_runtime_zero_prompt_static.py）。
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


_FEEDBACK_FALLBACK_LOCK = threading.Lock()
_feedback_logger = logging.getLogger(__name__)


@contextmanager
def _feedback_lock(path: Path):
    """feedback.jsonl stable cross-process lock; lock acquisition failure is fatal."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        import fcntl
    except ImportError:
        with _FEEDBACK_FALLBACK_LOCK:
            yield
        return

    lock_file = None
    try:
        lock_file = lock_path.open("a", encoding="utf-8")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    except OSError:
        if lock_file is not None:
            lock_file.close()
        raise
    try:
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            _feedback_logger.warning("feedback lock release failed: %s", lock_path, exc_info=True)
        finally:
            lock_file.close()


def _feedback_fsync_parent(path: Path) -> None:
    """Best-effort directory fsync; file fsync remains mandatory."""
    fd: int | None = None
    try:
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(fd)
    except OSError as exc:
        _feedback_logger.warning(
            "feedback parent fsync unavailable (write completed, durability degraded): %s: %s",
            path.parent,
            exc,
        )
    finally:
        if fd is not None:
            os.close(fd)


def append_feedback(path: str | Path, record: dict) -> None:
    """Append one feedback record under the same stable lock used by physical purge."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False) + "\n"
    with _feedback_lock(target):
        created = not target.exists()
        with target.open("a", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        if created:
            _feedback_fsync_parent(target)


def delete_feedback_for_session(path: str | Path, session_id: str) -> int:
    """Physically remove exact-session feedback records; malformed rows fail closed."""
    target = Path(path)
    if not target.exists():
        return 0
    with _feedback_lock(target):
        if not target.exists():
            return 0
        kept: list[str] = []
        removed = 0
        for line_no, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"feedback.jsonl line {line_no} is corrupt; cannot determine session ownership"
                ) from exc
            if str(entry.get("session_id", "")) == session_id:
                removed += 1
            else:
                kept.append(raw)
        if removed == 0:
            return 0
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                if kept:
                    f.write("\n".join(kept) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            _feedback_fsync_parent(target)
        finally:
            with suppress(OSError):
                tmp.unlink(missing_ok=True)
        return removed
