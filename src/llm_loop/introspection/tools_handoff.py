"""handoff Skill — 上下文压力自动检测 + 一键交接（EVO-20260813-62791501）.

Codex 风格 handoff 增强：在上下文压力高（context_usage > 70%）时主动建议交接，
或用户显式触发 handoff_now 生成结构化交接文档（含未完成任务/关键决策/记忆/下一步）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

HANDOFF_TOOL_DEF: dict = {
    "name": "handoff_now",
    "description": "生成结构化交接文档；用户明确要求开新会话继续时请同时传 create_new_session=true 并直接报告新会话链接，无需再次检索全部日志。何时用: 上下文压力高（context_usage > 70%）时主动触发；任务跨多会话需要交接；显式长期任务存档。何时不用: 任务简单无需交接；当前会话未开始工作。失败对策: 无关键状态时返回空提示，不伪造交接内容。状态契约: 交接文档落盘本地文件（路径在回执中给出），上下文压缩/新会话后仍可凭文件接管——长任务关键进度建议同时落盘项目文件而非仅依赖交接文档。",
    "parameters": {
        "type": "object",
        "properties": {
            "urgency": {"type": "string", "enum": ["low", "medium", "high"], "description": "紧急程度（low=总结 / medium=立即交接 / high=紧急交接）"},
            "include_decisions": {"type": "boolean", "description": "是否包含关键决策记录（默认 true）"},
            "include_memory": {"type": "boolean", "description": "是否包含记忆指针（默认 true）"},
            "create_new_session": {"type": "boolean", "description": "仅用户明确要求开新会话继续时为 true；创建独立空历史会话并返回精确链接，不继承事件/工具历史，默认 false"},
        },
    },
}

_PRESSURE_WARN_THRESHOLD = 0.70
_PRESSURE_HIGH_THRESHOLD = 0.85

_HANDOFF_TPL = """# 📨 Handoff 文档（生成于 {timestamp}）

> 紧急程度: **{urgency}** | 上下文压力: **{pressure_text}**

## 📋 未完成任务
{tasks_section}

## 🎯 关键决策
{decisions_section}

## 💡 记忆指针
{memory_section}

## ➡️ 下一步建议
{next_steps}

---

## 🔧 使用方式

1. **新会话** 开头执行：
   ```bash
   search_archive query="handoff_<timestamp>" with_summary=true
   ```
2. AI 会读取本 handoff.md + 关联记忆，自动恢复上下文
3. 继续未完成任务（按"下一步建议"排序）
4. 完成后调用 `evolve-complete` 关闭本交接

## ⚠️ 注意事项

