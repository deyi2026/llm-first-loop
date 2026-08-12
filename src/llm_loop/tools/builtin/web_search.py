"""基础工具: 网络搜索（M48，2026-08-12，借鉴 AnySearch 结构化结果设计）.

无 JS 渲染环境下实测可行的免费通道：Bing HTML（主）/ 百度 HTML（备）双后端互为降级。
返回结构化结果（title/url/snippet/source），不返回网页清单原始 HTML。
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import quote_plus

import httpx

from llm_loop.core.message import ToolResult, ToolResultStatus

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _search_bing(query: str, limit: int, timeout: float) -> list[dict]:
    """Bing HTML 端（实测 302→cn.bing.com 跟随跳转后 200，h2>a 可解析）."""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={min(limit * 2, 30)}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    resp.raise_for_status()
    items = re.findall(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S | re.I)
    out = []
    for u, t in items:
        title = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if title and u.startswith("http"):
            out.append({"title": title, "url": u, "snippet": "", "source": "bing"})
        if len(out) >= limit:
            break
    return out


def _search_baidu(query: str, limit: int, timeout: float) -> list[dict]:
    """百度 HTML 端（兜底，跳转链接保留原样并如实标注）."""
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": _UA})
    resp.raise_for_status()
    items = re.findall(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S | re.I)
    out = []
    for u, t in items:
        title = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if title:
            out.append({"title": title, "url": u, "snippet": "", "source": "baidu(跳转链接)"})
        if len(out) >= limit:
            break
    return out


_BACKENDS = [("bing", _search_bing), ("baidu", _search_baidu)]


class WebSearchTool:
    name = "web_search"
    description = (
        "网络搜索，返回结构化结果列表（标题/URL/来源）。何时用: 查找信息、找网页线索、验证外部事实。"
        "何时不用: 已知确切 URL 时用 web_fetch 直接抓取；本地检索用 search_records/search_archive。"
        "失败对策: 后端被限流/超时会自动降级到备用后端并如实标注来源；全部失败如实返回原因。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "返回结果条数（默认 5，最大 10）"},
        },
        "required": ["query"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        limit = min(max(int(kwargs.get("limit", 5) or 5), 1), 10)
        if not query:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'query'（搜索关键词）",
                tool_call_id="",
                tool_name=self.name,
            )
        errors: list[str] = []
        for name, fn in _BACKENDS:
            try:
                results = fn(query, limit, self._timeout_s)
            except Exception as exc:  # noqa: BLE001 — 单后端失败降级下一后端，如实记录
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if results:
                lines = [f"[query] {query}  [backend] {name}  [count] {len(results)}"]
                for i, r in enumerate(results, 1):
                    lines.append(f"{i}. {r['title']}\n   {r['url']}  ({r['source']})")
                    if r["snippet"]:
                        lines.append(f"   {r['snippet']}")
                if errors:
                    lines.append(f"[降级记录] 前置后端失败: {'; '.join(errors)}")
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content="\n".join(lines),
                    tool_call_id="",
                    tool_name=self.name,
                )
            errors.append(f"{name}: 0 条结果")
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[搜索失败] 所有后端均不可用: {'; '.join(errors)}",
            tool_call_id="",
            tool_name=self.name,
        )
