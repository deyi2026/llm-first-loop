"""基础工具 3: 网络抓取（design.md 模块 D / FR-TOOL-01）."""

from __future__ import annotations

import httpx

from llm_loop.core.message import ToolResult, ToolResultStatus


class WebFetchTool:
    name = "web_fetch"
    description = (
        "抓取网页/URL 并返回文本内容。何时用: 获取网页信息、读取在线文档、查询外部数据。"
        "何时不用: 本地文件用 read_file；需执行命令用 execute_command。"
        "失败对策: URL 无效/HTTP 错误/超时会如实返回原因，请核对 URL 后重试。"
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
            with httpx.Client(timeout=self._timeout_s, follow_redirects=True) as client:
                resp = client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; llm-first-loop/0.1)"},
                )
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
                content=f"[HTTP {resp.status_code}] {url} 返回错误状态: {resp.reason_phrase}",
                tool_call_id="",
                tool_name=self.name,
            )

        text = resp.text
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n…[内容超长，已截断，共 {len(resp.text)} 字符]…"
        if not text.strip():
            text = "（页面无文本内容）"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=text,
            tool_call_id="",
            tool_name=self.name,
        )