- 本交接是**只读快照**（不修改原状态）
- 高紧急程度会自动通知监听会话（飞书主动出站场景）
- handoff.md 永久保存在压缩档案（可在 search_archive 检索）
"""


def _calc_pressure(ctx: Any) -> float | None:
    """计算上下文压力（0-1）."""
    # 简化估算：基于消息数 + 工具调用数
    if not ctx:
        return None
    try:
        msg_count = float(getattr(ctx, "message_count", 0) or 0)
        tool_count = float(getattr(ctx, "tool_call_count", 0) or 0)
    except (TypeError, ValueError):
        return None
    if msg_count <= 0 and tool_count <= 0:
        # Context is not wired to the real provider token meter. Do not call it 0%.
        return None
    # Legacy count-derived estimate, not actual provider context occupation.
    used = msg_count * 0.01 + tool_count * 0.005
    return min(1.0, max(0.0, used))


def _tasks_section(ctx: Any) -> str:
    """未完成任务列表（从 ctx 提取）."""
    tasks = getattr(ctx, "pending_tasks", []) if ctx else []
    if not tasks:
        return "（无未完成任务，或 ctx 未注入 pending_tasks）"
    lines = []
    for i, t in enumerate(tasks, 1):
        lines.append(f"{i}. {t}")
    return "\n".join(lines)


def _decisions_section(ctx: Any, include: bool) -> str:
    """关键决策（来自 search_records kind=memory）."""
    if not include:
        return "_已跳过_"
    decisions = getattr(ctx, "recent_decisions", []) if ctx else []
    if not decisions:
        return "（无最近决策，或 ctx 未注入 recent_decisions）"
    return "\n".join(f"- {d}" for d in decisions[-10:])


def _memory_section(include: bool) -> str:
    """记忆指针（指向 [[memory]] 标签）。"""
    if not include:
        return "_已跳过_"
    return "新会话开始时执行 `search_records kind=memory` 检索最近记忆条目"


def _next_steps(urgency: str, pressure: float | None) -> str:
    """下一步建议（按紧急程度生成；EVO-20260824-3cd4d74b: 恢复先验证外部状态再依赖）."""
    pressure_text = f"估算 {pressure:.0%}" if pressure is not None else "未知（未提供实际 token 数据）"
    lines = [f"1. 紧急度: **{urgency}**（上下文压力 {pressure_text}）"]
    if pressure is not None and pressure >= _PRESSURE_HIGH_THRESHOLD:
        lines.append("2. ⚠️ **必须立即交接**——继续追加消息将丢失早期上下文")
    elif pressure is not None and pressure >= _PRESSURE_WARN_THRESHOLD:
        lines.append("2. ⚠️ 建议交接——避免核心上下文被压缩")
    else:
        lines.append("2. 无法仅凭当前统计判断上下文压力；用户要求交接时应直接执行")
    lines.append("3. 新会话读取 handoff.md 后，先验证外部状态再依赖内容（RULE-AI-12）：")
    lines.append("   ① `architecture_status` 验证引擎状态；② git status 核对 worktree 改动归属；")
    lines.append("   ③ 关键文件 mtime 确认无意外变更；④ 演进建议状态（pending_review/accepted/executing）")
    lines.append("4. 继续未完成任务清单")
    return "\n".join(lines)




def _archive_handoff(ctx: Any, doc: str) -> None:
    """将交接文档归档到当前会话 ArchiveStore（fail-open，零回归）.

    EVO-20260813-4b49a822: handoff.md 只写普通文件时 search_archive 检索不到
    （search_archive 仅检索 ArchiveStore 条目），导致新会话恢复路径断裂。
    此处同步归档为档案条目（role=system, source=handoff），使交接物天然可检索。
    """
    try:
        archive = getattr(ctx, "archive", None)
        if archive is None:
            return
        from llm_loop.introspection.tools_status import bound_session_id

        session_id = bound_session_id()
        if not session_id:
            return
        archive.archive(
            session_id,
            role="system",
            source="handoff",
            content=doc,
            tool_name="handoff_now",
        )
    except Exception as exc:  # noqa: BLE001 fail-open
        logger.warning("handoff 归档失败（fail-open）: %s", exc)


def run_handoff_now(
    ctx: Any, audit: Any, args: dict, *,
    session_store: Any | None = None, audit_dir: str | Path | None = None,
) -> ToolResult:
    """handoff_now: 生成结构化交接文档."""
    urgency = str(args.get("urgency", "medium")).strip() or "medium"
    if urgency not in {"low", "medium", "high"}:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[参数错误] 事实: urgency 收到非法值 '{urgency}'。原因: 需为 low/medium/high。建议: 提供正确紧急程度。",
            tool_call_id="", tool_name="handoff_now",
        )

    pressure = _calc_pressure(ctx)
    include_dec = bool(args.get("include_decisions", True))
    include_mem = bool(args.get("include_memory", True))

    # Strong binding: shared ctx.session_id is unsafe across concurrent sessions.
    from llm_loop.introspection.tools_status import bound_session_id

    sid = bound_session_id()
    snapshot = None
    if session_store is not None and sid and audit_dir is not None:
        try:
            from llm_loop.introspection.session_handoff import build_handoff_snapshot

            if session_store.exists(sid):
                snapshot = build_handoff_snapshot(session_store.load(sid), audit_dir=audit_dir)
        except Exception as exc:
            logger.warning("handoff 事实快照读取失败: %s", exc)

    created = None
    if args.get("create_new_session", False) is True:
        if session_store is None or not sid or audit_dir is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[交接拒绝] 无当前 run 可信会话绑定或 SessionStore，未创建新会话。",
                tool_call_id="", tool_name="handoff_now",
            )
        try:
            from llm_loop.introspection.session_handoff import create_handoff_session

            created = create_handoff_session(session_store, sid, audit_dir=audit_dir)
        except Exception as exc:
            logger.warning("handoff 新会话创建失败: %s", exc)
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[交接失败] 新会话未成功创建：{type(exc).__name__}",
                tool_call_id="", tool_name="handoff_now",
            )

    timestamp = system_local_now().strftime("%Y%m%d-%H%M%S")
    doc = _HANDOFF_TPL.format(
        timestamp=timestamp,
        urgency=urgency,
        pressure_text=(
            f"估算 {pressure:.0%}" if pressure is not None
            else "未知（无实际 token 数据，不能显示为 0%）"
        ),
        tasks_section=(
            snapshot["continuation_prompt"] if snapshot is not None
            else _tasks_section(ctx)
        ),
        decisions_section=(
            "_已跳过_" if not include_dec else
            "以最近用户原始指令和 Goal Checkpoint 的事实为准，详见上述来源快照。"
            if snapshot is not None else _decisions_section(ctx, include_dec)
        ),
        memory_section=_memory_section(include_mem),
        next_steps=_next_steps(urgency, pressure),
    )

    # 附加文档属于可选审计副本。它写失败时绝不能隐藏已成功创建的
    # 新 session id（否则人类重试会产生多个孤儿接力会话）。
    archive_dir = (
        (Path(audit_dir).parent if audit_dir is not None else Path("data"))
        / "compressed_archive" / f"handoff_{timestamp}"
    )
    handoff_path = archive_dir / "handoff.md"
    artifact_error = ""
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(doc, encoding="utf-8")
    except OSError as exc:
        artifact_error = type(exc).__name__
        logger.warning("handoff 辅助文档写入失败（保留已创建会话）: %s", exc)
    else:
        _archive_handoff(ctx, doc)
    if artifact_error and created is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[交接失败] 交接文档写入失败：{artifact_error}；未创建新会话。",
            tool_call_id="", tool_name="handoff_now",
        )

    summary = (
        f"# 📨 交接快照已生成\n\n"
        f"- **文档**: {str(handoff_path) if not artifact_error else '写入失败（保留新会话）'}\n"
        f"- **紧急度**: {urgency}\n"
        f"- **上下文压力**: {('估算 ' + format(pressure, '.0%')) if pressure is not None else '未知（无实际 token 用量）'}\n"
        f"- **建议**: {('用户要求立即交接' if urgency == 'high' else '根据用户要求执行')}\n\n"
        f"## 📄 快照预览\n\n\x60\x60\x60markdown\n{doc[:1500]}\n\x60\x60\x60\n"
    )

    if created is not None:
        summary += (
            f"\n## 新会话已创建（空历史，无事件复制）\n"
            f"- new_session_id: {created['new_session_id']}\n"
            f"- source_session_id: {created['source_session_id']}\n"
            f"- 入口: /ui/v2/?session={created['new_session_id']}\n"
            f"- 新会话接力草稿已持久化，可直接打开上方入口后发送继续。\n"
            f"- 本轮应直接告知用户新会话入口，不要继续旧任务查证。\n"
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=summary,
        tool_call_id="",
        tool_name="handoff_now",
    )
