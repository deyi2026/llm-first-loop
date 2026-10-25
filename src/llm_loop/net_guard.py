"""统一出站网络目标校验（单一事实源）.

背景（docs/安全审查与修复建议书-2026-10-25.md，P1-2 / S1-4 / S2-2）：
- S1-4/P1-2：browser ``navigate`` 此前只校验 scheme（browser/action.py ``_validate``），
  AI 可直驱 ``http://127.0.0.1:8090`` 读本机 Web 控制面 → 本模块成为 browser 与
  web_fetch 共用的目标闸门；web_fetch 侧仅把纯 IP 分类（``_blocked_ip_label``）
  委托到这里的 ``classify_ip``，其余 198.18/15 代理例外、重定向逐跳复检、连接后
  对端复核逻辑原样保留。
- S2-2：web_fetch 旧四条件（is_private/is_loopback/is_link_local/is_reserved）漏拦
  CGNAT ``100.64.0.0/10``（阿里云元数据 ``100.100.100.200`` 实测四项全 False）→
  ``classify_ip`` 升级为并集语义：``not ip.is_global`` ∪ 旧四条件，对旧行为只收紧、
  不放宽（Python 3.13 实测部分 IPv6 保留段 ``is_reserved=True`` 而 ``is_global=True``，
  如 ``64:ff9b::/96`` NAT64 段，单用 ``not is_global`` 反而会放宽旧拦截，故取并集）。

设计约束：
- 纯标准库；模块导入阶段不读环境变量、不做任何网络解析（环境读取集中在
  ``_env_flag``/``browser_allowed_hosts`` 函数体内，调用时才发生）。
- ``198.18.0.0/15``（RFC 2544 基准段，也是 Surge/Clash fake-ip 代理假地址段）例外
  不在 ``classify_ip`` 内部：由调用方沿用 web_fetch 既有策略——**全部**解析地址落在
  该段且 ``WEB_FETCH_BLOCK_FAKE_IP`` 未设为 1 → 视为代理假 IP 放行（真实连接由代理
  通道完成，reason 如实标注 ``fake_ip_proxied``）；否则按拦截处理。``check_url``
  内置同一例外，使 browser 与 web_fetch 语义一致。
- ``check_url`` 域名解析失败 fail-open（reason 标 ``unresolved``，放行到请求阶段由
  真实网络错误如实暴露，与 web_fetch ``_resolve_checked_ips`` 现状一致）；判定内部
  异常 fail-closed（返回 ``(False, "check_error:...")``，绝不放行）。
- 残余风险（S2-3，如实声明不假装已修）：本模块的 ``getaddrinfo`` 校验与请求方
  （httpx/Chrome）的实际连接是两次独立解析，短 TTL DNS 可在校验后翻转（概率型，
  需攻击者控制目标域名的 DNS）；web_fetch 的 httpx 通道靠连接后对端复核兜底（防
  数据回读，已发出的 GET 无法撤销），curl 通道以 ``--resolve`` 钉住已校验 IP。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterable
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")  # S2-2：共享地址段（含阿里云元数据）
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")  # RFC 2544 / 代理 fake-ip 段
# 环境变量名以字面量出现在各调用点（见 _env_flag docstring），此处不设间接常量。
_TRUTHY = {"1", "on", "true", "yes"}


def _env_flag(name: str, default: str = "0") -> bool:
    """真值环境开关解析（与 web_fetch 既有 flag 语义一致：1/on/true/yes）.

    调用点传字面量 key（不经过模块常量），保证 env 访问审计扫描器
    （scripts/audit_runtime_env.py schema v2）能把每次读取还原为
    可审计的字面量签名，而非 <dynamic> 批量读取。
    """
    raw = os.environ.get(name, default).strip().lower()
    return raw in _TRUTHY


def _blocked_by_union(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """拦截判定 = CGNAT ∪ not is_global ∪ 旧四条件（只收紧不放宽）."""
    if ip.version == 4 and ip in _CGNAT_V4:
        return True
    if not ip.is_global:
        return True
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def classify_ip(ip_str: str) -> str:
    """单个 IP 字符串的出站拦截说明（放行返回空串）.

    语义为 web_fetch 旧 ``_blocked_ip_label`` 的收紧版：命中并集条件即返回
    ``"<ip>（类别）"``，类别优先级 CGNAT > 私网 > 回环 > 链路本地 > 保留地址 >
    非全球单播；``198.18/15`` 仍按"私网"标注（例外放行由调用方处理）。非法 IP
    字符串返回空串（与旧实现一致，由上层解析阶段处理）。
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return ""
    if not _blocked_by_union(ip):
        return ""
    if ip.version == 4 and ip in _CGNAT_V4:
        kind = "CGNAT"
    elif ip.is_private:
        kind = "私网"
    elif ip.is_loopback:
        kind = "回环"
    elif ip.is_link_local:
        kind = "链路本地"
    elif ip.is_reserved:
        kind = "保留地址"
    else:
        kind = "非全球单播"
    return f"{ip_str}（{kind}）"


def _in_fake_ip_network(candidate: str) -> bool:
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return ip.version == 4 and ip in _FAKE_IP_NETWORK


