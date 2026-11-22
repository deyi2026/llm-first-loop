"""CDP 端点可达性探针回归（EVO-20261121-efa320ab；RULE-AI-24 RED→GREEN）。

背景（本机实测，2026-11-21）：本机 Chrome 已登录但未开远程调试端口，CDP 端点
"不可发现"——没有任何工具能回答"Chrome 有没有开调试端口"，只能盲写坐标脚本。
本文件锁定探针的四条边界：

1) 可达端点如实报告 browser/协议版本/目标数；不可达端点如实报错、不伪报可达；
2) 探针只读 loopback 元信息，**不回传**页面标题/URL 等页面内容；非 loopback 直接拒绝；
3) 候选来源包含 DevToolsActivePort 文件（Chrome 开启调试端口时的落盘事实）；
4) 探针不属 browser_* 页面能力家族（既有"一只眼一只手"能力身份契约保持不变）。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from llm_loop.browser import cdp_probe
from llm_loop.tools.builtin.cdp_probe import CdpProbeTool


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        if self.path == "/json/version":
            payload = {
                "Browser": "Chrome/138.0.0.0",
                "Protocol-Version": "1.3",
                "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/browser/abc",
            }
        elif self.path == "/json/list":
            payload = [{"title": "私密页面标题", "url": "https://example.com/private"}]
        else:
            payload = {}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # pragma: no cover - 静默测试服务器
        return


@pytest.fixture
def cdp_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_probe_reports_reachable_endpoint(cdp_server: str) -> None:
    report = cdp_probe.probe_cdp_endpoint(cdp_server)

    assert report["reachable"] is True
    assert "Chrome/138" in (report["browser"] or "")
    assert report["target_count"] == 1
    assert "私密页面标题" not in json.dumps(report, ensure_ascii=False)
    assert "example.com" not in json.dumps(report, ensure_ascii=False)


def test_probe_reports_unreachable_endpoint_without_faking_success() -> None:
    report = cdp_probe.probe_cdp_endpoint("http://127.0.0.1:1", timeout_s=0.5)

    assert report["reachable"] is False
    assert report["error"]


def test_probe_rejects_non_loopback_target() -> None:
    report = cdp_probe.probe_cdp_endpoint("http://example.com:9222")

    assert report["reachable"] is False
    assert "loopback" in (report["error"] or "")


def test_devtools_active_port_file_is_discovered(tmp_path) -> None:
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text("39999\n/devtools/browser/xyz\n", encoding="utf-8")

    candidates = cdp_probe.discover_cdp_candidates(user_data_dirs=[str(profile)])

    assert "http://127.0.0.1:39999" in candidates


def test_probe_tool_reports_candidates_and_opt_in_guidance(cdp_server: str) -> None:
    result = CdpProbeTool().execute(url=cdp_server)

    assert result.status is not None
    assert "LFL_BROWSER_PERCEPTION_CDP_URL" in result.content
    assert "可达" in result.content
    assert "私密页面标题" not in result.content


def test_probe_tool_does_not_write_configuration(cdp_server: str, monkeypatch) -> None:
    monkeypatch.delenv("LFL_BROWSER_PERCEPTION_CDP_URL", raising=False)

    CdpProbeTool().execute(url=cdp_server)

    assert os.environ.get("LFL_BROWSER_PERCEPTION_CDP_URL") is None


def test_probe_is_not_in_browser_page_capability_family() -> None:
    """既有能力身份契约（provider-visible browser 面恰好一只眼一只手）不被本探针放宽."""
    assert CdpProbeTool.name == "cdp_probe"
    assert not CdpProbeTool.name.startswith("browser_")


def test_extra_ports_are_merged_with_defaults() -> None:
    """额外端口是加法：与缺省端口合并，不替换（review P2-1）。"""
    candidates = cdp_probe.discover_cdp_candidates(env_url="", ports=[9333])

    assert "http://127.0.0.1:9222" in candidates
    assert "http://127.0.0.1:9223" in candidates
    assert "http://127.0.0.1:9229" in candidates
    assert "http://127.0.0.1:9333" in candidates


def test_extra_inputs_and_candidates_are_bounded() -> None:
    """额外端口/目录与候选端点总数都有上界（review P2-2）。"""
    candidates = cdp_probe.discover_cdp_candidates(
        env_url="",
        ports=list(range(9300, 9400)),
        user_data_dirs=[f"/tmp/lfl-cdp-dir-{index}" for index in range(50)],
    )

    extra_ports = [c for c in candidates if ":93" in c]
    assert len(extra_ports) <= cdp_probe.MAX_EXTRA_PORTS
    assert len(candidates) <= cdp_probe.MAX_CANDIDATES


def test_probe_tool_stops_at_total_deadline(monkeypatch) -> None:
    """整体时限到点即停：剩余候选不再逐个探测（如实回报而非静默少探）。"""
    from llm_loop.tools.builtin import cdp_probe as cdp_probe_tool

    calls: list[tuple[str, float]] = []

    def fake_probe(base_url: str, timeout_s: float = 2.0) -> dict:
        calls.append((base_url, timeout_s))
        return {
            "url": base_url,
            "reachable": False,
            "browser": None,
            "protocol_version": None,
            "target_count": None,
            "error": "测试占位",
        }

    class _FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def monotonic(self) -> float:
            self.now += 6.0
            return self.now

    monkeypatch.setattr(cdp_probe_tool, "time", _FakeClock())
    monkeypatch.setattr(cdp_probe_tool, "probe_cdp_endpoint", fake_probe)

    result = CdpProbeTool().execute(ports=[9300, 9301, 9302])

    assert len(calls) == 1
    assert calls[0][1] <= cdp_probe_tool.TOTAL_TIMEOUT_S
    assert "时限" in result.content
