"""P2-B 目录服务：MCP Registry 只读发现（设计 §13 / FR-12 / §5.2）.

纪律：
- 只读发现、只生成候选：不自动安装、不自动信任、不执行任何内容；
  安装永远需要显式动作（git/归档源获取见 sources.py）。
- 元数据 ≠ 认证：Registry 元数据（名称/描述/包坐标/fileSha256/status）
  不是代码托管、授权或质量认证；候选的风险与质量由安装者另行核验。
- 可用性如实：API 不可达/HTTP 错误/分页未取尽都如实呈现，不缓存伪装、
  不静默截断。

API（official-registry-api.md / openapi.yaml，docs/reference/api，main@2026-10）：
- GET {base}/v0.1/servers?cursor=&limit=&search= →
  {"servers": [ServerResponse], "metadata": {"nextCursor": str, "count": int}}
- ServerResponse = {"server": {...}, "_meta": {...}}；server 含 name/
  description/website_url/releases[].requirements[].transport_type/
  packages[].{registry_type,identifier,version,file_sha256}/status。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from llm_loop.timekeeping import system_local_now_iso

__all__ = [
    "DEFAULT_REGISTRY_BASE",
    "RegistryCandidate",
    "DirectoryDiscovery",
    "discover_registry_servers",
]

DEFAULT_REGISTRY_BASE = "https://registry.modelcontextprotocol.io"
_API_VERSION = "v0.1"

#: 单次发现的最大页数（防游标循环；如实报告 truncated）
MAX_PAGES = 10


@dataclass(frozen=True)
class RegistryCandidate:
    """目录候选（facts only；不含任何安装/信任判定）."""

    name: str
    description: str
    website_url: str
    latest_version: str
    status: str  # active/deprecated/deleted/unknown（缺省如实标 unknown）
    packages: tuple[dict, ...]  # registry_type/identifier/version/file_sha256
    remote_transports: tuple[str, ...]  # remotes[].transport_type / requirements[].transport_type
    remote_urls: tuple[str, ...] = ()  # remotes[].url（传输端点 facts）
    raw: dict = field(default_factory=dict)

    def summary(self) -> str:
        pkgs = ";".join(
            f"{p.get('registry_type')}:{p.get('identifier')}@{p.get('version')}"
            + (f"+sha256:{sha[:12]}" if (sha := p.get("file_sha256")) else "")
            for p in self.packages
            if isinstance(p, dict)
        )
        transports = ",".join(self.remote_transports) or "-"
        return (
            f"{self.name}（status={self.status}, latest={self.latest_version or '-'}, "
            f"transports={transports}, packages={pkgs or '-'}）"
        )


@dataclass(frozen=True)
class DirectoryDiscovery:
    """一次目录发现的结果（含可用性与来源状态，如实）."""

    ok: bool
    base_url: str
    candidates: tuple[RegistryCandidate, ...]
    page_count: int
    next_cursor: str
    truncated: bool
    availability: str
    fetched_at: str

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "base_url": self.base_url,
            "count": len(self.candidates),
            "page_count": self.page_count,
            "next_cursor": self.next_cursor,
            "truncated": self.truncated,
            "availability": self.availability,
            "fetched_at": self.fetched_at,
            "candidates": [c.raw for c in self.candidates],
        }


def _parse_candidate(entry: dict) -> RegistryCandidate:
    server = entry.get("server")
    if not isinstance(server, dict):
        server = {}
    name = str(server.get("name", "") or "")
    releases = server.get("releases")
    if not isinstance(releases, list):
        releases = []
    latest_version = str(server.get("version", "") or "")
    transports: list[str] = []
    remote_urls: list[str] = []
    for remote in server.get("remotes") or []:
        # 实况形态（2026-10 实连）：remotes[] 携带 type/url（type=传输类型）
        if not isinstance(remote, dict):
            continue
        tt = str(remote.get("transport_type") or remote.get("type") or "")
        if tt and tt not in transports:
            transports.append(tt)
        if remote.get("url"):
            remote_urls.append(str(remote["url"]))
    for rel in releases:
        # 规格形态（openapi.yaml）：releases[].requirements[].transport_type
        if not isinstance(rel, dict):
            continue
        if not latest_version:
            latest_version = str(rel.get("version", "") or "")
        for req in rel.get("requirements") or []:
            if isinstance(req, dict) and req.get("transport_type"):
                tt = str(req["transport_type"])
                if tt not in transports:
                    transports.append(tt)
    packages: list[dict] = []
    for pkg in server.get("packages") or []:
        if isinstance(pkg, dict):
            packages.append(
                {
                    "registry_type": str(pkg.get("registry_type", "") or ""),
                    "identifier": str(pkg.get("identifier", "") or ""),
                    "version": str(pkg.get("version", "") or ""),
                    "file_sha256": str(pkg.get("file_sha256", "") or ""),
                }
            )
    meta = entry.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    official = meta.get("io.modelcontextprotocol.registry/official")
    if not isinstance(official, dict):
        official = {}
    status = str(server.get("status", "") or official.get("status", "") or "unknown") or "unknown"
    return RegistryCandidate(
        name=name,
        description=str(server.get("description", "") or server.get("title", "") or ""),
        website_url=str(server.get("website_url", "") or ""),
        latest_version=latest_version,
        status=status,
        packages=tuple(packages),
        remote_transports=tuple(transports),
        remote_urls=tuple(dict.fromkeys(remote_urls)),
        raw=entry,
    )


def _default_http_get(url: str, timeout_s: float) -> tuple[int, str]:
    """默认 GET（Accept: application/json）；返回 (status, body)."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        return resp.status, resp.read().decode("utf-8", errors="replace")


