"""Task-context helper utilities.

Rule-first scope: this module may derive a factual recent-task anchor for durable
compaction/handoff records and keep legacy program-appendix rendering compatibility.
It does not classify task complexity or choose models.
"""

from __future__ import annotations

from llm_loop.core.injection_labels import (
    PROGRAM_APPENDIX_NOTICE,
    InjectionLayer,
    render_program_appendix,
)


# ── 任务锚点 ──
def build_task_anchor(sess) -> str:
    """从会话最近消息提取"当前任务目标 + 最近动作"（任务锚点）.

    用于压缩审计/hot-card 等 durable handoff 事实；不自动进入普通模型 prompt。
    fail-open: 提取失败返回空串。
    """
    try:
        if sess is None or not getattr(sess, "messages", None):
            return ""
        _last_user = ""
        _recent_tools: list[str] = []
        for m in reversed(sess.messages):
            role = getattr(m, "role", "")
            content = str(getattr(m, "content", "") or "")
            if (
                role == "user"
                and not _last_user
                and content
                and not content.startswith(PROGRAM_APPENDIX_NOTICE)
                and not (getattr(m, "metadata", None) or {}).get("program_origin", False)
            ):
                _last_user = content[:100]
            elif role == "tool" and content and len(_recent_tools) < 2:
                _recent_tools.append(content[:60].replace("\n", " "))
            if _last_user and len(_recent_tools) >= 2:
                break
        _parts = []
        if _last_user:
            _parts.append(f"当前任务: {_last_user}")
        if _recent_tools:
            _parts.append("最近动作: " + " | ".join(_recent_tools))
        return "\n".join(_parts)
    except Exception:  # noqa: BLE001 — fail-open
        return ""


# ── 注入统一包装 ──
# 兼容既有 import / err1210 身份复核；真实单一真相源在 core.injection_labels。
_INJECTION_PREFIX = PROGRAM_APPENDIX_NOTICE


def wrap_injection(
    content: str,
    anchor: str = "",
    *,
    layer: InjectionLayer | str | None = None,
    slot_kind: str = "",
) -> str:
    """统一渲染 program-origin appendix。

    用户原话不经本函数改写；资料/通知 appendix 获得唯一冲突仲裁声明与
    语义标签。程序恢复任务仅获得 [任务·程序恢复] 标签，不伪装成背景资料。
    """
    return render_program_appendix(
        content, layer=layer, slot_kind=slot_kind, anchor=anchor
    )
