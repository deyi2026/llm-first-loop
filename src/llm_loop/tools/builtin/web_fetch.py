"""基础工具 3: 网络抓取（design.md 模块 D / FR-TOOL-01）.

M48 增强（2026-08-12）：浏览器 UA 池（403 自动换 UA 重试）+ 正文提取降级链：
trafilatura → og:title/<p> 密度启发 → 去标签纯文本（原行为兜底，兼容文档页）。
设计借鉴 AnySearch（结构化/提取分离），实测解决头条 JS 壳、站点反爬 UA 拦截。
M48-B curl 回退：httpx 被 TLS 指纹拦截（ConnectError/Reset）或仅取到 JS 壳时，
自动回退 curl 子进程（argv 无 shell 注入面）按 UA 池重试——实测唯一能穿透头条的路径。

P0-2/P0-3（2026-08-15，审计发现 #1/#2 修复）SSRF 深化：
- 重定向不再自动跟随（httpx follow_redirects / curl -L 均关闭），改手动循环：
  每一跳重新做内网校验（含 DNS 解析），上限 5 跳如实报错（防跳云元数据泄凭证）。
- DNS rebinding TOCTOU 收窄（混合方案）：curl 通道 --resolve 钉住已校验 IP
  （预连接钉扎，SNI/证书校验不受损）；httpx 通道连接后读取实际对端 IP 复核，
  命中私网即丢弃连接。如实标注 httpx 残余：GET 请求已发出，此处防数据回读；
  需更强隔离的场景依赖 curl 钉 IP 通道。
"""

from __future__ import annotations

import html as _html
import ipaddress
import logging
import re
import subprocess
import time as _time

import httpx

from llm_loop.core.message import ToolResult, ToolResultStatus

logger = logging.getLogger(__name__)

# 单例 Browser 感知: 短时重复抓取同一 URL 提示复用。
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


# ── HARNESS-03: SSRF 内网拦截（默认开；WEB_FETCH_BLOCK_PRIVATE=0 关闭）──
_BLOCK_PRIVATE_DEFAULT = "1"

# 2026-08-15 现场修复：198.18.0.0/15 为 RFC 2544 基准测试段，也是 Surge/Clash fake-ip 模式的
# 默认假地址段（代理 DNS 把目标域名解析成 198.18.x.x）。Python is_private 将其判为私网，
# 导致代理环境下所有外网抓取被 SSRF 误杀（既有测试被迫 WEB_FETCH_BLOCK_PRIVATE=0 绕过）。
# 默认策略：全部解析地址均落在该段（代理假 IP）→ 放行 + 回执如实标注（真实连接由代理通道
# 完成，对端为真实公网地址）；WEB_FETCH_BLOCK_FAKE_IP=1 恢复严格拦截。真实私网/回环/
# 链路本地/保留段拦截语义不变（P0 不回归）。
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _strict_fake_ip() -> bool:
    """WEB_FETCH_BLOCK_FAKE_IP 解析（默认 0=放行假 IP；1=严格拦截）."""
    import os

    raw = os.environ.get("WEB_FETCH_BLOCK_FAKE_IP", "0").strip().lower()
    return raw in {"1", "on", "true", "yes"}


def _block_private_enabled() -> bool:
    """WEB_FETCH_BLOCK_PRIVATE 解析（默认 1=开启；0/off/false 关闭）."""
    import os

    raw = os.environ.get("WEB_FETCH_BLOCK_PRIVATE", _BLOCK_PRIVATE_DEFAULT).strip().lower()
    return raw not in {"0", "off", "false", "no"}


