"""MCP 协议层（纯逻辑，无 IO）— DESIGN-20261009 §6/§11 P1-B.

职责：协议版本/时代、版本协商、现代（2026-07-28）与旧时代
（2024-11-05 → 2025-11-25）请求构造与结果解释。不接触进程与网络。

现代时代（2026-07-28）关键契约（modelcontextprotocol.io 官方规范）：
- 无 initialize 握手；每次请求在 params._meta 携带版本与身份：
  io.modelcontextprotocol/protocolVersion、clientInfo、clientCapabilities。
- 服务器 MUST 实现 server/discover（DiscoverResult.supportedVersions）。
- 版本不支持 → UnsupportedProtocolVersionError（data.supported 列表）→
  属"已识别现代错误"：按列表选版本重试，不回退旧握手。
- HTTP：每请求 POST，header Mcp-Method/Mcp-Name/MCP-Protocol-Version
  （须与 _meta 一致）；无会话（Mcp-Session-Id 已移除）。
- 订阅：subscriptions/listen（types 选择），通知带 _meta.subscriptionId。

旧时代（legacy）：initialize 握手（版本在 params.protocolVersion）+
notifications/initialized；HTTP 为 Streamable HTTP（Mcp-Session-Id 会话头）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── 类型化错误（P0 语义保持；供传输层与适配层共用）──────────────────────


class McpError(RuntimeError):
    """MCP 通道/协议错误基类."""


class McpNotDispatchedError(McpError):
    """请求确认未派发（进程已退出/连接拒绝）→ 唯一可安全重连重放的路径."""


class McpOutcomeUnknownError(McpError):
    """请求已派发但结果未知（超时/写半失败）→ 禁止自动重放（防重复副作用）."""


class McpProtocolError(McpError):
    """服务器以 JSON-RPC error 明确拒绝（派发已确认，不重放）.

    error: 原始 JSON-RPC error 对象（可能为 None）；era 判定用
    （如 data.supported → UnsupportedProtocolVersionError）。
    """

    def __init__(self, message: str, error: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error = error


# ── 版本与时代 ────────────────────────────────────────────────────────

MODERN_ERA = "modern"
LEGACY_ERA = "legacy"

#: 现代（无握手、逐请求 _meta）协议版本，按偏好排序。
MODERN_VERSIONS: list[str] = ["2026-07-28"]

#: 旧时代（initialize 握手）协议版本，按偏好排序。
LEGACY_VERSIONS: list[str] = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]

#: 本客户端明确支持集（设计文档 §6.2 SDK 资格建议的最低集）。
SUPPORTED_VERSIONS: list[str] = MODERN_VERSIONS + LEGACY_VERSIONS

_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
META_SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"


@dataclass
class ProtocolProfile:
    """一次连接协商出的协议形态（服务器属性，进程生命期/HTTP origin 内稳定）."""

    era: str  # MODERN_ERA | LEGACY_ERA
    version: str
    server_info: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    #: modern：server/discover 报告的服务器支持版本全集；legacy：协商用集合
    server_supported_versions: list[str] = field(default_factory=list)
    #: legacy HTTP：initialize 响应携带的 Mcp-Session-Id（现代无会话）
    http_session_id: str | None = None

    @property
    def is_modern(self) -> bool:
        return self.era == MODERN_ERA

    def supports(self, capability: str) -> bool:
        """服务器能力宣告判定（P2-B：resources/prompts）.

        MCP 语义：capabilities 对象中键存在即宣告支持（值可为 {} 或
        选项对象，如 resources: {subscribe: true}）。缺键 = 未宣告，
        调用对应方法应如实报"未支持能力"而非服务器无能力（§7.1）。
        """
        return isinstance(self.capabilities, dict) and capability in self.capabilities

    def describe(self) -> str:
        kind = "现代（无握手，逐请求 _meta）" if self.is_modern else "旧时代（initialize 握手）"
        return f"MCP {kind} 版本 {self.version}"


def is_known_version(version: Any) -> bool:
    return isinstance(version, str) and version in SUPPORTED_VERSIONS


def select_mutual_version(supported: list[Any]) -> str | None:
    """按本客户端偏好序，从服务器支持列表选双方共同支持的最高版本."""
    valid = [v for v in (supported or []) if is_known_version(v)]
    for pref in SUPPORTED_VERSIONS:
        if pref in valid:
            return pref
    return None


def select_mutual_modern_version(supported: list[Any]) -> str | None:
    valid = [v for v in (supported or []) if isinstance(v, str) and v in MODERN_VERSIONS]
    for pref in MODERN_VERSIONS:
        if pref in valid:
            return pref
    return None


def extract_supported_versions(error: dict[str, Any]) -> list[str] | None:
    """识别 UnsupportedProtocolVersionError：JSON-RPC error.data.supported 列表."""
    if not isinstance(error, dict):
        return None
    data = error.get("data")
    if isinstance(data, dict):
        supported = data.get("supported")
        if isinstance(supported, list) and supported and all(
            isinstance(v, str) and _VERSION_RE.match(v) for v in supported
        ):
            return [str(v) for v in supported]
    message = str(error.get("message") or "")
    if "UnsupportedProtocolVersion" in message or "protocol version" in message.lower():
        # 有信号但无结构化列表：返回空列表交由上层报协议错误
        return []
    return None


# ── 请求元数据（现代）与握手（旧时代）构造 ────────────────────────────


def client_identity() -> dict[str, str]:
    try:
        from importlib.metadata import version

        return {"name": "llm-first-loop", "version": version("llm-loop")}
    except Exception:  # noqa: BLE001 — 未安装环境（源码运行）退回开发标识
        return {"name": "llm-first-loop", "version": "0.0.0+source"}


def modern_request_meta(version: str) -> dict[str, Any]:
    """现代协议逐请求 _meta（版本 + 客户端身份 + 能力）."""
    return {
        META_VERSION: version,
        META_CLIENT_INFO: client_identity(),
        META_CLIENT_CAPABILITIES: {},
    }


def with_modern_meta(version: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """将现代 _meta 合入 params（不覆盖调用方已有的其他 _meta 键）."""
    merged = dict(params or {})
    meta = dict(merged.get("_meta") or {})
    meta.update(modern_request_meta(version))
    merged["_meta"] = meta
    return merged


def build_discover_request(msg_id: int, version: str) -> dict[str, Any]:
    """server/discover 请求（era 探测首选；服务器 MUST 实现）."""
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "server/discover",
        "params": {"_meta": modern_request_meta(version)},
    }


def parse_discover_result(result: Any) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """解析 DiscoverResult → (supportedVersions, capabilities, serverInfo).

    serverInfo 允许出现在顶层或 result._meta（2026-07-28：服务器应在每个
    结果的 _meta 标识自己）；两者都缺失时返回空 dict（fail-open）。
    """
    if not isinstance(result, dict):
        raise McpProtocolError(f"server/discover 结果不是对象: {type(result).__name__}")
    supported = result.get("supportedVersions")
    if not isinstance(supported, list) or not supported:
        raise McpProtocolError(f"server/discover 缺少 supportedVersions: {result!r:.200}")
    raw_caps = result.get("capabilities")
    capabilities = raw_caps if isinstance(raw_caps, dict) else {}
    raw_meta = result.get("_meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    raw_info = result.get("serverInfo") or meta.get(META_SERVER_INFO) or {}
    server_info = raw_info if isinstance(raw_info, dict) else {}
    return [str(v) for v in supported], capabilities, server_info


def build_initialize_request(msg_id: int, version: str) -> dict[str, Any]:
    """旧时代 initialize 握手请求."""
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": client_identity(),
        },
    }


def negotiate_initialize_result(result: Any, offered: str) -> str:
    """旧时代版本协商：服务器返回其版本；不在本客户端支持集 → 协议错误.

    （MCP legacy 语义：服务器不支持客户端版本时返回自身版本，由客户端裁决。）
    """
    if not isinstance(result, dict):
        raise McpProtocolError(f"initialize 结果不是对象: {type(result).__name__}")
    server_version = result.get("protocolVersion")
    if not isinstance(server_version, str) or not _VERSION_RE.match(server_version):
        raise McpProtocolError(f"initialize 结果缺少有效 protocolVersion: {result!r:.200}")
    if server_version != offered and not is_known_version(server_version):
        raise McpProtocolError(
            f"服务器仅支持未知协议版本 {server_version!r}（本端支持: {SUPPORTED_VERSIONS}）"
        )
    return server_version


def build_list_tools_request(msg_id: int, cursor: str | None, profile: ProtocolProfile) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cursor:
        params["cursor"] = cursor
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": params}


def build_call_tool_request(
    msg_id: int, name: str, arguments: dict[str, Any], profile: ProtocolProfile
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name, "arguments": arguments or {}}
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": params}


def build_subscribe_request(msg_id: int, types: list[str], profile: ProtocolProfile) -> dict[str, Any]:
    """现代 subscriptions/listen（长驻；stdio 下通知以 _meta.subscriptionId 标记）."""
    params: dict[str, Any] = {"types": list(types)}
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "subscriptions/listen", "params": params}


# ── P2-B：resources / prompts（FR-11）──────────────────────────────────


def build_list_resources_request(
    msg_id: int, cursor: str | None, profile: ProtocolProfile
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cursor:
        params["cursor"] = cursor
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "resources/list", "params": params}


def build_read_resource_request(msg_id: int, uri: str, profile: ProtocolProfile) -> dict[str, Any]:
    params: dict[str, Any] = {"uri": uri}
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "resources/read", "params": params}


def build_list_resource_templates_request(
    msg_id: int, cursor: str | None, profile: ProtocolProfile
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cursor:
        params["cursor"] = cursor
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "resources/templates/list",
        "params": params,
    }


def build_list_prompts_request(
    msg_id: int, cursor: str | None, profile: ProtocolProfile
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cursor:
        params["cursor"] = cursor
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "prompts/list", "params": params}


def build_get_prompt_request(
    msg_id: int,
    name: str,
    arguments: dict[str, Any] | None,
    profile: ProtocolProfile,
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name}
    if arguments:
        params["arguments"] = arguments
    if profile.is_modern:
        params = with_modern_meta(profile.version, params)
    return {"jsonrpc": "2.0", "id": msg_id, "method": "prompts/get", "params": params}


def build_cancel_notification(request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": request_id},
    }


def parse_notification(msg: Any) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """解析无 id 帧 → (method, params, subscriptionId)（非通知返回 (None,..)）."""
    if not isinstance(msg, dict) or msg.get("id") is not None or "method" not in msg:
        return None, None, None
    method = str(msg.get("method") or "")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params, dict) else None
    sub_id = meta.get(META_SUBSCRIPTION_ID) if isinstance(meta, dict) else None
    return method, params, (str(sub_id) if sub_id is not None else None)


def encode_header_value(value: str) -> str:
    """MCP header 值编码：非 ASCII 安全值用 =?base64?...?= 哨兵（2026-07-28）."""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        import base64

        return f"=?base64?{base64.b64encode(value.encode('utf-8')).decode('ascii')}?="
