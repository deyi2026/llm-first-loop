"""net_guard 单一事实源测试（P1-2/S1-4/S2-2，docs/安全审查与修复建议书-2026-10-25.md）.

覆盖：
- ``classify_ip`` 表驱动（私网/回环/链路本地/保留/CGNAT/全球单播/非 IP 字符串）；
- ``check_url``：scheme 白名单、host 为空、IP 字面量、DNS 解析任一命中、解析失败
  fail-open（unresolved）、allowed_hosts 精确/``*.suffix`` 通配、
  ``LFL_NET_ALLOW_PRIVATE``、198.18/15 代理假 IP 例外与严格开关、fail-closed；
- 与 ``web_fetch._blocked_ip_label`` 的同一 IP 表一致性（新旧单一事实源等价证明）；
- 对旧四条件语义的"只收紧不放宽"扫描（嵌入式旧实现对照：边界 + 种子随机样本，
  断言旧拦地址新必拦且标签逐字节一致——S2-2 收紧不得伴随任何放宽）；
- S2-2 端到端：``web_fetch._blocked_private_url`` 对 CGNAT 元数据地址的拦截。

不触网：所有 DNS 路径用 monkeypatch 假解析器或确定性 ``localhost``。
"""

from __future__ import annotations

import ipaddress
import random
import socket

import pytest

