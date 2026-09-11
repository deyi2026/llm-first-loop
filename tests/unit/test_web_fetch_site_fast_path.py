"""Site fast paths must stay one-shot and preserve web_fetch safety boundaries."""

import json
from unittest import mock

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.web_fetch import (
    WebFetchTool,
    _extract_toutiao_info,
    _toutiao_article_id,
)


def test_toutiao_article_id_requires_trusted_host() -> None:
    article_id = "1234567890123456789"
    assert _toutiao_article_id(f"https://www.toutiao.com/article/{article_id}/") == article_id
    assert _toutiao_article_id(f"https://m.toutiao.com/i{article_id}/") == article_id
    assert _toutiao_article_id(f"https://m.toutiao.com/w/{article_id}/") == article_id
    assert _toutiao_article_id(f"https://www.toutiao.com/x?group_id={article_id}") == article_id
    assert _toutiao_article_id(f"https://evil.example/article/{article_id}/") is None
    assert _toutiao_article_id("https://toutiao.com.evil.example/article/123456789/") is None


def test_extract_toutiao_info_cleans_html() -> None:
    raw = json.dumps(
        {
            "data": {
                "title": "测试标题",
                "content": "<p>第一段正文足够长，验证 HTML 清洗。</p><p>第二段正文继续补足长度。</p>",
            }
        },
        ensure_ascii=False,
    )
    parsed = _extract_toutiao_info(raw)
    assert parsed is not None
    title, text = parsed
    assert title == "测试标题"
    assert "第一段正文" in text and "第二段正文" in text
    assert "<p>" not in text


def test_toutiao_fast_path_uses_protected_adapter_and_skips_generic_request(monkeypatch) -> None:
    article_id = "1234567890123456789"
    original = f"https://www.toutiao.com/article/{article_id}/"
    payload = json.dumps(
        {
            "data": {
                "title": "快速正文",
                "content": "<p>这是通过 info/v2 快路径返回的正文，长度足以通过解析门槛。</p>",
            }
        },
        ensure_ascii=False,
    )
    tool = WebFetchTool()
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    with (
        mock.patch.object(tool, "_curl_fetch", return_value=("strip", payload)) as curl_fetch,
        mock.patch.object(tool, "_request") as generic_request,
    ):
        result = tool.execute(url=original)

    assert result.status == ToolResultStatus.SUCCESS
    curl_fetch.assert_called_once_with(f"https://m.toutiao.com/i{article_id}/info/v2/")
    generic_request.assert_not_called()
    assert "[extract] toutiao_info_v2" in result.content
    assert "站点快路径" in result.content
    assert "这是通过 info/v2 快路径返回的正文" in result.content


def test_toutiao_micro_post_fast_path_uses_same_protected_adapter(monkeypatch) -> None:
    """Regression: real /w/<id> links must not be preflight-routed away from info/v2."""
    article_id = "1876019686147072"
    original = f"https://m.toutiao.com/w/{article_id}/?app=news_article"
    payload = json.dumps(
        {
            "data": {
                "title": "微头条正文",
                "content": "<p>这是通过微头条 /w/ 地址进入同一受保护 info/v2 适配器的正文。</p>",
            }
        },
        ensure_ascii=False,
    )
    tool = WebFetchTool()
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    with (
        mock.patch.object(tool, "_curl_fetch", return_value=("strip", payload)) as curl_fetch,
        mock.patch.object(tool, "_request") as generic_request,
    ):
        result = tool.execute(url=original)

    assert result.status == ToolResultStatus.SUCCESS
    curl_fetch.assert_called_once_with(f"https://m.toutiao.com/i{article_id}/info/v2/")
    generic_request.assert_not_called()
    assert "微头条 /w/ 地址" in result.content


def test_toutiao_fast_path_miss_falls_back_to_generic_request(monkeypatch) -> None:
    article_id = "1234567890123456789"
    original = f"https://www.toutiao.com/article/{article_id}/"
    tool = WebFetchTool()
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    response = mock.MagicMock(
        status_code=200,
        text="<html><body>generic body from normal path</body></html>",
    )
    with (
        mock.patch.object(tool, "_curl_fetch", return_value=None),
        mock.patch.object(tool, "_request", return_value=response) as generic_request,
    ):
        result = tool.execute(url=original)

    assert result.status == ToolResultStatus.SUCCESS
    generic_request.assert_called_once_with(original)
    assert "generic body from normal path" in result.content


def test_registry_reaches_toutiao_fast_path(monkeypatch) -> None:
    """Registry preflight must not make a supported site adapter unreachable."""
    from llm_loop.core.message import ToolCall
    from llm_loop.tools.registry import ToolRegistry

    article_id = "1234567890123456789"
    original = f"https://www.toutiao.com/article/{article_id}/"
    payload = json.dumps(
        {
            "data": {
                "title": "Registry 可达正文",
                "content": "<p>这是从 ToolRegistry 进入受保护站点快路径得到的正文，长度足够。</p>",
            }
        },
        ensure_ascii=False,
    )
    tool = WebFetchTool()
    registry = ToolRegistry()
    registry.register(tool)
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    with (
        mock.patch.object(tool, "_curl_fetch", return_value=("strip", payload)) as curl_fetch,
        mock.patch.object(tool, "_request") as generic_request,
    ):
        result = registry.execute(
            ToolCall(id="call-fast", name="web_fetch", arguments={"url": original})
        )

    assert result.status == ToolResultStatus.SUCCESS
    curl_fetch.assert_called_once_with(f"https://m.toutiao.com/i{article_id}/info/v2/")
    generic_request.assert_not_called()
    assert "[extract] toutiao_info_v2" in result.content
    assert "Registry 可达正文" in result.content
