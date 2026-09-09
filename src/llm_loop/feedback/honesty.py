"""如实反馈管道（design.md §2.1.3.7 机制六 / FR-HON 系列）.

统一收敛所有降级/标注/如实反馈构造（FR-HON-03 不静默降级）：
错误完整透传（FR-FBK-02）、压缩标注、记忆不可用标注、回答中断标注。

LLM-first: 生产反馈优先承载可核验事实与原因；任务策略由 AI 决定。
历史程序提示前缀仍保留识别/清洗兼容，但退役生产者不留在运行代码中。
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

# Historical/program-origin feedback prefixes remain a compatibility/source
# recognition table. They authorize no new producer and inject no prompt text.
# Old sessions may still contain these frames; source/eligibility filtering needs
# to distinguish them from genuine model or user semantics.
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
    # 1210 is a provider request-structure rejection. Recovery may have had no
    # applicable tail-user transform, so the final receipt must not claim a retry
    # happened and must not prescribe a next action.
    if _is_err1210(error):
        return (
            f"[LLM 调用异常] 事实: provider 拒绝了本次请求（HTTP 400/code 1210）。\n"
            f"原因: {type(error).__name__}: {error}\n"
            f"边界: 该错误码属于 provider 请求结构校验；本次未能获得模型回答。"
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


def stagnation_feedback(
    tool_name: str, streak: int, trace: list[str], *, has_evidence: bool = True
) -> Message:
    """[停滞熔断] 连续相同指纹工具调用熔断如实结束（EVO-20260814-aab7eb0b P2，阈值 5）.

    GPT 审计批次4（P2 evidence-validity gate）: 无成功回执（无有效证据）时不得暗示
    "基于已获得的信息"可作答——改报 unresolved 需 replan，禁止推测性结论。
    """
    trace_str = "; ".join(trace[-10:]) if trace else "（无动作记录）"
    if has_evidence:
        advice = (
            "建议: 基于已获得的信息给出最终回答；若确需继续，请明确说明还需要什么、"
            "换不同参数或不同工具。"
        )
    else:
        advice = (
            "建议: 本 run 尚未获得任何成功的工具回执（无有效证据），不能基于已有信息作答——"
            "请如实向用户报告任务未解决（unresolved），说明已尝试路径与失败原因，"
            "并提出 replan 方向（换工具/换参数/换路径或补充外部输入）；禁止给出推测性结论。"
        )
    return Message(
        role="system",
        content=(
            f"[停滞熔断] 事实: 已连续 {streak} 次以相同参数调用工具 {tool_name}，循环被程序如实终止。\n"
            f"原因: 重复调用无法产生新信息，继续执行只会耗尽轮数预算。已执行轨迹: {trace_str}。\n"
            + advice
        ),
        source=MessageSource.SYSTEM,
    )


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
