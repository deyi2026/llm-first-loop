"""browser navigate 站点授权与出站门禁测试（P1-2/S1-4，建议书 2026-10-25）.

只驱动 ``BrowserActionAdapter._validate``（纯函数级静态方法）——不启动浏览器、
不建立任何会话/感知栈。navigate 之外的动作（click 等）不受门禁影响也在此证明。

环境契约：默认（无 LFL_BROWSER_ALLOWED_HOSTS）拒绝私网/回环/CGNAT/保留目标；
``LFL_BROWSER_ALLOWED_HOSTS``（逗号分隔，支持 ``*.suffix``）显式放行；闸门内部
异常 fail-closed（拒绝导航而非放行）。
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

import llm_loop.browser.action as action_module
from llm_loop.browser.action import BrowserActionAdapter


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "LFL_BROWSER_ALLOWED_HOSTS",
        "LFL_NET_ALLOW_PRIVATE",
        "WEB_FETCH_BLOCK_FAKE_IP",
        "WEB_FETCH_BLOCK_PRIVATE",
    ):
        monkeypatch.delenv(key, raising=False)


def _fake_resolver(monkeypatch, *ips):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _navigate_action(url: str, action_id: str = "nav-policy-1") -> dict[str, Any]:
    """最小合法 navigate SemanticAction（满足 _MUTATION_CONTRACT 全部字段约束）."""
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": "page-1",
        "action_id": action_id,
        "verb": "navigate",
        "target_id": "page-1",
        "args": {"url": url},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": "snap-1",
        "version_scope": "resource",
        "version_precondition": "required",
    }


def test_navigate_loopback_blocked_by_default():
    """S1-4 实证缺口：navigate http://127.0.0.1:8090（本机 Web 控制面）默认拒绝."""
    err = BrowserActionAdapter._validate(_navigate_action("http://127.0.0.1:8090/console"))
    assert err is not None
    assert err == "navigate_host_blocked:ip_blocked:127.0.0.1（私网）"


def test_navigate_cloud_metadata_blocked():
    err = BrowserActionAdapter._validate(
        _navigate_action("http://169.254.169.254/latest/meta-data/iam/security-credentials/")
    )
    assert err is not None and err.startswith("navigate_host_blocked:ip_blocked:")
    assert "169.254.169.254" in err


def test_navigate_cgnat_metadata_blocked_s2_2():
    err = BrowserActionAdapter._validate(_navigate_action("http://100.100.100.200/latest/meta-data/"))
    assert err == "navigate_host_blocked:ip_blocked:100.100.100.200（CGNAT）"


def test_navigate_ipv6_loopback_blocked():
    err = BrowserActionAdapter._validate(_navigate_action("http://[::1]:8090/"))
    assert err is not None and err.startswith("navigate_host_blocked:ip_blocked:")
    assert "::1" in err


def test_navigate_private_dns_target_blocked(monkeypatch):
    _fake_resolver(monkeypatch, "192.168.1.10")
    err = BrowserActionAdapter._validate(_navigate_action("http://router.local/"))
    assert err == "navigate_host_blocked:dns_blocked:192.168.1.10（私网）"


def test_navigate_localhost_blocked():
    """真实解析路径：localhost → 回环（确定性，不触外网）."""
    err = BrowserActionAdapter._validate(_navigate_action("http://localhost:8090/"))
    assert err is not None and err.startswith("navigate_host_blocked:dns_blocked:")


def test_navigate_file_scheme_rejected_by_existing_check():
    """file:// 仍由既有 scheme 校验先拒绝（门禁不改既有序列）."""
    err = BrowserActionAdapter._validate(_navigate_action("file:///etc/passwd"))
    assert err == "navigate_url_scheme_rejected"


def test_navigate_userinfo_rejected_by_existing_check():
    err = BrowserActionAdapter._validate(_navigate_action("http://user:pass@8.8.8.8/"))
    assert err == "navigate_url_credentials_rejected"