def discover_registry_servers(
    base_url: str = DEFAULT_REGISTRY_BASE,
    *,
    search: str | None = None,
    page_size: int = 100,
    max_pages: int = MAX_PAGES,
    timeout_s: float = 20.0,
    http_get: Callable[[str], tuple[int, str]] | None = None,
) -> DirectoryDiscovery:
    """只读发现 MCP Registry 服务器清单（候选；不安装、不信任、不执行）.

    ``http_get`` 可注入（测试/代理）；签名 (url) → (status, body)。
    任何失败都收敛为 ok=False 的 DirectoryDiscovery（如实可用性），不抛出。
    """
    fetched_at = system_local_now_iso()
    getter = http_get or (lambda url: _default_http_get(url, timeout_s))
    candidates: list[RegistryCandidate] = []
    cursor = ""
    pages = 0
    while pages < max_pages:
        url = f"{base_url.rstrip('/')}/{_API_VERSION}/servers?limit={int(page_size)}"
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor, safe='')}"
        if search:
            url += f"&search={urllib.parse.quote(search, safe='')}"
        try:
            status, body = getter(url)
        except urllib.error.HTTPError as exc:
            return DirectoryDiscovery(
                ok=False,
                base_url=base_url,
                candidates=tuple(),
                page_count=pages,
                next_cursor=cursor,
                truncated=True,
                availability=f"Registry HTTP {exc.code}（{exc.reason}）；候选不可用，未安装任何内容",
                fetched_at=fetched_at,
            )
        except Exception as exc:  # noqa: BLE001 — 网络/DNS/超时统一如实
            return DirectoryDiscovery(
                ok=False,
                base_url=base_url,
                candidates=tuple(),
                page_count=pages,
                next_cursor=cursor,
                truncated=True,
                availability=f"Registry 不可达（{type(exc).__name__}: {exc}）；候选不可用，未安装任何内容",
                fetched_at=fetched_at,
            )
        if status != 200:
            return DirectoryDiscovery(
                ok=False,
                base_url=base_url,
                candidates=tuple(),
                page_count=pages,
                next_cursor=cursor,
                truncated=True,
                availability=f"Registry HTTP {status}；候选不可用，未安装任何内容",
                fetched_at=fetched_at,
            )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            return DirectoryDiscovery(
                ok=False,
                base_url=base_url,
                candidates=tuple(candidates),
                page_count=pages,
                next_cursor=cursor,
                truncated=True,
                availability=f"Registry 响应非 JSON（{exc}）；已获 {len(candidates)} 条后中止",
                fetched_at=fetched_at,
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("servers"), list):
            return DirectoryDiscovery(
                ok=False,
                base_url=base_url,
                candidates=tuple(candidates),
                page_count=pages,
                next_cursor=cursor,
                truncated=True,
                availability="Registry 响应结构异常（缺 servers 数组）；已获 "
                f"{len(candidates)} 条后中止",
                fetched_at=fetched_at,
            )
        for entry in payload["servers"]:
            if isinstance(entry, dict):
                candidates.append(_parse_candidate(entry))
        pages += 1
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        next_cursor = str(metadata.get("nextCursor", "") or "")
        if not next_cursor:
            return DirectoryDiscovery(
                ok=True,
                base_url=base_url,
                candidates=tuple(candidates),
                page_count=pages,
                next_cursor="",
                truncated=False,
                availability=f"完整（{pages} 页 {len(candidates)} 条；Registry 元数据非认证）",
                fetched_at=fetched_at,
            )
        cursor = next_cursor
    return DirectoryDiscovery(
        ok=True,
        base_url=base_url,
        candidates=tuple(candidates),
        page_count=pages,
        next_cursor=cursor,
        truncated=True,
        availability=f"达单次页数上限 {max_pages}（续读游标已保留；Registry 元数据非认证）",
        fetched_at=fetched_at,
    )