def _host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    """显式授权匹配：精确主机 或 ``*.suffix`` 标签边界后缀匹配.

    ``*.example.com`` 匹配 ``example.com`` 与任意 ``*.example.com`` 子域，但不匹配
    ``notexample.com``（后缀必须落在标签边界上）。大小写不敏感，忽略尾部点。
    """
    for raw in allowed_hosts or ():
        pattern = str(raw).strip().lower().rstrip(".")
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if suffix and (host == suffix or host.endswith(f".{suffix}")):
                return True
        elif host == pattern:
            return True
    return False


def parse_host_allowlist(raw: str) -> frozenset[str]:
    """逗号分隔主机清单 → frozenset（条目小写、去空白与尾部点，空条目丢弃）."""
    entries: list[str] = []
    for item in str(raw or "").split(","):
        item = item.strip().lower().rstrip(".")
        if item:
            entries.append(item)
    return frozenset(entries)


def browser_allowed_hosts() -> frozenset[str]:
    """browser 站点授权清单：``LFL_BROWSER_ALLOWED_HOSTS``（逗号分隔，支持 ``*.suffix``）."""
    return parse_host_allowlist(os.environ.get("LFL_BROWSER_ALLOWED_HOSTS", ""))


def _resolve_candidates(host: str) -> tuple[list[str], bool, bool]:
    """主机 → (候选地址列表, 是否 IP 字面量, 是否解析失败).

    IP 字面量直接返回单元素列表（不做 DNS）；域名 getaddrinfo 全量解析（任一
    地址命中由调用方判定——DNS rebinding 面收窄）；解析失败返回 unresolved=True。
    """
    try:
        ip = ipaddress.ip_address(host)
        return [str(ip)], True, False
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return [], False, True
    candidates: list[str] = []
    for info in infos:
        cand = str(info[4][0])
        if cand not in candidates:
            candidates.append(cand)
    return candidates, False, not candidates


def check_url(
    url: str,
    *,
    mode: str,
    allowed_hosts: frozenset[str] = frozenset(),
    allow_private: bool = False,
) -> tuple[bool, str]:
    """URL 出站目标判定 → (是否放行, reason).

    - 非 http/https → ``(False, "scheme_not_allowed")``；host 为空 → ``(False, "host_missing")``；
    - host 命中 ``allowed_hosts``（精确或 ``*.suffix``）→ 放行（reason ``allowed_host``），
      显式授权优先于一切 DNS 判定；
    - IP 字面量直接 ``classify_ip`` 判定（reason ``ip_blocked:<label>``）；
    - 域名 getaddrinfo 解析后**任一**地址命中即拒（reason ``dns_blocked:<label>``）；
    - 全部地址落在 198.18/15 且 ``WEB_FETCH_BLOCK_FAKE_IP`` 未开启 → 放行
      （reason ``fake_ip_proxied``，沿用 web_fetch 代理 fake-ip 现状）；
    - 解析失败 → 放行但 reason 标 ``unresolved``（fail-open 到请求阶段，与 web_fetch 现状一致）；
    - ``allow_private=True`` 或 ``LFL_NET_ALLOW_PRIVATE=1`` → 私网放行但 reason 前缀
      ``private_allowed:`` 如实标注；
    - 判定内部异常 → ``(False, "check_error:<类型>")`` fail-closed。

    ``mode`` 为调用方标签（如 ``"browser"``），当前不区分行为，仅用于调用点自查；
    非空字符串校验失败直接抛 ``ValueError``（fail-closed 由调用方兜底）。
    """
    if not isinstance(mode, str) or not mode:
        raise ValueError("mode must be a non-empty string (e.g. 'browser')")
    try:
        parsed = urlparse(str(url))
        host = str(parsed.hostname or "").strip().lower()
        if host.endswith("."):
            host = host[:-1]
        scheme = str(parsed.scheme or "").lower()
    except (ValueError, UnicodeError):
        return (False, "url_parse_error")
    if scheme not in _ALLOWED_SCHEMES:
        return (False, "scheme_not_allowed")
    if not host:
        return (False, "host_missing")
    if _host_allowed(host, allowed_hosts):
        return (True, "allowed_host")
    private_allowed = bool(allow_private) or _env_flag("LFL_NET_ALLOW_PRIVATE")
    try:
        candidates, literal, unresolved = _resolve_candidates(host)
    except Exception as exc:  # noqa: BLE001 — 判定内部异常 fail-closed，绝不放行
        return (False, f"check_error:{type(exc).__name__}")
    if unresolved:
        return (True, "unresolved")
    # 198.18/15 代理假 IP 段处理逐分支对齐 web_fetch._resolve_checked_ips：
    # 假 IP 候选不参与常规拦截判定（混合解析时引用真实私网地址拦截，语义不变）；
    # 全部候选为假 IP 且非严格模式 → 放行（代理通道完成真实连接）；严格模式 → 拦截。
    prefix = "ip" if literal else "dns"
    fake_hits = 0
    label = ""
    for cand in candidates:
        if _in_fake_ip_network(cand):
            if _env_flag("WEB_FETCH_BLOCK_FAKE_IP"):
                return (False, f"{prefix}_blocked:{cand}（代理假 IP 段 198.18/15，严格模式拦截）")
            fake_hits += 1
            continue
        label = classify_ip(cand)
        if label:
            break
    if candidates and fake_hits == len(candidates):
        return (True, "fake_ip_proxied")
    if label:
        if private_allowed:
            return (True, f"private_allowed:{label}")
        return (False, f"{prefix}_blocked:{label}")
    return (True, "")
