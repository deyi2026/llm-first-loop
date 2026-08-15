"""架构状态/检索类工具实现（M16 审计 FR-AUDIT-AI-14 拆分: corrections.py → tools_status.py）.

- architecture_status: LLM 拉取架构运行状态（通道一）
- search_archive / search_records: 统一检索（压缩档案 / 历史记录·记忆·档案）
"""

from __future__ import annotations

import json
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

_SEARCH_RECORDS_KIND_HINT = (
    "action_trace/exception_log/self_correction_log/declaration_check/"
    "memory/memory_extract/archive/selfheal/param_adjust/evolution/evolution_exec/"
    "self_eval/change_log/proc_versions/feishu_audit/experience/all"
)


def run_status(ctx: Any, status_provider: Any, args: dict) -> ToolResult:
    """architecture_status: 拉取架构状态快照（维度可按需裁剪）."""
    if status_provider is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[架构状态不可用] 架构自省未启用（SELF_INSPECTION_ENABLED=0）或状态提供器未装配。",
            tool_call_id="",
            tool_name="architecture_status",
        )
    dims = args.get("dimensions")
    snap = status_provider.snapshot(dimensions=dims)
    text = json.dumps(snap, ensure_ascii=False, indent=2)
    # M19 FIX-03: 8000 字符静默截断如实标注（标注拼接在截断段之后，保证标注可见）
    if len(text) > 8000:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=text[:8000]
            + "\n[快照截断] 超出 8000 字符部分未显示（可缩小 dimensions 精确查询，如仅查 architecture_config）。",
            tool_call_id="",
            tool_name="architecture_status",
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=text,
        tool_call_id="",
        tool_name="architecture_status",
    )


def current_session_id(ctx: Any) -> str:
    """当前会话（由循环注入；默认空则检索全部）.

    P0-5(2026-08-15): contextvar 优先——并发 run 期间按当前执行上下文定位
    本会话（ctx.session_id 为环境回退，跨会话并发时其值为最后写入者，不可信）。
    """
    try:
        from llm_loop.core.run_context import current_session_id as _sid_var

        sid = _sid_var.get()
        if sid:
            return sid
    except Exception:  # noqa: BLE001 — 上下文不可用回退 ctx 字段（零回归）
        pass
    return getattr(ctx, "session_id", "") or ""


def run_search_archive(ctx: Any, archive: Any, args: dict, session_id_fn: Any, summarizer: Any = None) -> ToolResult:
    """search_archive: 检索被压缩的历史/超长结果（T22）.

    R2: with_summary=true 时对命中条目生成 LLM 语义摘要（AI 按需触发，增加计费）。
    """
    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content='[参数错误] 事实: 缺少检索关键词。\n原因: query 为必填。\n建议: 提供关键词后重试（如 search_archive(query="文件名")）。',
            tool_call_id="",
            tool_name="search_archive",
        )
    if archive is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[压缩档案不可用] 事实: 压缩档案未装配。\n原因: ARCHIVE_ENABLED=0 或 ArchiveStore 未注入。\n建议: 检查配置后重试。",
            tool_call_id="",
            tool_name="search_archive",
        )
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 50))
    role = args.get("role") or None
    tool_name = args.get("tool_name") or None
    hits = archive.search(session_id_fn(), query, limit=limit, role=role, tool_name=tool_name)
    if not hits:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[search_archive] 未找到匹配 '{query}' 的压缩档案条目（不伪造结果）。",
            tool_call_id="",
            tool_name="search_archive",
        )
    with_summary = bool(args.get("with_summary", False))
    lines: list[str] = []
    for h in hits[:6]:
        ts = h.get("ts", "")
        role_h = h.get("role", "")
        src = h.get("tool_name") or h.get("source", "")
        header = f"[{ts}] {role_h}/{src}"
        if with_summary:
            content_preview = str(h.get("content_preview", ""))
            if summarizer is not None and content_preview:
                try:
                    result = summarizer.summarize(content_preview)
                    lines.append(
                        f"{header}: 摘要(source={result.source}): {result.summary}\n"
                        f"原文片段: {content_preview[:200]}"
                    )
                except Exception as exc:  # noqa: BLE001 — 如实反馈失败，不静默降级
                    lines.append(
                        f"{header}: [摘要失败: {exc}] 原文片段: {content_preview[:400]}"
                    )
            else:
                lines.append(
                    f"{header}: [摘要不可用] 原文片段: {content_preview[:400]}"
                )
        else:
            lines.append(
                f"{header}: {str(h.get('summary', ''))[:200]}"
            )
    if not with_summary:
        lines.append("原文片段: " + str(hits[0].get("content_preview", ""))[:400])
    content = "[search_archive] 命中 " + str(len(hits)) + " 条:\n" + "\n".join(lines[:6])
    # M19 FIX-02: 命中 > 展示数时如实标注（AI 请求 limit 却只见 6 条，需告知真实命中数）
    if len(hits) > 6:
        content += (
            f"\n[仅显示前 6 条] 共 {len(hits)} 条命中（limit={limit}）。"
            "可缩小 query 或提高 limit 精确检索。"
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="search_archive",
    )



