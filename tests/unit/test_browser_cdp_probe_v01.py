"""CDP 端点可达性探针回归（EVO-20261121-efa320ab；RULE-AI-24 RED→GREEN）。

背景（本机实测，2026-11-21）：本机 Chrome 已登录但未开远程调试端口，CDP 端点
"不可发现"——没有任何工具能回答"Chrome 有没有开调试端口"，只能盲写坐标脚本。
本文件锁定探针的三条边界：

1) 可达端点如实报告 browser/协议版本/目标数；不可达端点如实报错、不伪报可达；
2) 探针只读 loopback 元信息，**不回传**页面标题/URL 等页面内容；
3) 候选来源包含 DevToolsActivePort 文件（Chrome 开启调试端口时的落盘事实）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from llm_loop.browser import cdp_probe
from llm_loop.tools.builtin.browser_probe import BrowserProbeTool


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


def test_devtools_active_port_file_is_discovered(tmp_path) -> None:
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text("39999\n/devtools/browser/xyz\n", encoding="utf-8")

    candidates = cdp_probe.discover_cdp_candidates(user_data_dirs=[str(profile)])

    assert "http://127.0.0.1:39999" in candidates


def test_probe_tool_reports_candidates_and_opt_in_guidance(cdp_server: str) -> None:
    result = BrowserProbeTool().execute(url=cdp_server)

    assert result.status is not None
    assert "LFL_BROWSER_PERCEPTION_CDP_URL" in result.content
    assert "可达" in result.content
    assert "私密页面标题" not in result.content
