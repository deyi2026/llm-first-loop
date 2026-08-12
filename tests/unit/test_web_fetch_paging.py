"""web_fetch 分页续读测试（既有实现 read_preview 借鉴）.

验证:
- start=0 默认整段截断 + 续读提示
- start>0 返回 [start, start+max_chars) 段 + 分页标注
- 越界返回 FAILURE（已抓全）
- 无超长不触发分页逻辑
"""
from __future__ import annotations

from llm_loop.tools.builtin.web_fetch import WebFetchTool


class _FakeTool(WebFetchTool):
    """注入固定正文，跳过真实网络请求."""

    def execute(self, **kwargs):
        # 复用真实 execute，但替换 _request/_curl_fetch 路径
        return super().execute(**kwargs)


def _patch_fetch(tool, body: str):
    """monkeypatch 网络层：返回固定正文."""
    def fake_request(url):
        import httpx
        resp = httpx.Response(200, text=f"<html><body>{body}</body></html>", request=httpx.Request("GET", url))
        return resp

    def fake_curl(url):
        return ("strip", "测试页", body)

    tool._request = fake_request  # type: ignore[method-assign]
    tool._curl_fetch = fake_curl  # type: ignore[method-assign]
    return tool


def test_paging_continues():
    """start>0 续读下一段."""
    body = "甲" * 500
    t = _patch_fetch(_FakeTool(), body)
    # 第一段
    r1 = t.execute(url="https://x.test/a", max_chars=200)
    assert r1.status == "success"
    assert "[内容超长" in r1.content  # 截断提示 + 续读 start
    assert "start=200" in r1.content
    # 续读第二段
    r2 = t.execute(url="https://x.test/a", max_chars=200, start=200)
    assert r2.status == "success"
    assert "[分页" in r2.content
    assert "甲" in r2.content


def test_paging_oop_bounds():
    """越界返回 FAILURE（已抓全）."""
    body = "甲" * 100
    t = _patch_fetch(_FakeTool(), body)
    r = t.execute(url="https://x.test/a", max_chars=200, start=500)
    assert r.status == "failure"
    assert "分页越界" in r.content


def test_no_trim_no_paging():
    """内容未超长 → 无分页标注（零回归）."""
    body = "短内容"
    t = _patch_fetch(_FakeTool(), body)
    r = t.execute(url="https://x.test/a", max_chars=1000)
    assert r.status == "success"
    assert "[分页" not in r.content
    assert "[内容超长" not in r.content
    assert "短内容" in r.content


def test_paging_with_explicit_count():
    """start 与 count 正交：start 定起点、count 定段长."""
    body = "甲乙丙丁戊己庚辛壬癸" * 30  # 300 字符
    t = _patch_fetch(_FakeTool(), body)
    # 第一段: start=0, count=100
    r1 = t.execute(url="https://x.test/a", max_chars=200, count=100)
    assert r1.status == "success"
    assert "[内容超长" in r1.content  # 全文 300 > 100 → 截断提示
    # 第二段: start=100, count=100（跳过第一段继续）
    r2 = t.execute(url="https://x.test/a", max_chars=200, start=100, count=100)
    assert r2.status == "success"
    assert "[分页" in r2.content
    assert "start=200" in r2.content  # 提示下一段位置


def test_count_defaults_to_max_chars():
    """count 未指定 → 段长 = max_chars（兼容原行为）."""
    body = "甲" * 500
    t = _patch_fetch(_FakeTool(), body)
    r1 = t.execute(url="https://x.test/a", max_chars=200)
    assert "start=200" in r1.content  # 段长 200 = max_chars
    r2 = t.execute(url="https://x.test/a", max_chars=200, start=200)
    assert r2.status == "success"