def run_event_stream(search_fn: Any, args: dict) -> ToolResult:
    """event_stream: 统一事件流视图（EVO-20260814）."""
    if search_fn is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[事件流不可用] 事实: event_stream 未装配。\n原因: 检索实现未注入。\n建议: 检查配置后重试。",
            tool_call_id="",
            tool_name="event_stream",
        )
    streams = str(args.get("streams", "all")).strip() or "all"
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit") or 50)
    limit = max(1, min(limit, 200))
    since = str(args.get("since", "")).strip()
    try:
        result = search_fn.event_stream(streams=streams, query=query, limit=limit, since=since)
    except Exception as exc:  # noqa: BLE001 — 事件流读取失败如实回执
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[事件流读取失败] 事实: {exc}\n原因: 审计流读取异常。\n建议: 检查 audit_dir 后重试。",
            tool_call_id="",
            tool_name="event_stream",
        )
    if not result:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[event_stream] 无匹配事件（streams={streams}, query='{query}'）。不伪造视图。",
            tool_call_id="",
            tool_name="event_stream",
        )
    lines: list[str] = []
    for e in result:
        lines.append(f"[{e.get('ts', '')}] {e.get('stream', '?')}: {str(e.get('summary', ''))[:200]}")
    content = "[event_stream] 统一事件流 " + str(len(result)) + " 条（旧→新）:\n" + "\n".join(lines)
    if len(result) == limit:
        content += f"\n[已达 limit={limit} 上限] 如需更早事件可提高 limit 或加 since 过滤。"
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="event_stream",
    )


def run_search_records(ctx: Any, search_fn: Any, args: dict, session_id_fn: Any) -> ToolResult:
    """search_records: 统一检索运行记录/记忆/压缩档案（T23）."""
    if search_fn is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[统一检索不可用] 事实: search_records 未装配。\n原因: 检索实现未注入。\n建议: 检查配置后重试。",
            tool_call_id="",
            tool_name="search_records",
        )
    kind = str(args.get("kind", "all")).strip()
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 50))
    try:
        result = search_fn(kind=kind, query=query, limit=limit, session_id=session_id_fn())
    except ValueError as exc:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[参数错误] 事实: {exc}\n原因: kind 取值不合法。\n建议: 可选 {_SEARCH_RECORDS_KIND_HINT}。",
            tool_call_id="",
            tool_name="search_records",
        )
    if not result:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[search_records] 未找到匹配 '{query}' 的记录（不伪造结果）。",
            tool_call_id="",
            tool_name="search_records",
        )
    lines: list[str] = []
    for r in result[:limit]:
        lines.append(
            f"[{r.get('ts', '')}] {r.get('kind', kind)}: {str(r.get('summary', ''))[:200]}"
        )
    content = "[search_records] 命中 " + str(len(result)) + " 条:\n" + "\n".join(lines[:6])
    # M19 FIX-02: 命中 > 展示数时如实标注（真实命中数 len(result)，非截断后计数）
    if len(result) > 6:
        content += (
            f"\n[仅显示前 6 条] 共 {len(result)} 条命中（limit={limit}）。"
            "可缩小 query 或提高 limit 精确检索。"
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="search_records",
    )


def current_params(ctx: Any) -> dict:
    """当前生效参数（动态优先）."""
    if ctx.runtime is not None:
        return ctx.runtime.current()
    return dict(ctx.strategy)
