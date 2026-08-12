"""基础工具 3: 网络抓取（design.md 模块 D / FR-TOOL-01）.

M48 增强（2026-08-12）：浏览器 UA 池（403 自动换 UA 重试）+ 正文提取降级链：
trafilatura → og:title/<p> 密度启发 → 去标签纯文本（原行为兜底，兼容文档页）。
设计借鉴 AnySearch（结构化/提取分离），实测解决头条 JS 壳、站点反爬 UA 拦截。
"""

from __future__ import annotations

import html as _html
import re

import httpx

from llm_loop.core.message import ToolResult, ToolResultStatus

# 真实浏览器 UA 池（实测：多数站点按 UA 反爬，首个失败换 UA 重试）
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
]

# 疑似 JS 壳/反爬页特征（正文提取失败时如实提示，不伪装成功）
_SHELL_HINTS = ("enable javascript", "需要允许", "_$jsvmprt", "browser check", "cf-chl")


def _extract_title(raw: str) -> str:
    """og:title 优先，其次 <title>."""
    for pat in (
        r'property="og:title"\s+content="([^"]{2,120})"',
        r'content="([^"]{2,120})"\s+property="og:title"',
        r"<title[^>]*>([^<]{2,120})</title>",
    ):
        m = re.search(pat, raw, re.I)
        if m:
            return _html.unescape(m.group(1)).strip()
    return ""


def _density_extract(raw: str) -> str:
    """容器/<p> 密度启发提取（实测对头条等 SSR 文章页有效）."""
    m = re.search(
        r'<div[^>]*class="[^"]*(?:article-content|article_content|rich-text|post_content)[^"]*"[^>]*>(.*?)</div>\s*<',
        raw,
        re.S | re.I,
    )
    if m:
        text = re.sub(r"<[^>]+>", "\n", m.group(1))
    else:
        ps = re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S | re.I)
        text = "\n".join(re.sub(r"<[^>]+>", "", p) for p in ps)
    text = _html.unescape(text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text


def _strip_tags(raw: str) -> str:
    """去标签纯文本兜底（保持旧行为，兼容纯文档页）."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_content(raw: str, url: str) -> tuple[str, str, str]:
    """正文提取降级链。返回 (method, title, text)."""
    title = _extract_title(raw)
    try:
        import trafilatura

        text = trafilatura.extract(raw, url=url, include_comments=False) or ""
        if len(text.strip()) >= 50:
            return ("trafilatura", title, text.strip())
    except Exception:  # noqa: BLE001 — 提取失败走降级链，不阻断
        pass
    text = _density_extract(raw)
    if len(text) >= 50:
        return ("density", title, text)
    return ("strip", title, _strip_tags(raw))


class WebFetchTool:
    name = "web_fetch"
    description = (
        "抓取网页/URL 并返回文本内容（含标题与正文提取）。何时用: 获取网页信息、读取在线文档、查询外部数据。"
        "何时不用: 本地文件用 read_file；需执行命令用 execute_command。失败对策: URL 无效/HTTP 错误/超时会如实返回原因，请核对 URL 后重试。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的完整 URL（http/https）"},
            "max_chars": {"type": "integer", "description": "返回内容最大字符数（默认 100000）"},
        },
        "required": ["url"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）."""
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)

    def _request(self, url: str) -> httpx.Response:
        """UA 池轮换请求：首个 UA 遇 403/418 自动换 UA 重试."""
        last_exc: Exception | None = None
        with httpx.Client(timeout=self._timeout_s, follow_redirects=True) as client:
            for i, ua in enumerate(_UA_POOL):
                try:
                    resp = client.get(url, headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
                except httpx.HTTPError as exc:
                    if i == 0:
                        raise  # 网络层错误如实抛出，换 UA 无意义
                    last_exc = exc
                    continue
                if resp.status_code in (403, 418, 429) and i + 1 < len(_UA_POOL):
                    continue  # 疑似 UA 反爬，换下一个 UA
                return resp
        if last_exc is not None:
            raise last_exc
        return resp  # type: ignore[possibly-undefined]

    def execute(self, **kwargs) -> ToolResult:
        url = str(kwargs.get("url", "")).strip()
        max_chars = int(kwargs.get("max_chars", 100000) or 100000)
        if not url:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'url'（要抓取的链接）",
                tool_call_id="",
                tool_name=self.name,
            )
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[URL 无效] '{url}' 不是有效的 http/https 链接。请提供完整 URL（如 https://example.com）。",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            resp = self._request(url)
        except httpx.TimeoutException:
            return ToolResult(
                status=ToolResultStatus.TIMEOUT,
                content=f"[抓取超时] {url} 超过 {self._timeout_s:.0f}s 未响应",
                tool_call_id="",
                tool_name=self.name,
            )
        except httpx.HTTPError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[抓取失败] {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )

        if resp.status_code >= 400:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[HTTP {resp.status_code}] {url} 返回错误状态: {resp.reason_phrase}（已轮换 {len(_UA_POOL)} 个 UA）",
                tool_call_id="",
                tool_name=self.name,
            )

        raw = resp.text
        method, title, text = _extract_content(raw, url)
        header = f"[title] {title}\n[source] {url}\n[extract] {method}\n\n" if title else ""
        lower = raw[:5000].lower()
        if method == "strip" and any(h in lower for h in _SHELL_HINTS) and len(text) < 300:
            header += (
                "[提示] 该页面疑似 JS 壳/反爬页，正文需浏览器渲染；"
                "可换 execute_command 用 curl+python 解析，或改用 web_search 找替代信源。\n\n"
            )
        if not text.strip():
            text = "（页面无文本内容）"
        body = header + text
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n…[内容超长，已截断，共 {len(body)} 字符]…"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=body,
            tool_call_id="",
            tool_name=self.name,
        )
