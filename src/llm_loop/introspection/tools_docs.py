"""search_docs 工具执行逻辑（docs/ 文档语义检索入口）.

对齐 tools_status.py 拆分模式：参数校验 → 调用检索实现 → 如实回执。
程序仅提供检索通道+如实反馈；检索决策归 AI 自主（RULE-AI-00）。
"""

from __future__ import annotations

from collections.abc import Callable

from llm_loop.core.message import ToolResult, ToolResultStatus

_DOC_TYPE_ENUM = [
    "assessment",
    "analysis",
    "design",
    "spec",
    "tasks",
    "reflection",
    "report",
    "issue",
    "changes",
    "index",
    "rules",
    "playbook",
    "milestone",
    "other",
]

SEARCH_DOCS_TOOL_DEF: dict = {
    "name": "search_docs",
    "description": (
        "检索 docs/ 项目文档（规则/评估/分析/设计/spec/反思/报告等 Markdown 文件），"
        "返回结构化条目（路径/标题/摘要/相关性）。"
        "何时用: 需要定位 docs/ 中相关文档而非全量加载时（如查规则约束/评估结论/设计方案/反思记录）。"
        "何时不用: 检索运行记录/记忆/档案用 search_records，检索压缩档案用 search_archive，"
        "读单个文件用 read_file。"
        "失败对策: 未命中/检索失败如实返回不伪造，请调整关键词或 doc_type 重试。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词（必填）",
            },
            "doc_type": {
                "type": "string",
                "enum": _DOC_TYPE_ENUM,
                "description": "文档类型过滤（可选，默认不过滤）",
            },
            "limit": {
                "type": "integer",
                "description": "最多返回条数（默认 10，上限 50）",
            },
        },
        "required": ["query"],
    },
}


def run_search_docs(
    docs_search_fn: Callable[..., list[dict]] | None,
    args: dict,
) -> ToolResult:
    """search_docs: 检索 docs/ 项目文档（对齐 run_search_records 模式）."""
    if docs_search_fn is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[search_docs 不可用] 事实: docs 检索未装配。\n"
                "原因: DocsSearcher 未注入或 docs/ 目录无效。\n"
                "建议: 检查配置后重试。"
            ),
            tool_call_id="",
            tool_name="search_docs",
        )
    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[参数错误] 事实: 缺少检索关键词。\n"
                "原因: query 为必填。\n"
                '建议: 提供关键词后重试（如 search_docs(query="优化")）。'
            ),
            tool_call_id="",
            tool_name="search_docs",
        )
    doc_type = str(args.get("doc_type", "")).strip()
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 50))
    try:
        result = docs_search_fn(query=query, doc_type=doc_type, limit=limit)
    except OSError as exc:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[程序异常] 事实: docs 检索 IO 异常: {exc}\n原因: 文件读写错误。\n建议: 检查 docs/ 目录权限后重试。",
            tool_call_id="",
            tool_name="search_docs",
        )
    if not result:
        return _no_hit_result(query, docs_search_fn)
    lines: list[str] = []
    for r in result[:6]:
        ts = r.get("ts", "")
        dt = r.get("doc_type", "")
        title = r.get("title", "")
        file = r.get("file", "")
        summary = str(r.get("summary", ""))[:200]
        lines.append(f"[{ts}] {dt}: {title} ({file})\n  {summary}")
    content = "[search_docs] 命中 " + str(len(result)) + " 条:\n" + "\n".join(lines)
    if len(result) > 6:
        content += (
            f"\n[仅显示前 6 条] 共 {len(result)} 条命中（limit={limit}）。"
            "可缩小 query 或提高 limit 精确检索。"
        )
    notes = [str(r["note"]) for r in result[:6] if r.get("note")]
    if notes:
        content += "\n[降级标注] " + "; ".join(notes)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="search_docs",
    )


def _no_hit_result(query: str, docs_search_fn: Callable[..., list[dict]] | None) -> ToolResult:
    """A4: search_docs 未命中 → 近 N 篇文档标题引导（明确标注"未命中 + 参考引导"）.

    recent 通道经 `docs_search_fn.recent_docs`（可选属性，未装配时回退
    既有"不伪造结果"文案，零回归）。recent 通道异常 → fail-open 回退既有文案。
    """
    fallback = f"[search_docs] 未找到匹配 '{query}' 的文档（不伪造结果）。"
    recent_fn = getattr(docs_search_fn, "recent_docs", None)
    if not callable(recent_fn):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=fallback,
            tool_call_id="",
            tool_name="search_docs",
        )
    try:
        recent = recent_fn(limit=5) or []
        if not isinstance(recent, list):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=fallback,
                tool_call_id="",
                tool_name="search_docs",
            )
    except Exception:  # noqa: BLE001 — recent 通道异常 fail-open 回退既有文案
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=fallback,
            tool_call_id="",
            tool_name="search_docs",
        )
    recent_entries: list[dict] = [
        r for r in recent if isinstance(r, dict)
    ]  # A4: recent 条目防御（元素非 dict 过滤，fail-open）
    titles = [r.get("title", "") for r in recent_entries[:5] if r.get("title")]
    if not titles:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=fallback,
            tool_call_id="",
            tool_name="search_docs",
        )
    guide = "\n".join(f"- {t}" for t in titles)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[search_docs] 未命中 '{query}'（不伪造结果）；"
            f"docs/ 最近文档参考引导：\n{guide}"
        ),
        tool_call_id="",
        tool_name="search_docs",
    )
