"""会话状态快照文本构造（R9-P3-01 步1/3：自 core/loop/engine.py 纯 move）.

模块级纯函数、零 llm_loop import（纯 stdlib 字符串构造）——环①断裂的落位模块，
engine/build 双方可指本模块而不构成新环（Tarjan 单向边）。
"""


def build_session_snapshot_text(
    message_count: int, memory_count: int, evolution_summary: dict | None = None
) -> str:
    """会话状态快照文本（EVO-20260811-9ccdec97）: 客观指标 + 定位校准引导.

    作为 system 消息注入，帮助 AI 在长会话中保有"我在哪、要去哪"的定位锚点；
    客观指标取实时值，语义部分（当前任务/下一步）由 AI 以本条为锚点自行校准。
    """
    parts = [f"[会话状态快照] 消息 {message_count} 条；记忆 {memory_count} 条"]
    if evolution_summary:
        parts.append(
            "演进待办: "
            + ", ".join(
                f"{k}={v}"
                for k, v in evolution_summary.items()
                if k in ("pending_review", "executed", "executing")
            )
        )
    parts.append("若你对当前任务/已完成/下一步/未决事项的定位漂移，以本条为锚点重新校准。")
    return "；".join(parts)
