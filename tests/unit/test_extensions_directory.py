"""P2-B 目录服务：MCP Registry 只读发现（设计 §13 / FR-12 / §5.2）.

- 分页聚合（cursor）；两种响应形态（openapi releases/packages 与实况
  remotes/type/_meta.status）都如实解析。
- 只生成候选：不安装、不信任、不执行（函数族无副作用）。
- 可用性如实：HTTP 错误/网络失败/坏 JSON → ok=False + availability 原因；
  分页未取尽 → truncated=True 且续读游标保留。
"""

from __future__ import annotations

import json
import os

import pytest

from llm_loop.extensions.directory import (
    DEFAULT_REGISTRY_BASE,
    discover_registry_servers,
)


def _page(servers: list[dict], next_cursor: str = "") -> str:
    return json.dumps(
        {"servers": servers, "metadata": {"nextCursor": next_cursor, "count": len(servers)}}
    )


def _openapi_entry(name: str, version: str = "1.0.0") -> dict:
    return {
        "server": {
            "name": name,
            "description": f"desc {name}",
            "website_url": f"https://example.com/{name}",
            "releases": [
                {"version": version, "requirements": [{"transport_type": "streamable-http"}]}
            ],
            "packages": [
                {"registry_type": "npm", "identifier": f"@x/{name}", "version": version, "file_sha256": "a" * 64}
            ],
        },
        "_meta": {},
    }


def _live_entry(name: str, status: str = "active", remote_type: str = "sse") -> dict:
    return {
        "server": {
            "name": name,
            "title": f"Title {name}",
            "description": f"live desc {name}",
            "version": "2.3.4",
            "remotes": [{"type": remote_type, "url": f"https://{name}.example/mcp"}],
        },
        "_meta": {"io.modelcontextprotocol.registry/official": {"status": status}},
    }


def test_pagination_aggregates_openapi_shape() -> None:
    pages = {
        "https://reg.example/v0.1/servers?limit=100": _page([_openapi_entry("a")], "CUR2"),
        "https://reg.example/v0.1/servers?limit=100&cursor=CUR2": _page([_openapi_entry("b", "0.9.0")]),
    }

    def fake_get(url: str) -> tuple[int, str]:
        return 200, pages[url]

    d = discover_registry_servers("https://reg.example", http_get=fake_get)
    assert d.ok and len(d.candidates) == 2 and d.page_count == 2 and not d.truncated
    a = d.candidates[0]
    assert a.name == "a" and a.latest_version == "1.0.0"
    assert a.packages[0]["identifier"] == "@x/a"
    assert "sha256" in json.dumps(a.packages)
    assert a.remote_transports == ("streamable-http",)


def test_live_shape_remotes_and_meta_status() -> None:
    def fake_get(url: str) -> tuple[int, str]:
        return 200, _page([_live_entry("x", status="deprecated", remote_type="sse")])

    d = discover_registry_servers("https://reg.example", http_get=fake_get)
    c = d.candidates[0]
    assert c.status == "deprecated"
    assert c.remote_transports == ("sse",)
    assert c.remote_urls == ("https://x.example/mcp",)
    assert c.latest_version == "2.3.4"


def test_truncation_keeps_cursor_and_reports() -> None:
    def fake_get(url: str) -> tuple[int, str]:
        return 200, _page([_openapi_entry("loop")], "SAME")

    d = discover_registry_servers("https://reg.example", http_get=fake_get, max_pages=2)
    assert d.ok and d.truncated and d.page_count == 2 and d.next_cursor == "SAME"
    assert "页数上限" in d.availability


def test_http_and_network_failures_reported_honestly() -> None:
    import urllib.error

    def http_500(url: str) -> tuple[int, str]:
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)  # type: ignore[arg-type]

    d = discover_registry_servers("https://reg.example", http_get=http_500)
    assert not d.ok and d.candidates == ()
    assert "HTTP 500" in d.availability

    def net_fail(url: str) -> tuple[int, str]:
        raise OSError("dns broken")

    d2 = discover_registry_servers("https://reg.example", http_get=net_fail)
    assert not d2.ok and "不可达" in d2.availability

    def bad_json(url: str) -> tuple[int, str]:
        return 200, "<html>not json</html>"

    d3 = discover_registry_servers("https://reg.example", http_get=bad_json)
    assert not d3.ok and "非 JSON" in d3.availability

    def bad_shape(url: str) -> tuple[int, str]:
        return 200, json.dumps({"servers": "nope"})

    d4 = discover_registry_servers("https://reg.example", http_get=bad_shape)
    assert not d4.ok and "结构异常" in d4.availability


def test_discovery_has_no_install_side_effects(tmp_path) -> None:
    """只读发现：不写任何文件、不调用安装路径（§13 候选不自动安装）."""
    def fake_get(url: str) -> tuple[int, str]:
        return 200, _page([_openapi_entry("z")])

    before = set(tmp_path.rglob("*"))
    d = discover_registry_servers("https://reg.example", http_get=fake_get)
    assert d.ok
    after = set(tmp_path.rglob("*"))
    assert before == after  # 无文件副作用


def test_default_base_and_availability_note_mentions_not_certification() -> None:
    def fake_get(url: str) -> tuple[int, str]:
        assert url.startswith(DEFAULT_REGISTRY_BASE)
        return 200, _page([_openapi_entry("w")])

    d = discover_registry_servers(http_get=fake_get)
    assert d.ok
    assert "非认证" in d.availability  # 元数据 ≠ 认证


@pytest.mark.skipif(
    os.environ.get("LFL_TEST_LIVE_REGISTRY") != "1",
    reason="实连 Registry 需 LFL_TEST_LIVE_REGISTRY=1（网络环境依赖，默认跳过）",
)
def test_live_registry_discovery_smoke() -> None:
    d = discover_registry_servers(page_size=5, max_pages=1, timeout_s=20)
    assert d.ok or "不可达" in d.availability or "HTTP" in d.availability
