"""M48 单元测试: web_fetch 正文提取降级链 + web_search 双后端降级."""

import json
from unittest import mock

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.web_fetch import (
    WebFetchTool,
    _density_extract,
    _extract_title,
    _strip_tags,
)
from llm_loop.tools.builtin.web_search import WebSearchTool


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", reason_phrase: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.reason_phrase = reason_phrase
        self.headers: dict = {}
        self.extensions: dict = {}

    def read(self) -> bytes:
        return self.text.encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=None)


class _FakeStreamCM:
    """P0-2 后 web_fetch httpx 通道走 client.stream：上下文管理器包装."""

    def __init__(self, resp: _FakeResponse) -> None:
        self._resp = resp

    def __enter__(self) -> _FakeResponse:
        return self._resp

    def __exit__(self, *args) -> bool:
        return False


def _stream_seq(*items):
    """构造 client.stream 的 side_effect：依次返回 _FakeStreamCM 或抛异常."""

    seq = list(items)

    def _side(method, url, headers=None):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeStreamCM(item)

    return _side


def _fake_client(resp):
    return mock.patch("httpx.Client") and resp


def test_web_fetch_extract_header_and_body(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """正文提取成功时输出含 title/source/extract 头与正文."""
    tool = WebFetchTool()
    html = (
        '<html><head><meta property="og:title" content="测试文章标题">'
        "<title>兜底标题</title></head><body><div class=\"article-content\">"
        + "<p>这是正文段落。" + "长" * 60 + "</p></div> </body></html>"
    )
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.stream.side_effect = _stream_seq(
            _FakeResponse(200, html)
        )
        r = tool.execute(url="https://example.com/a")
    assert r.status == ToolResultStatus.SUCCESS
    assert "[title] 测试文章标题" in r.content
    assert "[source] https://example.com/a" in r.content
    assert "这是正文段落" in r.content


def test_web_fetch_403_ua_rotation(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """403 时自动换 UA 重试，第二个 UA 成功则整体成功."""
    tool = WebFetchTool()
    ok = _FakeResponse(200, "<html>Hello Page</html>")
    forbid = _FakeResponse(403, reason_phrase="Forbidden")
    stream = mock.MagicMock(side_effect=_stream_seq(forbid, ok))
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.stream = stream
        r = tool.execute(url="https://example.com")
    assert r.status == ToolResultStatus.SUCCESS
    assert stream.call_count == 2
    assert "Hello Page" in r.content


def test_web_fetch_js_shell_hint(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """JS 壳页面如实提示，不伪装正文成功."""
    tool = WebFetchTool()
    shell = '<html><body><noscript>您需要允许该页面 JavaScript</noscript><script>var _$jsvmprt=1;</script></body></html>'
    article = ("<html><head><title>t</title></head><body><p>" + "正文" * 40 + "</p></body></html>").encode()
    # P0-2 后 curl 回退带状态行解析——本地替身返回 200 文章（原实现隐式依赖真实网络 404 页，脆弱）
    with (
        mock.patch("httpx.Client") as client_cls,
        mock.patch("subprocess.run", return_value=_curl_proc(article)),
    ):
        client_cls.return_value.__enter__.return_value.stream.side_effect = _stream_seq(
            _FakeResponse(200, shell)
        )
        r = tool.execute(url="https://example.com/shell")
    assert r.status == ToolResultStatus.SUCCESS
    assert "JS 壳" in r.content


def test_extract_helpers():
    assert _extract_title('<title>abc</title>') == "abc"
    density = _density_extract('<div class="article-content"><p>' + "正文" * 40 + "</p></div> <div>尾</div>")
    assert "正文" in density
    assert _strip_tags("<p>a<b>b</b></p>") == "a b"


def test_web_search_bing_success():
    """Bing HTML 解析出结构化结果."""
    tool = WebSearchTool()
    html = '<ol><li><h2><a href="https://a.com/x">结果一</a></h2></li><li><h2><a href="https://b.com">结果二</a></h2></li></ol>'
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _FakeResponse(200, html)
        r = tool.execute(query="test query", limit=5)
    assert r.status == ToolResultStatus.SUCCESS
    assert "[backend] bing" in r.content
    assert "结果一" in r.content and "https://a.com/x" in r.content


def test_web_search_fallback_to_baidu():
    """Bing 失败降级百度，并如实记录降级."""
    tool = WebSearchTool()
    baidu_html = '<h3><a href="https://www.baidu.com/link?url=x">百度结果</a></h3>'

    def _side(url, headers=None, **kw):
        if "bing" in url:
            raise __import__("httpx").ConnectError("boom")
        return _FakeResponse(200, baidu_html)

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = _side
        r = tool.execute(query="q")
    assert r.status == ToolResultStatus.SUCCESS
    assert "[backend] baidu" in r.content
    assert "降级记录" in r.content
    assert "bing" in r.content


def test_web_search_all_fail_honest():
    """全部后端失败如实返回，不伪造结果."""
    tool = WebSearchTool()
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = __import__("httpx").ConnectError("down")
        r = tool.execute(query="q")
    assert r.status == ToolResultStatus.FAILURE
    assert "所有后端均不可用" in r.content


def test_web_search_missing_query():
    assert WebSearchTool().execute().status == ToolResultStatus.FAILURE


# ── M48-B: curl 回退通道 ──

def _curl_proc(stdout: bytes, returncode: int = 0, code: int = 200, redirect: str = ""):
    # P0-2: curl 不再 -L 自动跟随，-w 尾部追加 "\n%{http_code} %{redirect_url}" 供手动循环判定
    return mock.MagicMock(returncode=returncode, stdout=stdout + f"\n{code} {redirect}".encode())


def test_curl_fallback_on_connect_error(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """httpx 连接被重置（TLS 指纹拦截场景）→ curl 回退成功并如实标注."""
    tool = WebFetchTool()
    article = "<html><head><title>真文章</title></head><body><div class=\"article-content\"><p>" + "正文" * 40 + "</p></div> </body></html>"
    with (
        mock.patch("httpx.Client") as client_cls,
        mock.patch("subprocess.run", return_value=_curl_proc(article.encode())) as run_mock,
    ):
        client_cls.return_value.__enter__.return_value.stream.side_effect = __import__("httpx").ConnectError("reset")
        r = tool.execute(url="https://example.com/a")
    assert r.status == ToolResultStatus.SUCCESS
    assert "[fetch] curl 回退" in r.content
    assert "ConnectError" in r.content  # 如实记录 httpx 侧原因
    assert "正文" in r.content
    # argv 列表传参（无 shell），URL 在 -- 之后
    args = run_mock.call_args[0][0]
    assert args[0] == "curl" and "--" in args and "https://example.com/a" in args


def test_curl_fallback_on_js_shell(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """httpx 仅取到 JS 壳 → curl 回退拿到正文（头条场景）."""
    tool = WebFetchTool()
    shell = '<html><body><noscript>您需要允许该网站执行 JavaScript</noscript><script>var _$jsvmprt=1;</script></body></html>'
    article = "<html><head><title>头条文章</title></head><body><div class=\"article-content\"><p>" + "正文" * 40 + "</p></div> </body></html>"
    with (
        mock.patch("httpx.Client") as client_cls,
        mock.patch("subprocess.run", return_value=_curl_proc(article.encode())),
    ):
        client_cls.return_value.__enter__.return_value.stream.side_effect = _stream_seq(
            _FakeResponse(200, shell)
        )
        r = tool.execute(url="https://m.toutiao.com/article/x/")
    assert r.status == ToolResultStatus.SUCCESS
    assert "curl 回退" in r.content and "JS 壳" in r.content
    assert "正文" in r.content


def test_curl_fallback_both_fail_honest(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """httpx 失败 + curl 也失败 → 如实双失败，不伪造."""
    tool = WebFetchTool()
    with (
        mock.patch("httpx.Client") as client_cls,
        mock.patch("subprocess.run", return_value=_curl_proc(b"", returncode=7)),
    ):
        client_cls.return_value.__enter__.return_value.stream.side_effect = __import__("httpx").ConnectError("down")
        r = tool.execute(url="https://example.com")
    assert r.status == ToolResultStatus.FAILURE
    assert "curl 回退亦失败" in r.content
    assert "ConnectError" in r.content


def test_curl_fallback_skips_shell_and_tries_next_ua(monkeypatch):
    """curl 首个 UA 取到 JS 壳时换 UA 再试."""
    # P0-2 后 _curl_fetch 每跳做内网校验——本测试聚焦 UA 轮换，关闭拦截避免 DNS 干扰
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    tool = WebFetchTool()
    shell = b'<html><body><noscript>enable javascript</noscript><script>_$jsvmprt</script></body></html>'
    article = ("<html><head><title>t</title></head><body><p>" + "正文" * 40 + "</p></body></html>").encode()
    with mock.patch("subprocess.run", side_effect=[_curl_proc(shell), _curl_proc(article)]) as run_mock:
        got = tool._curl_fetch("https://example.com")
    assert got is not None and run_mock.call_count == 2


# ── M48-C: 垂直搜索通道（免 key 公开 API）──

_OA_JSON = json.dumps({
    "results": [
        {"title": "Paper A", "publication_year": 2025, "cited_by_count": 12,
         "primary_location": {"landing_page_url": "https://a.example.com/p1"}},
        {"title": "Paper B", "publication_year": 2024, "cited_by_count": 3,
         "primary_location": {"landing_page_url": "https://b.example.com/p2"}},
    ]
})
_CR_JSON = json.dumps({"message": {"items": [
    {"title": ["Paper C"], "DOI": "10.1/x", "issued": {"date-parts": [[2023]]}},
]}})
_PM_SEARCH = json.dumps({"esearchresult": {"idlist": ["111", "222"]}})
_PM_SUMM = json.dumps({"result": {"uids": ["111", "222"],
    "111": {"title": "Med A", "source": "Nature", "pubdate": "2025"},
    "222": {"title": "Med B", "source": "Cell", "pubdate": "2024"}}})
_GH_JSON = json.dumps({"items": [
    {"full_name": "a/b", "html_url": "https://github.com/a/b", "stargazers_count": 99,
     "language": "Python", "description": "demo"},
]})


def _json_router(mapping):
    def _side(url, headers=None, **kw):
        for key, body in mapping.items():
            if key in url:
                return _FakeResponse(200, body)
        raise __import__("httpx").ConnectError(f"no route: {url}")
    return _side


def test_scholar_merges_multi_source():
    """scholar 通道合并 OpenAlex+Crossref+PubMed 并标注来源."""
    tool = WebSearchTool()
    mapping = {
        "openalex": _OA_JSON,
        "crossref": _CR_JSON,
        "esearch": _PM_SEARCH,
        "esummary": _PM_SUMM,
    }
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = _json_router(mapping)
        r = tool.execute(query="llm agent", channel="scholar", limit=10)
    assert r.status == ToolResultStatus.SUCCESS
    assert "[channel] scholar" in r.content
    assert "Paper A" in r.content and "Paper C" in r.content and "Med A" in r.content
    assert "openalex" in r.content and "crossref" in r.content and "pubmed" in r.content
    assert "被引:12" in r.content


def test_scholar_partial_failure_degrades():
    """单源失败降级其余源，并如实记录降级."""
    tool = WebSearchTool()
    mapping = {"crossref": _CR_JSON, "esearch": _PM_SEARCH, "esummary": _PM_SUMM}
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = _json_router(mapping)
        r = tool.execute(query="x", channel="scholar")
    assert r.status == ToolResultStatus.SUCCESS
    assert "Paper C" in r.content
    assert "降级记录" in r.content and "openalex" in r.content


def test_code_channel_github():
    tool = WebSearchTool()
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = _json_router({"api.github.com": _GH_JSON})
        r = tool.execute(query="anysearch", channel="code")
    assert r.status == ToolResultStatus.SUCCESS
    assert "a/b" in r.content and "★99" in r.content and "github" in r.content


def test_channel_all_fail_honest():
    tool = WebSearchTool()
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = __import__("httpx").ConnectError("down")
        r = tool.execute(query="x", channel="scholar")
    assert r.status == ToolResultStatus.FAILURE
    assert "channel=scholar" in r.content


def test_auto_routing():
    from llm_loop.tools.builtin.web_search import _route_channel
    assert _route_channel("找几篇关于agent的论文") == "scholar"
    assert _route_channel("anysearch github 仓库") == "code"
    assert _route_channel("今天天气怎么样") == "general"
    # auto 端到端：走 code 通道
    tool = WebSearchTool()
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = _json_router({"api.github.com": _GH_JSON})
        r = tool.execute(query="anysearch github", channel="auto")
    assert "[channel] code" in r.content


def test_merge_dedupe():
    from llm_loop.tools.builtin.web_search import _merge_dedupe
    g1 = [{"title": "A", "url": "u1"}, {"title": "B", "url": "u2"}]
    g2 = [{"title": "A2", "url": "u1"}, {"title": "C", "url": "u3"}]
    merged = _merge_dedupe([g1, g2], 10)
    assert [m["title"] for m in merged] == ["A", "B", "C"]


# --- M49: bing 摘要提取 + SPA 内嵌 JSON 提取 ---

def test_bing_snippet_extraction():
    """M49: b_algo 块内 <p> 摘要被提取（供 LLM 预判相关性）."""
    from llm_loop.tools.builtin.web_search import _search_bing

    html = (
        '<li class="b_algo"><h2><a href="https://a.com/x">标题A</a></h2>'
        '<p>这是结果A的详细摘要描述，长度足够用于判断相关性，超过三十字阈值。</p></li>'
        '<li class="b_algo"><h2><a href="https://b.com/y">标题B</a></h2></li>'
    )
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _FakeResponse(200, html)
        rs = _search_bing("q", 5, 5)
    assert rs[0]["title"] == "标题A"
    assert "详细摘要" in rs[0]["snippet"]
    assert rs[1]["snippet"] == ""  # 无 <p> 摘要留空


def test_web_fetch_embedded_json_extract(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """M49: SPA 内嵌 JSON（ld+json）正文提取，过滤 URL 噪声."""
    from llm_loop.tools.builtin.web_fetch import _embedded_json_extract

    raw = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"WebPage","headline":"示例文章标题","description":"这是内嵌JSON中的正文内容，'
        '长度足够超过过滤阈值，用于验证SPA数据提取路径是否正常工作并且完整返回。"}'
        '</script></head><body><div id="app"></div></body></html>'
    )
    txt = _embedded_json_extract(raw)
    assert "内嵌JSON" in txt
    assert "https://" not in txt  # URL 噪声被过滤


def test_web_fetch_embedded_json_noise_filter(monkeypatch):
    # 本测试聚焦其他行为（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰（198.18/15 VPN 劫持段）
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    """M49: 纯 URL 字符串被过滤，不污染正文."""
    from llm_loop.tools.builtin.web_fetch import _embedded_json_extract

    raw = (
        '<script type="application/ld+json">'
        '{"image":"https://cdn.example.com/pic.png","text":"这是一段有意义的正文内容，'
        '长度足够超过四十字阈值，应当被正常保留下来用于阅读判断。"}'
        '</script>'
    )
    txt = _embedded_json_extract(raw)
    assert "有意义" in txt
    assert "pic.png" not in txt
