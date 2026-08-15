"""web_fetch 代理假 IP 段（198.18/15）感知测试（2026-08-15 用户现场修复）.

背景: Surge/Clash fake-ip 模式下代理 DNS 将目标域名解析为 198.18.0.0/15 假地址，
既有 SSRF 拦截（Python is_private 含该段）误杀全部外网抓取，测试被迫 WEB_FETCH_BLOCK_PRIVATE=0 绕过。

修复: 全部解析地址均为 198.18/15（代理假 IP）→ 默认放行 + 回执如实标注；
WEB_FETCH_BLOCK_FAKE_IP=1 恢复严格拦截。真实私网/回环/链路本地/保留段拦截语义不变（P0 不回归）。
"""

from __future__ import annotations

import socket
from unittest import mock

from llm_loop.tools.builtin.web_fetch import (
    WebFetchTool,
    _blocked_private_url,
    _resolve_checked_ips,
)
from llm_loop.tools.registry import ToolResultStatus

_FAKE_IP = "198.18.13.42"


def test_fake_ip_literal_allowed_by_default():
    """默认: 198.18/15 字面量目标放行（不拦截）."""
    assert _blocked_private_url(f"http://{_FAKE_IP}/x") == ""


def test_fake_ip_literal_strict_mode_blocks(monkeypatch):
    """WEB_FETCH_BLOCK_FAKE_IP=1: 198.18/15 按拦截处理."""
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "1")
    label = _blocked_private_url(f"http://{_FAKE_IP}/x")
    assert "198.18" in label


def test_real_private_still_blocked_default():
    """默认: 真实私网段拦截语义不变（P0 不回归）."""
    assert "10.0.0.1" in _blocked_private_url("http://10.0.0.1/x")
    assert "192.168.1.1" in _blocked_private_url("http://192.168.1.1/x")
    assert "169.254.169.254" in _blocked_private_url("http://169.254.169.254/latest/meta-data")


def test_real_private_still_blocked_even_with_fake_ip(monkeypatch):
    """混合解析（假 IP + 真实私网）→ 仍拦截（防解析漂移面不收窄）."""
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "0")
    label, ips, host, port, fake = _resolve_checked_ips("http://10.0.0.1/x")
    assert label and "10.0.0.1" in label


def test_domain_resolving_to_fake_ip_allowed(monkeypatch):
    """域名解析全部为 198.18/15（代理假 IP）→ 放行 + fake 标志置位（供如实标注）."""
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "0")
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_FAKE_IP, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    label, ips, host, port, fake = _resolve_checked_ips("https://example.com/x")
    assert label == "" and fake is True and _FAKE_IP in ips
    socket.getaddrinfo = real_getaddrinfo  # 还原（防御）


def test_execute_fake_ip_ok_with_honest_note(monkeypatch):
    """端到端: 假 IP 目标默认可抓取，回执含如实标注（代理假 IP 段已放行）."""
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "0")
    tool = WebFetchTool()
    html = "<html><body><p>正文" + "长" * 60 + "</p></body></html>"

    class _FakeResp:
        status_code = 200
        headers = {}
        text = html
        url = f"http://{_FAKE_IP}/x"
        extensions = {}

        def read(self):
            return html.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.stream.return_value = _FakeResp()
        r = tool.execute(url=f"http://{_FAKE_IP}/x")
    assert r.status == ToolResultStatus.SUCCESS
    assert "代理假 IP" in r.content, f"回执缺如实标注: {r.content[:200]}"
    assert "正文" in r.content


def test_execute_fake_ip_strict_blocks(monkeypatch):
    """严格模式端到端: 198.18/15 → BLOCKED 回执."""
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "1")
    tool = WebFetchTool()
    r = tool.execute(url=f"http://{_FAKE_IP}/x")
    assert r.status == ToolResultStatus.BLOCKED
    assert "198.18" in r.content


def test_verify_peer_tolerates_fake_ip(monkeypatch):
    """连接后对端复核: 对端为假 IP（TUN 模式）→ 不误杀；真实私网对端仍丢弃."""
    from llm_loop.tools.builtin.web_fetch import WebFetchTool as W

    class _Stream:
        def get_extra_info(self, key):
            return (_FAKE_IP, 443)

    class _Resp:
        status_code = 200
        extensions = {"network_stream": _Stream()}
        headers = {}

    resp = _Resp()
    W._verify_peer(resp, "https://example.com/x")  # 假 IP 放行（不抛）
    real = _Stream()
    real.get_extra_info = lambda key: ("10.0.0.1", 80)
    resp2 = _Resp()
    resp2.extensions = {"network_stream": real}
    try:
        W._verify_peer(resp2, "https://example.com/x")
    except Exception as exc:  # noqa: BLE001 — 预期抛 PrivateTargetBlockedError
        assert "内网" in str(exc)
    else:
        raise AssertionError("真实私网对端应被丢弃")


def test_verify_peer_tolerates_loopback_proxy(monkeypatch):
    """对端为本机回环（Surge/Clash 透明代理监听）→ 放行（per-hop 预检查已把关目标）."""
    from llm_loop.tools.builtin.web_fetch import WebFetchTool as W

    class _Stream:
        def get_extra_info(self, key):
            return ("127.0.0.1", 6152)

    class _Resp:
        status_code = 200
        extensions = {"network_stream": _Stream()}
        headers = {}

    W._verify_peer(_Resp(), "https://example.com/x")  # 回环对端放行（不抛）