from llm_loop.net_guard import (
    browser_allowed_hosts,
    check_url,
    classify_ip,
    parse_host_allowlist,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔离宿主环境的安全开关（测试只在受控开关状态下判定）."""
    for key in (
        "LFL_NET_ALLOW_PRIVATE",
        "LFL_BROWSER_ALLOWED_HOSTS",
        "WEB_FETCH_BLOCK_FAKE_IP",
        "WEB_FETCH_BLOCK_PRIVATE",
    ):
        monkeypatch.delenv(key, raising=False)


# ── classify_ip 表驱动 ──────────────────────────────────────────────────────
# 期望标签按本仓库 venv（Python 3.13）实测地面真值编写；旧实现在这些地址上
# 产生完全相同的标签（见 test_web_fetch_blocked_ip_label_matches_net_guard_table）。
CLASSIFY_TABLE: list[tuple[str, str]] = [
    # 私网 / 回环 / 链路本地 / 保留（旧四条件拦截面，标签逐字节不变）
    ("127.0.0.1", "127.0.0.1（私网）"),  # is_private 优先于 is_loopback（与旧实现一致）
    ("::1", "::1（私网）"),
    ("10.0.0.1", "10.0.0.1（私网）"),
    ("172.16.0.1", "172.16.0.1（私网）"),
    ("192.168.1.1", "192.168.1.1（私网）"),
    ("169.254.169.254", "169.254.169.254（私网）"),  # 云元数据（link-local 也 is_private）
    ("0.0.0.0", "0.0.0.0（私网）"),
    ("fe80::1", "fe80::1（私网）"),
    ("fd00::1", "fd00::1（私网）"),
    ("::ffff:127.0.0.1", "::ffff:127.0.0.1（私网）"),
    ("64:ff9b::1.2.3.4", "64:ff9b::1.2.3.4（保留地址）"),  # is_global=True 但 is_reserved → 并集仍拦
    ("240.0.0.1", "240.0.0.1（私网）"),
    # 全球单播 → 放行
    ("8.8.8.8", ""),
    ("1.1.1.1", ""),
    ("93.184.216.34", ""),
    # S2-2 新增：CGNAT 100.64.0.0/10（旧四条件全 False → 旧实现放行，收紧）
    ("100.64.0.1", "100.64.0.1（CGNAT）"),
    ("100.100.100.200", "100.100.100.200（CGNAT）"),  # 阿里云元数据
    ("100.127.255.255", "100.127.255.255（CGNAT）"),
    ("100.63.255.255", ""),  # 网段外 → 放行
    ("100.128.0.1", ""),
    # 198.18/15：classify_ip 照常给拦截标签；是否按代理假 IP 放行由调用方决定
    ("198.18.0.1", "198.18.0.1（私网）"),
    ("198.19.255.1", "198.19.255.1（私网）"),
    # 非 IP 字符串 → 空串（与旧实现一致）
    ("example.com", ""),
    ("999.1.1.1", ""),
    ("", ""),
]


@pytest.mark.parametrize(("ip", "expected"), CLASSIFY_TABLE)
def test_classify_ip_table(ip, expected):
    assert classify_ip(ip) == expected


# ── check_url ───────────────────────────────────────────────────────────────
def _fake_resolver(monkeypatch, *ips):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _raising_resolver(monkeypatch):
    def boom(host, *args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", boom)


def test_check_url_rejects_non_http_scheme():
    assert check_url("file:///etc/passwd", mode="browser") == (False, "scheme_not_allowed")
    assert check_url("ftp://example.com/x", mode="browser") == (False, "scheme_not_allowed")
    assert check_url("gopher://127.0.0.1/x", mode="browser") == (False, "scheme_not_allowed")


def test_check_url_rejects_missing_host():
    assert check_url("http:///nohost", mode="browser") == (False, "host_missing")
    assert check_url("https://:8080/x", mode="browser") == (False, "host_missing")


def test_check_url_ip_literal_blocked():
    ok, reason = check_url("http://127.0.0.1:8090/console", mode="browser")
    assert ok is False
    assert reason == "ip_blocked:127.0.0.1（私网）"
    ok, reason = check_url("http://[::1]:8090/", mode="browser")
    assert ok is False and reason.startswith("ip_blocked:") and "::1" in reason
    ok, reason = check_url("http://169.254.169.254/latest/meta-data/", mode="browser")
    assert ok is False and "169.254.169.254" in reason


def test_check_url_public_ip_literal_allowed():
    assert check_url("https://8.8.8.8/dns-query", mode="browser") == (True, "")


def test_check_url_cgnat_literal_blocked_s2_2():
    ok, reason = check_url("http://100.100.100.200/latest/meta-data/", mode="browser")
    assert ok is False
    assert reason == "ip_blocked:100.100.100.200（CGNAT）"


def test_check_url_dns_any_hit_blocks(monkeypatch):
    """任一解析地址命中即拒（DNS rebinding 面收窄，与 web_fetch 现状一致）."""
    _fake_resolver(monkeypatch, "93.184.216.34", "10.0.0.7")
    ok, reason = check_url("https://mixed.example/", mode="browser")
    assert ok is False
    assert reason == "dns_blocked:10.0.0.7（私网）"


def test_check_url_dns_all_public_allowed(monkeypatch):
    _fake_resolver(monkeypatch, "93.184.216.34")
    assert check_url("https://example.com/", mode="browser") == (True, "")


def test_check_url_dns_cgnat_blocked_s2_2(monkeypatch):
    _fake_resolver(monkeypatch, "100.100.100.200")
    ok, reason = check_url("https://metadata-alias.example/", mode="browser")
    assert ok is False and "CGNAT" in reason


def test_check_url_unresolved_fail_open(monkeypatch):
    """解析失败 → 放行 + unresolved 标注（与 web_fetch 现状一致，请求阶段如实报错）."""
    _raising_resolver(monkeypatch)
    assert check_url("https://no-such-host.invalid/x", mode="browser") == (True, "unresolved")


def test_check_url_localhost_resolves_to_loopback_blocked():
    """真实解析路径：localhost → 回环地址 → 拒（确定性，不触外网）."""
    ok, reason = check_url("http://localhost:8090/", mode="browser")
    assert ok is False
    assert reason.startswith("dns_blocked:")


def test_check_url_allowed_hosts_exact_and_wildcard():
    assert check_url(
        "http://127.0.0.1:8090/console", mode="browser", allowed_hosts=frozenset({"127.0.0.1"})
    ) == (True, "allowed_host")


def test_check_url_allowed_hosts_wildcard_suffix(monkeypatch):
    _fake_resolver(monkeypatch, "10.0.0.9")
    allowed = frozenset({"*.internal.example"})
    # 子域命中（解析到私网也无妨：显式授权优先，且不做 DNS）
    assert check_url("https://panel.internal.example/", mode="browser", allowed_hosts=allowed) == (
        True,
        "allowed_host",
    )
    # 裸域也覆盖（*.suffix 的标签边界语义，见 net_guard._host_allowed docstring）
    assert check_url("https://internal.example/", mode="browser", allowed_hosts=allowed) == (
        True,
        "allowed_host",
    )
    # 标签边界：notinternal.example 不得被 *.internal.example 吸收
    ok, reason = check_url("https://notinternal.example/", mode="browser", allowed_hosts=allowed)
    assert ok is False and reason == "dns_blocked:10.0.0.9（私网）"


def test_check_url_allowed_host_skips_resolution(monkeypatch):
    _raising_resolver(monkeypatch)
    assert check_url(
        "https://svc.corp.example/", mode="browser", allowed_hosts=frozenset({"*.corp.example"})
    ) == (True, "allowed_host")


def test_check_url_allow_private_param_annotates():
    ok, reason = check_url("http://10.0.0.1/", mode="browser", allow_private=True)
    assert ok is True
    assert reason == "private_allowed:10.0.0.1（私网）"


def test_check_url_env_allow_private_annotates(monkeypatch):
    monkeypatch.setenv("LFL_NET_ALLOW_PRIVATE", "1")
    ok, reason = check_url("http://10.0.0.1/", mode="browser")
    assert ok is True
    assert reason == "private_allowed:10.0.0.1（私网）"


def test_check_url_fake_ip_all_allowed_by_default(monkeypatch):
    """全部解析地址落在 198.18/15 且非严格模式 → 代理假 IP 放行（沿用 web_fetch 现状）."""
    _fake_resolver(monkeypatch, "198.18.13.42")
    assert check_url("https://example.com/", mode="browser") == (True, "fake_ip_proxied")
    assert check_url("http://198.18.0.7/x", mode="browser") == (True, "fake_ip_proxied")


def test_check_url_fake_ip_strict_mode_blocks(monkeypatch):
    monkeypatch.setenv("WEB_FETCH_BLOCK_FAKE_IP", "1")
    _fake_resolver(monkeypatch, "198.18.13.42")
    ok, reason = check_url("https://example.com/", mode="browser")
    assert ok is False and "198.18" in reason


def test_check_url_fake_ip_mixed_with_private_blocks(monkeypatch):
    """混合解析（假 IP + 真实私网）→ 私网拦截语义不变."""
    _fake_resolver(monkeypatch, "198.18.13.42", "10.0.0.8")
    ok, reason = check_url("https://mixed.example/", mode="browser")
    assert ok is False and "10.0.0.8" in reason


def test_check_url_mode_is_required_label():
    with pytest.raises(ValueError):
        check_url("https://example.com/", mode="")


def test_parse_host_allowlist():
    assert parse_host_allowlist(" Example.COM , *.api.Example.org ,, x. ") == frozenset(
        {"example.com", "*.api.example.org", "x"}
    )
    assert parse_host_allowlist("") == frozenset()
    assert parse_host_allowlist(",,,") == frozenset()


def test_browser_allowed_hosts_reads_env(monkeypatch):
    assert browser_allowed_hosts() == frozenset()
    monkeypatch.setenv("LFL_BROWSER_ALLOWED_HOSTS", "127.0.0.1, *.corp.example")
    assert browser_allowed_hosts() == frozenset({"127.0.0.1", "*.corp.example"})


# ── 与 web_fetch 旧实现的一致性（单一事实源等价证明 + 只收紧不放宽）─────────────
def _old_web_fetch_label(ip_str: str) -> str:
    """web_fetch 2026-10-25 之前的旧实现（逐字节复刻，仅作对照基线）."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        kind = (
            "私网"
            if ip.is_private
            else "回环"
            if ip.is_loopback
            else "链路本地"
            if ip.is_link_local
            else "保留地址"
        )
        return f"{ip_str}（{kind}）"
    return ""


