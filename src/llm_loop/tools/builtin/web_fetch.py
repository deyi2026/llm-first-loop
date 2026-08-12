"""基础工具 3: 网络抓取（design.md 模块 D / FR-TOOL-01）.

M48 增强（2026-08-12）：浏览器 UA 池（403 自动换 UA 重试）+ 正文提取降级链：
trafilatura → og:title/<p> 密度启发 → 去标签纯文本（原行为兜底，兼容文档页）。
设计借鉴 AnySearch（结构化/提取分离），实测解决头条 JS 壳、站点反爬 UA 拦截。
M48-B curl 回退：httpx 被 TLS 指纹拦截（ConnectError/Reset）或仅取到 JS 壳时，
自动回退 curl 子进程（argv 无 shell 注入面）按 UA 池重试——实测唯一能穿透头条的路径。
"""

from __future__ import annotations

import html as _html
import re
import subprocess
import time as _time

import httpx

from llm_loop.core.message import ToolResult, ToolResultStatus

# 单例 Browser 借鉴（既有实现 read_preview）: 短时重复抓取同一 URL 感知。
# 模块级 {url: last_fetch_epoch}——同会话内 5 分钟内重复抓同一 URL，
# 回执头部提示可复用上次结果（网页动态变化才重抓），避免浪费 token。
_fetch_history: dict[str, float] = {}
_FETCH_REUSE_WINDOW_S = 300  # 5 分钟内重复抓取提示复用

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