def test_navigate_public_https_allowed(monkeypatch):
    """公网 https 放行（公网 IP 字面量：确定性，无 DNS）."""
    assert BrowserActionAdapter._validate(_navigate_action("https://8.8.8.8/")) is None


def test_navigate_public_domain_allowed_with_public_resolution(monkeypatch):
    _fake_resolver(monkeypatch, "93.184.216.34")
    assert BrowserActionAdapter._validate(_navigate_action("https://example.com/x")) is None


def test_navigate_unresolved_domain_fail_open(monkeypatch):
    """域名解析失败 fail-open（unresolved 标注，请求阶段如实报错，与 web_fetch 现状一致）."""

    def boom(host, *args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert BrowserActionAdapter._validate(_navigate_action("https://offline.invalid/x")) is None


def test_navigate_allowlist_env_allows_loopback(monkeypatch):
    monkeypatch.setenv("LFL_BROWSER_ALLOWED_HOSTS", "127.0.0.1")
    assert BrowserActionAdapter._validate(_navigate_action("http://127.0.0.1:8090/console")) is None


def test_navigate_allowlist_wildcard_allows_private_subdomain(monkeypatch):
    monkeypatch.setenv("LFL_BROWSER_ALLOWED_HOSTS", "*.corp.example")
    _fake_resolver(monkeypatch, "10.0.0.9")
    assert BrowserActionAdapter._validate(_navigate_action("http://panel.corp.example/")) is None


def test_navigate_allowlist_wildcard_label_boundary(monkeypatch):
    """*.corp.example 不得吸收 evilcorp.example（后缀必须落在标签边界）."""
    monkeypatch.setenv("LFL_BROWSER_ALLOWED_HOSTS", "*.corp.example")
    _fake_resolver(monkeypatch, "10.0.0.9")
    err = BrowserActionAdapter._validate(_navigate_action("http://evilcorp.example/"))
    assert err == "navigate_host_blocked:dns_blocked:10.0.0.9（私网）"


def test_navigate_allowlist_exact_private_domain(monkeypatch):
    monkeypatch.setenv("LFL_BROWSER_ALLOWED_HOSTS", "router.local")
    _fake_resolver(monkeypatch, "192.168.1.10")
    assert BrowserActionAdapter._validate(_navigate_action("http://router.local/")) is None


def test_navigate_net_allow_private_env(monkeypatch):
    monkeypatch.setenv("LFL_NET_ALLOW_PRIVATE", "1")
    err = BrowserActionAdapter._validate(_navigate_action("http://10.0.0.1/"))
    assert err is None  # 私网放行（reason 仅在 check_url 层标注 private_allowed:）


def test_navigate_fake_ip_literal_follows_proxy_policy(monkeypatch):
    """198.18/15 字面量沿用 web_fetch 现状：默认代理假 IP 放行，严格模式拦截."""
    assert BrowserActionAdapter._validate(_navigate_action("http://198.18.0.7/x")) is None
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "1")
    err = BrowserActionAdapter._validate(_navigate_action("http://198.18.0.7/x"))
    assert err is not None and err.startswith("navigate_host_blocked:ip_blocked:")


def test_navigate_gate_fails_closed_on_internal_error(monkeypatch):
    """闸门自身异常必须拒绝导航（fail-closed），不得放行到本机/内网控制面."""
    def boom(*args, **kwargs):
        raise RuntimeError("net guard exploded")

    monkeypatch.setattr(action_module, "check_url", boom)
    err = BrowserActionAdapter._validate(_navigate_action("https://example.com/x"))
    assert err == "navigate_host_blocked:check_error:RuntimeError"


def test_click_action_not_gated():
    """非 navigate 动作不走出站门禁（click 全字段合法 → 校验通过）."""
    click = {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": "page-1",
        "action_id": "click-policy-1",
        "verb": "click",
        "target_id": "btn-1",
        "args": {},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": "snap-1",
        "version_scope": "object",
        "version_precondition": "required",
    }
    assert BrowserActionAdapter._validate(click) is None