BOUNDARY_IPS = [
    "0.0.0.0",
    "0.1.2.3",
    "8.8.8.8",
    "9.255.255.255",
    "10.0.0.1",
    "10.255.255.255",
    "100.63.255.255",
    "100.64.0.0",
    "100.64.0.1",
    "100.100.100.200",
    "100.127.255.255",
    "100.128.0.1",
    "127.0.0.0",
    "127.255.255.255",
    "169.254.0.1",
    "169.254.169.254",
    "169.255.0.1",
    "172.15.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "172.32.0.1",
    "192.0.0.8",
    "192.0.2.1",
    "192.88.99.1",
    "192.168.0.1",
    "192.168.255.255",
    "198.17.255.255",
    "198.18.0.0",
    "198.18.0.1",
    "198.19.255.255",
    "198.20.0.1",
    "198.51.100.1",
    "203.0.113.1",
    "223.255.255.255",
    "224.0.0.1",
    "239.1.1.1",
    "240.0.0.1",
    "255.255.255.255",
    "::",
    "::1",
    "::ffff:0.0.0.0",
    "::ffff:8.8.8.8",
    "::ffff:127.0.0.1",
    "2001:db8::1",
    "2606:4700::1111",
    "fc00::1",
    "fd12:3456::1",
    "fe80::1",
    "ff02::1",
    "64:ff9b::1.2.3.4",
    "2002:0808:0808::1",
]


