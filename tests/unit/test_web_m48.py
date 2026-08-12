"""M48 单元测试: web_fetch 正文提取降级链 + web_search 双后端降级."""

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

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=None)


def _fake_client(resp):
    return mock.patch("httpx.Client") and resp


def test_web_fetch_extract_header_and_body():
    """正文提取成功时输出含 title/source/extract 头与正文."""
    tool = WebFetchTool()
    html = (
        '<html><head><meta property="og:title" content="测试文章标题">'
        "<title>兜底标题</title></head><body><div class=\"article-content\">"
        + "<p>这是正文段落。" + "长" * 60 + "</p></div> </body></html>"
    )
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _FakeResponse(200, html)
        r = tool.execute(url="https://example.com/a")
    assert r.status == ToolResultStatus.SUCCESS
    assert "[title] 测试文章标题" in r.content
    assert "[source] https://example.com/a" in r.content
    assert "这是正文段落" in r.content


def test_web_fetch_403_ua_rotation():
    """403 时自动换 UA 重试，第二个 UA 成功则整体成功."""
    tool = WebFetchTool()
    ok = _FakeResponse(200, "<html>Hello Page</html>")
    forbid = _FakeResponse(403, reason_phrase="Forbidden")
    get = mock.MagicMock(side_effect=[forbid, ok])
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get = get
        r = tool.execute(url="https://example.com")
    assert r.status == ToolResultStatus.SUCCESS
    assert get.call_count == 2
    assert "Hello Page" in r.content


def test_web_fetch_js_shell_hint():
    """JS 壳页面如实提示，不伪装正文成功."""
    tool = WebFetchTool()
    shell = '<html><body><noscript>您需要允许该页面 JavaScript</noscript><script>var _$jsvmprt=1;</script></body></html>'
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _FakeResponse(200, shell)
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
