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


# ── 单例感知（既有实现 单例 Browser 借鉴: 短时重复抓取提示复用）──

def _reset_history():
    import llm_loop.tools.builtin.web_fetch as wf
    wf._fetch_history.clear()


def test_single_browser_reuse_notice():
    """短时重复抓同一 URL → 第二次回执提示可复用."""
    _reset_history()
    body = "甲" * 50
    t = _patch_fetch(_FakeTool(), body)
    r1 = t.execute(url="https://x.test/single", max_chars=200)
    assert "[重复抓取]" not in r1.content  # 首次无提示
    r2 = t.execute(url="https://x.test/single", max_chars=200)
    assert "[重复抓取]" in r2.content  # 短时重复 → 提示
    assert "秒前抓取过" in r2.content


def test_single_browser_different_url_no_notice():
    """不同 URL 互不影响."""
    _reset_history()
    body = "甲" * 50
    t = _patch_fetch(_FakeTool(), body)
    t.execute(url="https://x.test/a1", max_chars=200)
    r = t.execute(url="https://x.test/a2", max_chars=200)
    assert "[重复抓取]" not in r.content


def test_single_browser_window_expired():
    """超过 5 分钟窗口 → 不提示（网页可能已变化）."""
    import llm_loop.tools.builtin.web_fetch as wf
    _reset_history()
    body = "甲" * 50
    t = _patch_fetch(_FakeTool(), body)
    t.execute(url="https://x.test/w", max_chars=200)
    # 模拟 10 分钟前抓取过
    wf._fetch_history["https://x.test/w"] = wf._fetch_history["https://x.test/w"] - 600
    r = t.execute(url="https://x.test/w", max_chars=200)
    assert "[重复抓取]" not in r.content