def _blocked_ip_label(ip_str: str) -> str:
    """单个 IP 字符串的私网/保留命中说明（未命中返回空串）."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        kind = "私网" if ip.is_private else "回环" if ip.is_loopback else "链路本地" if ip.is_link_local else "保留地址"
        return f"{ip_str}（{kind}）"
    return ""


def _resolve_checked_ips(url: str) -> tuple[str, list[str], str, int, bool]:
    """解析 URL 主机并校验全部地址 → (命中原因, 已校验 IP 列表, host, port, 假IP放行标志).

    任一地址命中真实私网即整域拦截（防一半公网一半内网的解析漂移）；
    全部地址命中 198.18/15 代理假 IP 段（且非严格模式）→ 放行，第 5 元置 True（回执如实标注）；
    混合解析（假 IP + 真实私网）→ 真实私网拦截语义不变。
    解析失败 fail-open（返回空列表，请求阶段如实报网络错误）。
    """
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return ("host 为空", [], "", 0, False)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        candidates: list[str] = []
        try:
            ip = ipaddress.ip_address(host)
            candidates = [str(ip)]
        except ValueError:
            try:
                infos = socket.getaddrinfo(host, None)
                candidates = [str(info[4][0]) for info in infos]
            except socket.gaierror:
                return ("", [], host, port, False)  # 解析失败 fail-open（请求阶段如实报错）
        fake_hits = 0
        for cand in candidates:
            if ipaddress.ip_address(cand) in _FAKE_IP_NETWORK:
                if _strict_fake_ip():
                    return (f"{cand}（代理假 IP 段 198.18/15，严格模式拦截）", [], host, port, False)
                fake_hits += 1
                continue
            label = _blocked_ip_label(cand)
            if label:
                return (label, [], host, port, False)
        if candidates and fake_hits == len(candidates):
            # 全部为代理假 IP（Surge/Clash fake-ip 模式）→ 放行（真实连接由代理通道完成）
            return ("", candidates, host, port, True)
        return ("", candidates, host, port, False)
    except Exception:  # noqa: BLE001 — 判定失败 fail-open（不阻断正常请求）
        return ("", [], "", 0, False)


def _blocked_private_url(url: str) -> str:
    """URL 目标是否命中私网/保留地址段；返回命中说明（未命中返回空串）.

    检查链路: host 为 IP 字面量直接判定；域名经 getaddrinfo 解析后逐地址判定
    （任一地址命中即拦截——DNS rebinding 面收窄；198.18/15 代理假 IP 段默认放行）。
    解析失败 fail-open 放行（域名解析失败后续请求会如实报网络错误）。
    """
    return _resolve_checked_ips(url)[0]


class _PrivateTargetBlockedError(Exception):
    """P0-2: 重定向/连接后校验命中私网目标（execute 捕获转 BLOCKED 回执）."""


class _RedirectLimitExceededError(Exception):
    """P0-2: 重定向超过上限（防无限循环/资源耗尽，如实报错）."""


_MAX_REDIRECT_HOPS = 5


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
            "count": {"type": "integer", "description": "分页续读每段长度（字符，默认 max_chars）。start 与 count 正交：start 定起点、count 定段长（分页续读语义）"},
        },
        "required": ["url"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）."""
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)

    def _request(self, url: str) -> httpx.Response:
        """httpx 通道：手动重定向循环（P0-2：每跳重新内网校验，上限 5 跳）.

        修复前 follow_redirects=True 自动跟随——公开 URL 302 跳内网即 SSRF 泄漏。
        """
        from urllib.parse import urljoin

        current = url
        for _hop in range(_MAX_REDIRECT_HOPS + 1):
            if _block_private_enabled():
                blocked = _blocked_private_url(current)
                if blocked:
                    raise _PrivateTargetBlockedError(f"{current} → {blocked}")
            resp = self._request_once(current)
            if 300 <= resp.status_code < 400:
                loc = resp.headers.get("location", "")
                if not loc:
                    return resp  # 无 Location 的 3xx 如实返回（由上层按 HTTP 错误处理）
                current = urljoin(current, loc)
                continue
            return resp
        raise _RedirectLimitExceededError(f"重定向超过 {_MAX_REDIRECT_HOPS} 跳")

    def _request_once(self, url: str) -> httpx.Response:
        """单跳请求：UA 池轮换（403/418/429 换 UA）+ 连接后对端 IP 复核（P0-3）."""
        last_exc: Exception | None = None
        with httpx.Client(timeout=self._timeout_s) as client:  # follow_redirects 关闭（手动循环）
            for i, ua in enumerate(_UA_POOL):
                try:
                    with client.stream(
                        "GET", url,
                        headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                    ) as resp:
                        self._verify_peer(resp, url)  # P0-3: 实际对端命中私网 → 丢弃
                        if resp.status_code in (403, 418, 429) and i + 1 < len(_UA_POOL):
                            continue  # 疑似 UA 反爬，换下一个 UA
                        if not (300 <= resp.status_code < 400):
                            resp.read()  # 非重定向才读体（重定向跳读体浪费带宽）
                        return resp
                except httpx.HTTPError as exc:
                    if i == 0:
                        raise  # 网络层错误如实抛出，换 UA 无意义
                    last_exc = exc
                    continue
        if last_exc is not None:
            raise last_exc
        raise httpx.HTTPError("UA 池耗尽未取得响应")  # 理论不可达（首 UA 网络错即抛出）

    @staticmethod
    def _verify_peer(resp: httpx.Response, url: str) -> None:
        """P0-3: 连接后对端 IP 复核（DNS rebinding TOCTOU 收窄）.

        如实标注：GET 请求已发出，此处防的是数据回读（丢弃连接不读体）；
        预连接钉扎在 curl 通道（--resolve）。扩展缺失/已释放 → 跳过（fail-open
        保可用性，初始 URL 的预解析校验仍在前置把关）。
        """
        if not _block_private_enabled():
            return
        stream = resp.extensions.get("network_stream")
        if stream is None:
            return
        try:
            addr = stream.get_extra_info("server_addr")
        except Exception:  # noqa: BLE001 — 取不到对端地址跳过复核
            return
        if not addr:
            return
        peer = str(addr[0])
        # 2026-08-15: TUN/增强模式（Surge pf 重定向）下实际对端可能是——
        # ① 代理假 IP（198.18/15）：放行（非严格模式），真实连接由代理通道完成；
        # ② 本机回环（透明代理监听 127.0.0.1:port，如 Surge 6152 / Clash 7890）：
        #    per-hop 预检查已把关目标（直连 127.0.0.1 的 URL 在预检查即拦截），
        #    对端回环仅可能来自系统级透明转发 → 放行（logger 留痕）。
        #    残余如实标注：同跳内 DNS rebinding 至回环的窗口极小（需攻击者 DNS 控制
        #    + 同跳换 IP），且真实私网对端（10.x/172.16/192.168/169.254 等）仍丢弃，
        #    P0-2/P0-3 主体防护不变。
        # 真实私网对端仍丢弃（P0-3 语义不变）。
        try:
            peer_ip = ipaddress.ip_address(peer)
            if peer_ip in _FAKE_IP_NETWORK and not _strict_fake_ip():
                return
            if peer_ip.is_loopback:
                logger.info("web_fetch 对端为本机回环 %s（透明代理转发，已放行）: %s", peer, url)
                return
        except ValueError:
            pass  # 非 IP 字面量（域名字符串）→ 走 _blocked_ip_label 常规判定
        label = _blocked_ip_label(peer)
        if label:
            raise _PrivateTargetBlockedError(f"{url} 实际连接对端命中内网: {label}")

    def _curl_fetch(self, url: str) -> tuple[str, str] | None:
        """curl 回退通道（httpx 被 TLS 指纹拦截/JS 壳时）.

        P0-2/P0-3：不再用 -L 自动跟随，改手动重定向循环（每跳内网校验，上限 5 跳）；
        域名 URL 经 --resolve 钉住已校验 IP（预连接钉扎，防 TOCTOU 二次解析漂移，
        SNI/证书校验不受损）。argv 列表传参无 shell 注入面；按 UA 池逐个尝试，
        返回首个"非 JS 壳且正文提取达标"的 (extract_method, raw_html)。全部失败
        如实返回 None。
        """
        from urllib.parse import urljoin

        current = url
        for _hop in range(_MAX_REDIRECT_HOPS + 1):
            resolve: str | None = None
            if _block_private_enabled():
                reason, ips, host, port, _fake = _resolve_checked_ips(current)
                if reason:
                    raise _PrivateTargetBlockedError(f"{current} → {reason}")
                if ips and host:
                    resolve = f"{host}:{port}:{','.join(ips[:3])}"  # 钉已校验 IP（前 3 个）
            hop = self._curl_hop(current, resolve)
            if hop is None:
                return None
            if hop[0] == "redirect":
                if not hop[1]:
                    return None  # 3xx 无 Location 如实失败
                current = urljoin(current, hop[1])
                continue
            return (hop[1], hop[2])
        raise _RedirectLimitExceededError(f"重定向超过 {_MAX_REDIRECT_HOPS} 跳")

    def _curl_hop(self, url: str, resolve: str | None) -> tuple | None:
        """单跳 curl：返回 ("ok", method, raw) / ("redirect", location) / None."""
        for ua in _UA_POOL:
            r = self._curl_once(url, ua, resolve)
            if r is None:
                continue
            code, redirect, raw = r
            if 300 <= code < 400:
                return ("redirect", redirect)
            if code >= 400 or not raw.strip():
                continue  # 错误页/反爬 → 换 UA
            method, _title, text = _extract_content(raw, url)
            lower = raw[:5000].lower()
            is_shell = any(h in lower for h in _SHELL_HINTS) and len(text) < 300
            if not is_shell and len(text.strip()) >= 20:
                return ("ok", method, raw)
        return None

    def _curl_once(self, url: str, ua: str, resolve: str | None) -> tuple[int, str, str] | None:
        """单次 curl（不跟随重定向）→ (http_code, redirect_url, body)；失败 None.

        -w 尾部追加 "\\n%{http_code} %{redirect_url}" 供手动重定向循环判定。
        """
        args = [
            "curl", "-s", "-m", str(int(self._timeout_s)), "-A", ua,
            "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
            "-w", "\n%{http_code} %{redirect_url}",
        ]
        if resolve:
            args += ["--resolve", resolve]  # P0-3: 预连接钉已校验 IP
        args += ["--", url]
        try:
            proc = subprocess.run(  # noqa: S603 — 固定 argv、URL 已校验协议
                args,
                capture_output=True,
                timeout=self._timeout_s + 5,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0 or not proc.stdout:
            return None
        text = proc.stdout.decode("utf-8", errors="ignore")
        body, sep, trailer = text.rpartition("\n")
        if not sep:
            return None
        parts = trailer.strip().split(" ", 1)
        try:
            code = int(parts[0])
        except (ValueError, IndexError):
            return None
        redirect = parts[1].strip() if len(parts) > 1 else ""
        return (code, redirect, body)

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
        # HARNESS-03(2026-08-14): 内网拦截（SSRF 防护）——web_fetch 默认拦截私网/链路本地/
        # 回环/保留地址（含云元数据 169.254.169.254），防 Agent 被诱导访问内网服务。
        # WEB_FETCH_BLOCK_PRIVATE=0 可关闭（本地开发需要访问内网时）。
        # 2026-08-15: 198.18/15 代理假 IP 段（Surge/Clash fake-ip）默认放行 + 如实标注。
        fake_ip_note = ""
        if _block_private_enabled():
            block_label, _, _, _, fake_ip = _resolve_checked_ips(url)
            if block_label:
                return ToolResult(
                    status=ToolResultStatus.BLOCKED,
                    content=(
                        f"[内网拦截] 目标地址属于私网/保留地址段（{block_label}），已拒绝访问（SSRF 防护）。\n"
                        f"原因: web_fetch 默认拦截内网地址（含云元数据 169.254.169.254），"
                        f"防 AI 被诱导访问内网服务/云凭证。\n"
                        f"建议: 确需访问内网时设置 WEB_FETCH_BLOCK_PRIVATE=0（本地部署自担风险），"
                        f"或改用其他通道。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            if fake_ip:
                fake_ip_note = (
                    "[注] 目标解析为代理假 IP 段（198.18/15，Surge/Clash fake-ip 模式），"
                    "已按代理通道放行（真实连接由代理完成）；WEB_FETCH_BLOCK_FAKE_IP=1 "
                    "可恢复严格拦截。\n"
                )
        # 单例感知: 短时重复抓取同一 URL → 提示可复用
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
        except _PrivateTargetBlockedError as exc:
            # P0-2: 重定向/连接后命中内网（与初始拦截同一回执语义）
            return ToolResult(
                status=ToolResultStatus.BLOCKED,
                content=(
                    f"[内网拦截] {exc}，已拒绝访问（SSRF 防护——重定向目标逐跳校验）。\n"
                    f"原因: 公开 URL 的 3xx 重定向目标属于私网/保留地址段，"
                    f"自动跟随会泄内网信息/云凭证（审计发现 #1 修复）。\n"
                    f"建议: 核对最终跳转目标；确需访问内网时设置 WEB_FETCH_BLOCK_PRIVATE=0（自担风险）。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        except httpx.TimeoutException:
            resp = None
            httpx_note = f"httpx 超时（{self._timeout_s:.0f}s）"
        except _RedirectLimitExceededError as exc:
            resp = None
            httpx_note = f"httpx 重定向超限（{exc}）"
        except httpx.HTTPError as exc:
            resp = None
            httpx_note = f"httpx {type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 — httpx 通道意外异常如实降级 curl（fail-open）
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
            try:
                fallback = self._curl_fetch(url)
            except _PrivateTargetBlockedError as exc:
                # P0-2: curl 通道重定向命中内网（同一回执语义）
                return ToolResult(
                    status=ToolResultStatus.BLOCKED,
                    content=(
                        f"[内网拦截] {exc}，已拒绝访问（SSRF 防护——重定向目标逐跳校验）。\n"
                        f"原因: 3xx 重定向目标属于私网/保留地址段，自动跟随会泄内网信息/云凭证。\n"
                        f"建议: 核对最终跳转目标；确需访问内网时设置 WEB_FETCH_BLOCK_PRIVATE=0（自担风险）。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            except _RedirectLimitExceededError as exc:
                fallback = None
                httpx_note = f"{httpx_note}；curl 重定向超限（{exc}）"
            except Exception:  # noqa: BLE001 — curl 通道意外异常如实落入失败回执
                fallback = None
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
        header += fake_ip_note  # 代理假 IP 放行如实标注（未命中则为空）
        header += "\n"
        _fetch_history[url] = now  # 记录本次抓取（成功才记，失败不记）
        if not text.strip():
            text = "（页面无文本内容）"
        body = header + text
        total = len(body)
        if start > 0:
            # 分页续读（start 与 count 正交）
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