def _embedded_json_extract(raw: str) -> str:
    """SPA 内嵌 JSON 提取（M49）: Next.js __NEXT_DATA__ / Nuxt __NUXT__ / ld+json /
    __INITIAL_STATE__ —— 正文常藏在 HTML 内嵌数据里，trafilatura 抓不到时兜底.

    策略: 逐类提取 JSON → 递归收集字符串值（跳过 key/短碎片）→ 拼接正文。
    返回 "" 表示无有效内容（降级链继续）。
    """
    import json

    # 候选 JSON 块: (正则, 是否需 json.loads 校验)
    patterns = [
        (r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', True),
        (r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', True),
        (r'window\.__NUXT__\s*=\s*(.*?)</script>', False),
        (r'window\.__INITIAL_STATE__\s*=\s*(.*?)</script>', False),
    ]
    texts: list[str] = []
    for pat, need_json in patterns:
        for m in re.finditer(pat, raw, re.S | re.I):
            blob = m.group(1).strip()
            if not blob:
                continue
            data = None
            if need_json:
                try:
                    data = json.loads(blob)
                except Exception:  # noqa: BLE001
                    continue
            if data is None:
                # __NUXT__/__INITIAL_STATE__ 是 JS 对象，尝试 JSON 化后提取
                try:
                    import json5  # type: ignore[import-not-found]
                except Exception:  # noqa: BLE001
                    try:
                        # 无 json5 时: 只提取可见字符串字面量（保守）
                        strs = re.findall(r'"((?:[^"\\]|\\.){40,})"', blob)
                        texts.extend(x for x in strs if len(x) > 40)
                        continue
                    except Exception:  # noqa: BLE001
                        continue
                try:
                    data = json5.loads(blob)
                except Exception:  # noqa: BLE001
                    continue
            texts.extend(_collect_json_strings(data))
    # 去重保序 + 过滤噪声（排除纯 URL/图片链接/短碎片）
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        t = _html.unescape(t).strip()
        if len(t) < 40 or t in seen:
            continue
        if re.fullmatch(r"https?://\S+|\S+\.(?:png|jpe?g|svg|webp|gif|ico)", t, re.I):
            continue
        seen.add(t)
        out.append(t)
    return "\n\n".join(out)


def _collect_json_strings(data) -> list[str]:
    """递归收集 JSON 中的长字符串值（正文候选，跳过 key 与短碎片）."""
    out: list[str] = []
    if isinstance(data, str):
        if len(data) >= 40:
            out.append(data)
    elif isinstance(data, dict):
        for v in data.values():
            out.extend(_collect_json_strings(v))
    elif isinstance(data, list):
        for v in data:
            out.extend(_collect_json_strings(v))
    return out


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
    text = _embedded_json_extract(raw)
    if len(text) >= 50:
        return ("embedded_json", title, text)
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
            "start": {"type": "integer", "description": "分页续读起始偏移（字符，默认 0）。正文超长被截断后，用 start=上次位置 续读下一段"},
            "count": {"type": "integer", "description": "分页续读每段长度（字符，默认 max_chars）。start 与 count 正交：start 定起点、count 定段长（借鉴 既有实现 read_preview 'start 与 count 的分页续读'）"},
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

    def _curl_fetch(self, url: str) -> tuple[str, str] | None:
        """curl 回退通道（httpx 被 TLS 指纹拦截/JS 壳时）.

        argv 列表传参无 shell 注入面；按 UA 池逐个尝试，返回首个"非 JS 壳且
        正文提取达标"的 (extract_method, raw_html)。全部失败如实返回 None。
        """
        for ua in _UA_POOL:
            try:
                proc = subprocess.run(  # noqa: S603 — 固定 argv、URL 已校验协议
                    ["curl", "-sL", "-m", str(int(self._timeout_s)), "-A", ua,
                     "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8", "--", url],
                    capture_output=True,
                    timeout=self._timeout_s + 5,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError):
                continue
            if proc.returncode != 0 or not proc.stdout:
                continue
            raw = proc.stdout.decode("utf-8", errors="ignore")
            method, _title, text = _extract_content(raw, url)
            lower = raw[:5000].lower()
            is_shell = any(h in lower for h in _SHELL_HINTS) and len(text) < 300
            if not is_shell and len(text.strip()) >= 20:
                return (method, raw)
        return None

    def execute(self, **kwargs) -> ToolResult:
        url = str(kwargs.get("url", "")).strip()
        max_chars = int(kwargs.get("max_chars", 100000) or 100000)
        start = int(kwargs.get("start", 0) or 0)
        if start < 0:
            start = 0
        count = int(kwargs.get("count", 0) or 0)
        if count <= 0:
            count = max_chars  # count 未指定 → 段长 = max_chars
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
        # 单例感知: 短时重复抓取同一 URL → 提示可复用（既有实现 单例 Browser 精神）
        now = _time.time()
        reuse_note = ""
        last_fetch = _fetch_history.get(url)
        if last_fetch is not None and now - last_fetch < _FETCH_REUSE_WINDOW_S:
            reuse_note = (
                f"[重复抓取] 该 URL 于 {int(now - last_fetch)} 秒前抓取过"
                "（单例精神: 可考虑复用上次结果，网页动态变化才重抓）\n"
            )
        httpx_note = ""
        try:
            resp = self._request(url)
        except httpx.TimeoutException:
            resp = None
            httpx_note = f"httpx 超时（{self._timeout_s:.0f}s）"
        except httpx.HTTPError as exc:
            resp = None
            httpx_note = f"httpx {type(exc).__name__}: {exc}"

        if resp is not None and resp.status_code >= 400:
            httpx_note = f"httpx HTTP {resp.status_code}（已轮换 {len(_UA_POOL)} 个 UA）"
            resp = None

        curl_used = False
        if resp is not None:
            raw = resp.text
            method, title, text = _extract_content(raw, url)
            lower = raw[:5000].lower()
            if method == "strip" and any(h in lower for h in _SHELL_HINTS) and len(text) < 300:
                # JS 壳：尝试 curl 回退（实测头条等站点 curl 可穿透）
                httpx_note = "httpx 仅取到 JS 壳"
                resp = None
            else:
                method_out = method

        if resp is None:
            fallback = self._curl_fetch(url)
            if fallback is None:
                status = ToolResultStatus.TIMEOUT if "超时" in httpx_note else ToolResultStatus.FAILURE
                return ToolResult(
                    status=status,
                    content=f"[抓取失败] {url}：{httpx_note}；curl 回退亦失败（已轮换 {len(_UA_POOL)} 个 UA）。"
                    "可换 execute_command 手动排查，或改用 web_search 找替代信源。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            curl_used = True
            method_out, raw = fallback
            method, title, text = _extract_content(raw, url)

        header = f"[title] {title}\n[source] {url}\n[extract] {method_out}\n" if title else ""
        if curl_used:
            header += f"[fetch] curl 回退（{httpx_note}）\n"
        header += reuse_note  # 单例感知提示（无重复则为空）
        header += "\n"
        _fetch_history[url] = now  # 记录本次抓取（成功才记，失败不记）
        if not text.strip():
            text = "（页面无文本内容）"
        body = header + text
        total = len(body)
        if start > 0:
            # 分页续读（既有实现 read_preview 借鉴：start 与 count 正交）
            # start 定起点、count 定段长；返回 [start, start+count) 段
            body = body[start:start + count]
            if not body:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[分页越界] start={start} 超过正文总长 {total}（已抓全，无更多内容）",
                    tool_call_id="",
                    tool_name=self.name,
                )
            seg_note = f"\n…[分页 {start}-{start+len(body)}/{total}，续读；可用 start={start+len(body)} 继续]…"
            if len(body) >= count:
                body = body + seg_note
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=body,
                tool_call_id="",
                tool_name=self.name,
            )
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n…[内容超长，已截断，共 {len(body)} 字符；可用 start={max_chars} 续读]…"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=body,
            tool_call_id="",
            tool_name=self.name,
        )
