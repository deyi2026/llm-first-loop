"""handoff Skill — 上下文压力自动检测 + 一键交接（EVO-20260813-62791501）.

Codex 风格 handoff 增强：在上下文压力高（context_usage > 70%）时主动建议交接，
或用户显式触发 handoff_now 生成结构化交接文档（含未完成任务/关键决策/记忆/下一步）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

logger = logging.getLogger(__name__)

HANDOFF_TOOL_DEF: dict = {
    "name": "handoff_now",
    "description": "生成结构化交接文档（handoff.md），新会话可无缝接管当前进度。何时用: 上下文压力高（context_usage > 70%）时主动触发；任务跨多会话需要交接；显式长期任务存档。何时不用: 任务简单无需交接；当前会话未开始工作。失败对策: 无关键状态时返回空提示，不伪造交接内容。状态契约: 交接文档落盘本地文件（路径在回执中给出），上下文压缩/新会话后仍可凭文件接管——长任务关键进度建议同时落盘项目文件而非仅依赖交接文档。",
    "parameters": {
        "type": "object",
        "properties": {
            "urgency": {"type": "string", "enum": ["low", "medium", "high"], "description": "紧急程度（low=总结 / medium=立即交接 / high=紧急交接）"},
            "include_decisions": {"type": "boolean", "description": "是否包含关键决策记录（默认 true）"},
            "include_memory": {"type": "boolean", "description": "是否包含记忆指针（默认 true）"},
        },
    },
}

_PRESSURE_WARN_THRESHOLD = 0.70
_PRESSURE_HIGH_THRESHOLD = 0.85

_HANDOFF_TPL = """# 📨 Handoff 文档（生成于 {timestamp}）

> 紧急程度: **{urgency}** | 上下文压力: **{pressure:.0%}**

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


def _calc_pressure(ctx: Any) -> float:
    """计算上下文压力（0-1）."""
    # 简化估算：基于消息数 + 工具调用数
    if not ctx:
        return 0.0
    try:
        msg_count = float(getattr(ctx, "message_count", 0) or 0)
        tool_count = float(getattr(ctx, "tool_call_count", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    # 假设 100 消息 + 50 工具调用 = 满载
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


def _next_steps(urgency: str, pressure: float) -> str:
    """下一步建议（按紧急程度生成）."""
    lines = [f"1. 紧急度: **{urgency}**（上下文压力 {pressure:.0%}）"]
    if pressure >= _PRESSURE_HIGH_THRESHOLD:
        lines.append("2. ⚠️ **必须立即交接**——继续追加消息将丢失早期上下文")
    elif pressure >= _PRESSURE_WARN_THRESHOLD:
        lines.append("2. ⚠️ 建议交接——避免核心上下文被压缩")
    else:
        lines.append("2. 可继续当前会话（压力尚可）")
    lines.append("3. 新会话读取 handoff.md 后，调用 `architecture_status` 验证状态")
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
        session_id = getattr(ctx, "session_id", "") or ""
        archive.archive(
            session_id,
            role="system",
            source="handoff",
            content=doc,
            tool_name="handoff_now",
        )
    except Exception as exc:  # noqa: BLE001 fail-open
        logger.warning("handoff 归档失败（fail-open）: %s", exc)


def run_handoff_now(ctx: Any, audit: Any, args: dict) -> ToolResult:
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

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    doc = _HANDOFF_TPL.format(
        timestamp=timestamp,
        urgency=urgency,
        pressure=pressure,
        tasks_section=_tasks_section(ctx),
        decisions_section=_decisions_section(ctx, include_dec),
        memory_section=_memory_section(include_mem),
        next_steps=_next_steps(urgency, pressure),
    )

    # 写入压缩档案目录
    archive_dir = Path("data/compressed_archive") / f"handoff_{timestamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = archive_dir / "handoff.md"
    handoff_path.write_text(doc, encoding="utf-8")

    # EVO-20260813-4b49a822: 同步归档到当前会话 ArchiveStore（使 search_archive 天然可检索）
    _archive_handoff(ctx, doc)


    summary = (
        f"# 📨 交接文档已生成\n\n"
        f"- **路径**: `data/compressed_archive/handoff_{timestamp}/handoff.md`\n"
        f"- **紧急度**: {urgency}\n"
        f"- **上下文压力**: {pressure:.0%}\n"
        f"- **建议**: {('⚠️ 立即交接' if pressure >= _PRESSURE_HIGH_THRESHOLD else ('⚠️ 建议交接' if pressure >= _PRESSURE_WARN_THRESHOLD else '可继续'))}\n\n"
        f"## 📄 文档预览\n\n```markdown\n{doc[:1500]}\n```\n"
    )

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=summary,
        tool_call_id="",
        tool_name="handoff_now",
    )