@pytest.mark.parametrize("ip", BOUNDARY_IPS)
def test_classify_ip_never_loosens_old_blocking(ip):
    """旧实现拦截的地址：新实现必须拦截且标签逐字节一致（零回归）."""
    old = _old_web_fetch_label(ip)
    new = classify_ip(ip)
    if old:
        assert new == old, f"loosened/relabeled: {ip} old={old!r} new={new!r}"


def test_classify_ip_never_loosens_random_sample():
    """种子随机扫描（IPv4/IPv6 全空间 + 定向边界网段）：不允许任何旧拦新放."""
    rng = random.Random(20261025)
    samples = [str(ipaddress.IPv4Address(rng.getrandbits(32))) for _ in range(1500)]
    samples += [str(ipaddress.IPv6Address(rng.getrandbits(128))) for _ in range(1500)]
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "240.0.0.0/4",
        "255.255.255.255/32",
    ):
        network = ipaddress.ip_network(net)
        for _ in range(200):
            samples.append(
                str(ipaddress.IPv4Address(int(network.network_address) + rng.randrange(network.num_addresses)))
            )
    loosened = [
        (ip, _old_web_fetch_label(ip), classify_ip(ip))
        for ip in samples
        if _old_web_fetch_label(ip) and classify_ip(ip) != _old_web_fetch_label(ip)
    ]
    assert not loosened, f"旧拦新放/标签漂移: {loosened[:10]}"


def test_web_fetch_blocked_ip_label_matches_net_guard_table():
    """web_fetch._blocked_ip_label 已委托 net_guard：同一 IP 表判定完全一致."""
    from llm_loop.tools.builtin.web_fetch import _blocked_ip_label

    for ip, expected in CLASSIFY_TABLE:
        assert _blocked_ip_label(ip) == expected == classify_ip(ip), ip


def test_web_fetch_label_equals_net_guard_on_boundaries():
    from llm_loop.tools.builtin.web_fetch import _blocked_ip_label

    for ip in BOUNDARY_IPS:
        assert _blocked_ip_label(ip) == classify_ip(ip), ip


def test_s2_2_web_fetch_now_blocks_cgnat_metadata():
    """S2-2 端到端：阿里云元数据地址经 web_fetch 既有链路被拦（函数级，不触网）."""
    from llm_loop.tools.builtin.web_fetch import _blocked_private_url, _resolve_checked_ips

    label = _blocked_private_url("http://100.100.100.200/latest/meta-data/iam/security-credentials/")
    assert label == "100.100.100.200（CGNAT）"
    reason, _ips, host, _port, fake = _resolve_checked_ips("http://100.100.100.200/x")
    assert reason and "CGNAT" in reason and fake is False and host == "100.100.100.200"


def test_web_fetch_private_blocking_unchanged_on_classic_ranges():
    """既有 SSRF 拦截面（私网/回环/链路本地）语义不变."""
    from llm_loop.tools.builtin.web_fetch import _blocked_private_url

    assert "10.0.0.1" in _blocked_private_url("http://10.0.0.1/x")
    assert "127.0.0.1" in _blocked_private_url("http://127.0.0.1/x")
    assert "169.254.169.254" in _blocked_private_url("http://169.254.169.254/latest/meta-data")
    assert "192.168.1.1" in _blocked_private_url("http://192.168.1.1/admin")
    assert _blocked_private_url("http://8.8.8.8/x") == ""
