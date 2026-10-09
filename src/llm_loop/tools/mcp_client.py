"""MCP 客户端接入（P3-1，2026-08-15；P0 契约保真修复 2026-10-09）.

`MCP_SERVERS` env JSON 配置 stdio MCP 服务器；启动时连接握手 + 拉取工具清单，
以 `mcp_<server>_<tool>` 名注册进 ToolRegistry（LLM 协议工具名约束
`^[a-zA-Z0-9_-]+$`，原始 `mcp.<server>.<tool>` 中的点号替换为下划线；同批次
归一名冲突时追加原始身份的确定性 digest 后缀），执行走统一注册表通道（线程
超时 / 输出分层 / 审计复用），结果五态包装（success / failure / blocked /
timeout / error，对齐 ToolResultStatus）。

契约保真（P0，2026-10-09）：
- inputSchema 原样透传为 parameters：保留 $defs/oneOf/additionalProperties 等任意
  JSON Schema 关键字，仅补齐 provider 侧最低 object 骨架，不重建、不删键
- 工具结果保真：模型视图保留全部 text 块，非 text 块 / structuredContent /
  result._meta 以指针标注（digest 可对回原始），原始 result 存
  McpTool.last_raw_result；shadow 上下文开启时同步进 raw_observation
- typed 错误：McpNotDispatchedError（未派发→重试安全）/ McpOutcomeUnknownError
  （已派发、结果未知→禁止自动重放）/ McpProtocolError（服务器 JSON-RPC error）；
  均继承 McpError(RuntimeError)，兼容既有 except RuntimeError 路径

诚实边界（fail-open）：
- 服务器启动/握手失败 → 该服务器工具不注册，其余服务器/工具不受影响（日志如实）
- 调用时仅"确认未派发"（写入前进程已退出）才重连重试一次；派发后超时/断连按
  结果未知处理，不自动重放（防重复副作用），ERROR 态如实回执
- 工具返回 isError=True → FAILURE 态（content 原样透传）

分层与双时代（P1-B，2026-10-09）：
- mcp_protocol（纯逻辑）：版本/时代协商、请求构造（现代 2026-07-28 逐请求
  _meta；旧时代 initialize 握手）
- mcp_transport（IO）：StdioTransport（newline-delimited JSON-RPC 子进程）与
  HttpTransport（Streamable HTTP：现代单端点 POST + Mcp-Method/Mcp-Name/
  MCP-Protocol-Version 头；旧时代 Mcp-Session-Id 会话 + 202 通知 + SSE）
- 本模块：era 判定（server/discover 探测；非现代错误/超时才回退旧握手）、
  tools/list 游标分页聚合、tools/list_changed 目录版本观察（stale），
  现代连接 subscriptions/listen 常驻订阅（stdio fire-and-forget；HTTP
  X-Subscription-Id + 常驻 GET 流），connection_epoch 连接代际（重连递增，
  旧代通知按代际丢弃并记 adapter 事件；请求 id 跨重连绝不重置），
  registry 级 catalog_epoch（注册/刷新/list_changed/配置清理均推进，
  供 P1-C 装配点失效判定），
  以及 P0 typed 恢复语义（未派发→重连重放一次；HTTP 旧会话 404 视作
  未处理→重握手重放一次；结果未知/协议错误不重放）
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import re
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_evidence_shadow_enabled
from llm_loop.tools.mcp_auth import EnvSecretStore, McpOAuthClient
from llm_loop.tools.mcp_protocol import (  # typed 错误（P0 语义；本模块导入路径兼容）
    LEGACY_ERA,
    LEGACY_VERSIONS,
    MODERN_ERA,
    MODERN_VERSIONS,
    McpError,
    McpNotDispatchedError,
    McpOutcomeUnknownError,
    McpProtocolError,
    ProtocolProfile,
    build_call_tool_request,
    build_discover_request,
    build_get_prompt_request,
    build_initialize_request,
    build_list_prompts_request,
    build_list_resource_templates_request,
    build_list_resources_request,
    build_list_tools_request,
    build_read_resource_request,
    build_subscribe_request,
    extract_supported_versions,
    negotiate_initialize_result,
    parse_discover_result,
    select_mutual_modern_version,
    with_modern_meta,
)
from llm_loop.tools.mcp_transport import (
    PROBE_TIMEOUT_S,
    HttpTransport,
    LegacySseTransport,
    McpHttpError,
    McpTransport,
    StdioTransport,
)

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"  # 兼容常量（旧时代最早版本）
_CALL_TIMEOUT_S = 120.0
_HANDSHAKE_TIMEOUT_S = 15.0
_MAX_LIST_PAGES = 1000  # tools/list 游标分页防循环上限

# LLM 协议工具名约束（OpenAI 兼容: ^[a-zA-Z0-9_-]+$）——mcp.<server>.<tool> 含点号
# 会被提供方 400 拒绝，注册名统一替换为下划线；底层 MCP 调用仍用原始 tool 名。
_REGISTRY_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")

# ── registry 级目录 epoch + adapter 事件（设计 §7.3；与 P1-C 装配协同） ──
# catalog epoch：MCP 工具目录空间的进程级单调递增版本。凡使"注册表中可见的
# MCP 工具集可能变化"的事件（注册/热刷新/服务器宣告 tools/list_changed/
# 配置移除清理）都必须推进它；P1-C 装配点在装配前后比对即可判定失效，
# 无需自行订阅每个服务器的目录版本。
_CATALOG_LOCK = threading.Lock()
_CATALOG_EPOCH = 0
#: adapter 事件环形缓冲（代际丢弃等诊断事实；不替日志，只留结构化最近事实）
_ADAPTER_EVENTS: deque[dict[str, Any]] = deque(maxlen=64)


def catalog_epoch() -> int:
    """registry 级目录 epoch（单调递增；P1-C 装配失效判据）."""
    with _CATALOG_LOCK:
        return _CATALOG_EPOCH


def adapter_events() -> tuple[dict[str, Any], ...]:
    """最近 adapter 事件快照（如旧代际通知被丢弃；只读拷贝）."""
    with _CATALOG_LOCK:
        return tuple(_ADAPTER_EVENTS)


def _record_adapter_event(kind: str, server: str, detail: str) -> None:
    event = {"kind": kind, "server": server, "detail": detail}
    with _CATALOG_LOCK:
        _ADAPTER_EVENTS.append(event)
    logger.info("MCP adapter 事件 [%s] %s: %s", kind, server, detail)


def _advance_catalog_epoch(reason: str, server: str | None = None) -> None:
    """推进目录 epoch（任意 MCP 目录可见性变化后调用）."""
    global _CATALOG_EPOCH
    with _CATALOG_LOCK:
        _CATALOG_EPOCH += 1
    logger.debug(
        "MCP 目录 epoch → %d（%s%s）", _CATALOG_EPOCH, reason, f"，{server}" if server else ""
    )


def _reset_catalog_state_for_tests() -> None:
    """测试隔离：清零 epoch 与 adapter 事件缓冲（仅供测试调用）."""
    global _CATALOG_EPOCH
    with _CATALOG_LOCK:
        _CATALOG_EPOCH = 0
        _ADAPTER_EVENTS.clear()


def _registry_name(server_name: str, tool_name: str) -> str:
    """注册表工具名（协议合法）：mcp.<server>.<tool> → mcp_<server>_<tool>（非法字符 → _）."""
    return _REGISTRY_NAME_RE.sub("_", f"mcp.{server_name}.{tool_name}")


def _mcp_identity(server_name: str, tool_name: str) -> str:
    """工具原始身份（保留大小写与点号）：mcp.<server>.<tool>."""
    return f"mcp.{server_name}.{tool_name}"


def _digest_suffix(identity: str, width: int = 8) -> str:
    """原始身份的确定性 digest 后缀（同输入同名，跨进程稳定）."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:width]


def _assign_registry_names(
    server_name: str, tool_defs: list[McpToolDef], occupied: dict[str, str | None]
) -> dict[str, str]:
    """为本服务器批次的每个工具分配防碰撞注册名.

    Args:
        occupied: 现有注册名 → 该名当前持有者的 mcp 身份（非 McpTool 持有者为
            None）。规则：基础名空闲、或已被同一身份持有（幂等重注册）→ 用基础
            名；被不同身份持有（如服务器 a.b 与 a_b 归一后同名）→ 追加本身份的
            确定性 digest 后缀（宽度按需加宽，封顶 64 hex）。
    """
    taken = dict(occupied)
    assigned: dict[str, str] = {}
    for tool_def in tool_defs:
        identity = _mcp_identity(server_name, tool_def.name)
        base = _registry_name(server_name, tool_def.name)
        name = base
        width = 8
        while taken.get(name) not in (None, identity) and width < 64:
            width = min(width + 4, 64)
            name = f"{base}_{_digest_suffix(identity, width)}"
        assigned[tool_def.name] = name
        taken[name] = identity
    return assigned


def _result_digest(result: dict[str, Any]) -> str:
    """原始 result 的确定性摘要指纹（模型视图指针用，12 hex）."""
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class McpServerSpec:
    """MCP 服务器配置（MCP_SERVERS JSON 条目）."""

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    type: str = "stdio"  # "stdio" | "http"（Streamable HTTP）
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    credential_ref: str | None = None  # FR-05：env:VAR 引用（缺凭证可诊断）


@dataclass
class McpToolDef:
    """MCP 工具清单条目（tools/list 结果）."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


def parse_servers(raw: str) -> list[McpServerSpec]:
    """MCP_SERVERS 解析（JSON 数组；非法条目 warning + 跳过，如实标注）."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("MCP_SERVERS JSON 解析失败，MCP 工具未加载: %s", exc)
        return []
    if not isinstance(data, list):
        logger.warning(
            "MCP_SERVERS 必须为 JSON 数组（当前 %s），MCP 工具未加载", type(data).__name__
        )
        return []
    out: list[McpServerSpec] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("MCP_SERVERS[%d] 非对象，跳过", i)
            continue
        name = str(item.get("name", "")).strip()
        enabled = bool(item.get("enabled", True))
        server_type = str(item.get("type", "stdio")).strip().lower() or "stdio"
        if server_type == "http":
            url = str(item.get("url", "")).strip()
            if not url:
                logger.warning("MCP_SERVERS[%d]（%s）http 类型缺 url，跳过", i, name)
                continue
            raw_headers = item.get("headers")
            headers = raw_headers if isinstance(raw_headers, dict) else {}
            out.append(
                McpServerSpec(
                    name=name,
                    command="",
                    type="http",
                    url=url,
                    headers={str(k): str(v) for k, v in headers.items()},
                    credential_ref=str(item.get("credential_ref") or "").strip() or None,
                    enabled=enabled,
                )
            )
            continue
        if server_type == "sse":
            # P2-B：legacy HTTP+SSE 旧传输（设计 §3/T04）——显式选择才启用，
            # 无自动回退；凭证（headers）仅发往与 SSE 端点同 origin 的消息端点
            # （跨 origin 端点由传输层 fail-closed 拒绝）。
            url = str(item.get("url", "")).strip()
            if not url:
                logger.warning("MCP_SERVERS[%d]（%s）sse 类型缺 url，跳过", i, name)
                continue
            raw_headers = item.get("headers")
            headers = raw_headers if isinstance(raw_headers, dict) else {}
            out.append(
                McpServerSpec(
                    name=name,
                    command="",
                    type="sse",
                    url=url,
                    headers={str(k): str(v) for k, v in headers.items()},
                    credential_ref=str(item.get("credential_ref") or "").strip() or None,
                    enabled=enabled,
                )
            )
            continue
        if server_type != "stdio":
            logger.warning("MCP_SERVERS[%d]（%s）未知 type %r，跳过", i, name, server_type)
            continue
        command = str(item.get("command", "")).strip()
        if not name or not command:
            logger.warning("MCP_SERVERS[%d] 缺 name/command，跳过", i)
            continue
        out.append(
            McpServerSpec(
                name=name,
                command=command,
                args=[str(a) for a in item.get("args", []) if isinstance(a, str)],
                env={str(k): str(v) for k, v in (item.get("env") or {}).items()},
                enabled=enabled,
            )
        )
    return out


class McpConnection:
    """一个 MCP 服务器的连接编排（stdio 子进程或 Streamable HTTP 端点）.

    P1-B：进程/网络 IO 下沉到 mcp_transport，协议构造/协商下沉到
    mcp_protocol；本类负责 era 判定与版本协商（server/discover 探测，
    非现代错误或 stdio 探测超时才回退旧 initialize 握手）、tools/list
    游标分页聚合、tools/list_changed 目录版本观察（stale/list_revision），
    以及 P0 typed 恢复语义：

    - McpNotDispatchedError（未派发）→ close+connect 后重放一次；
    - 旧时代 HTTP 会话 404（请求未被处理）→ 重握手后重放一次；
    - McpOutcomeUnknownError / McpProtocolError → 如实上抛，不自动重放。
    """

    def __init__(
        self,
        spec: McpServerSpec,
        call_timeout: float = _CALL_TIMEOUT_S,
        probe_timeout_s: float | None = None,
    ) -> None:
        self.spec = spec
        self._call_timeout = call_timeout
        # era 探测等待上限（测试可缩短；默认 PROBE_TIMEOUT_S）
        self._probe_timeout_override = probe_timeout_s
        self._next_id = 1
        self._closed = False
        self.profile: ProtocolProfile | None = None
        self._list_revision = 0
        self._stale = False
        # 连接代际（设计 §7.3）：每次建立新通道（connect/重连/测试 _start_process）
        # 递增；旧代通道晚到的通知按代际丢弃并记 adapter 事件。
        self._connection_epoch = 0
        if spec.type == "http":
            transport: McpTransport = HttpTransport(spec.name, spec.url, spec.headers)
            assert isinstance(transport, HttpTransport)
            # FR-05：HTTP 连接挂 OAuth 客户端（credential_ref 绑定授权身份；
            # 缺凭证在首次 401 时可诊断，不静默降级）
            transport.oauth = McpOAuthClient(
                spec.name,
                spec.url,
                secret_store=EnvSecretStore(),
                credential_ref=spec.credential_ref,
            )
            self.transport = transport
        elif spec.type == "sse":
            # P2-B：legacy HTTP+SSE 显式旧传输（§3/T04）；凭证走 headers
            # （同 origin 强校验由传输层保证），不挂 OAuth（旧传输无此流程）。
            self.transport = LegacySseTransport(spec.name, spec.url, spec.headers)
        else:
            self.transport = StdioTransport(spec.name, spec.command, spec.args, spec.env)
        self.transport.notification_handler = self._on_notification

    # ── 目录版本（listChanged 观察；供上层惰性重拉） ──
    @property
    def list_revision(self) -> int:
        """目录版本：观察到 tools/list_changed 即 +1（未观察到恒为 0）."""
        return self._list_revision

    @property
    def stale(self) -> bool:
        """服务器已宣告 tools/list_changed 且尚未重新拉取清单."""
        return self._stale

    @property
    def connection_epoch(self) -> int:
        """当前连接代际（§5.4 绑定身份要素；每次重连递增，绝不回退）."""
        return self._connection_epoch

    @property
    def transport_kind(self) -> str:
        return self.spec.type

    def _enter_new_generation(self) -> None:
        """建立新通道代际：epoch +1 并回填 transport.generation（供代际丢弃）."""
        self._connection_epoch += 1
        self.transport.generation = self._connection_epoch

    def _on_notification(
        self, method: str, params: dict[str, Any], generation: int | None = None
    ) -> None:
        # §7.3：旧 epoch 的通知一律按代际丢弃并记录 adapter 事件，
        # 不得把旧代通道的晚到 tools/list_changed 套用到新代目录状态
        if generation is not None and generation != self._connection_epoch:
            _record_adapter_event(
                "stale_generation_notification",
                self.spec.name,
                f"epoch {generation} 通知 {method} 被丢弃（当前 epoch {self._connection_epoch}）",
            )
            return
        # 规范方法名为 notifications/tools/list_changed（2024-11-05 起）；
        # 宽容接受裸 "tools/list_changed"（部分实现/文档混用）
        if method in ("notifications/tools/list_changed", "tools/list_changed"):
            self._stale = True
            self._list_revision += 1
            _advance_catalog_epoch("tools_list_changed", self.spec.name)
            logger.info(
                "MCP %s 宣告 tools/list_changed（目录版本 → %d，refresh 时重拉）",
                self.spec.name,
                self._list_revision,
            )
            return
        # P2-B（FR-11）：resources/prompts 清单变化通知。清单按需读取、
        # 无本地缓存需失效，故如实记录 adapter 事件（不自动重拉、不猜状态）。
        if method in (
            "notifications/resources/list_changed",
            "resources/list_changed",
            "notifications/prompts/list_changed",
            "prompts/list_changed",
        ):
            _record_adapter_event("capability_list_changed", self.spec.name, f"{method}（清单按需读取，无缓存失效）")
            logger.info("MCP %s 宣告 %s（按需读取面，记录即可）", self.spec.name, method)

    def _next_msg_id(self) -> int:
        """请求 id：跨重连单调递增、绝不重置（§7.3 id 命名空间要求）."""
        value = self._next_id
        self._next_id += 1
        return value

    # ── 生命周期 ──
    def connect(self) -> list[McpToolDef]:
        """连接 + era 协商 + 全量工具清单（游标分页）；失败 close+raise（fail-open）."""
        self._closed = False
        self._enter_new_generation()  # 每次 connect 都是新代际（重连语义）
        try:
            if isinstance(self.transport, StdioTransport):
                self.transport.start()
            self.profile = self._negotiate()
            if self.profile.is_modern:
                self._start_list_subscription()
            tools = self._list_all_tools()
            self._stale = False
            return tools
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """终止连接（stdio 进程终止；HTTP 清会话引用；幂等）."""
        self._closed = True
        self.transport.close()

    # ── 内部（P0 测试契约保留） ──
    @property
    def _proc(self) -> subprocess.Popen[str] | None:
        transport = self.transport
        if isinstance(transport, StdioTransport):
            return transport._proc
        return None

    @_proc.setter
    def _proc(self, value: subprocess.Popen[str] | None) -> None:
        transport = self.transport
        if isinstance(transport, StdioTransport):
            transport._proc = value
        elif value is not None:
            raise AttributeError("HTTP 传输无子进程属性")

    def _start_process(self) -> None:
        self._closed = False
        self._enter_new_generation()  # 测试 seam：模拟进程重启 = 新代际
        if isinstance(self.transport, StdioTransport):
            self.transport.start()

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """按当前 profile 构造请求并等待响应（typed 错误语义见传输层）."""
        profile = self._ensure_profile()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_msg_id(),
            "method": method,
            "params": dict(params or {}),
        }
        if profile.is_modern:
            request["params"] = with_modern_meta(profile.version, request["params"])
        return self.transport.send_request(request, self._call_timeout)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具；仅"确认未派发"失败才重连重试一次（防未知效果重放）."""
        try:
            profile = self._ensure_profile()
            request = build_call_tool_request(self._next_msg_id(), name, arguments, profile)
            return self.transport.send_request(request, self._call_timeout)
        except McpNotDispatchedError:
            # 请求确认未派发 → 重连后重放无重复副作用风险（仍失败如实上抛）
            self.close()
            self.connect()
            assert self.profile is not None
            request = build_call_tool_request(self._next_msg_id(), name, arguments, self.profile)
            return self.transport.send_request(request, self._call_timeout)
        except McpHttpError as exc:
            if exc.status == 404 and self.profile is not None and not self.profile.is_modern:
                # 旧时代 HTTP 会话被服务器终结（404）：请求未被处理 → 重握手重放一次
                logger.warning("MCP %s HTTP 会话失效（404），重新握手后重放一次", self.spec.name)
                self.transport.session_id = None  # type: ignore[union-attr]
                self.profile = self._negotiate()
                assert self.profile is not None
                request = build_call_tool_request(
                    self._next_msg_id(), name, arguments, self.profile
                )
                return self.transport.send_request(request, self._call_timeout)
            raise
        # McpOutcomeUnknownError / McpProtocolError 如实上抛，不自动重放

    # ── era 判定与版本协商（P1-B） ──
    def _ensure_profile(self) -> ProtocolProfile:
        if self.profile is None:
            if isinstance(self.transport, StdioTransport) and self.transport._proc is None:
                self.transport.start()
            self.profile = self._negotiate(total_budget=self._call_timeout)
        return self.profile

    def _negotiate(self, total_budget: float | None = None) -> ProtocolProfile:
        """era 判定 + 版本协商（服务器属性：进程生命期/HTTP origin 内稳定）.

        现代：server/discover → DiscoverResult.supportedVersions 选交集版本；
        UnsupportedProtocolVersionError（data.supported）→ 属"已识别现代错误"，
        按列表选版本重试一次，绝不回退旧握手。
        旧时代：stdio 上其他错误/探测超时 → initialize 握手；HTTP 上非"已识别
        现代错误"的 4xx → initialize 握手（规范 era 判定路径）。
        total_budget：探测+回退握手的总等待上限（惰性协商时约束为调用超时，
        保持 P0"单次等待不翻倍"语义）。
        """
        import time as _time

        base_probe = (
            PROBE_TIMEOUT_S
            if self._probe_timeout_override is None
            else float(self._probe_timeout_override)
        )
        probe_deadline = base_probe if total_budget is None else min(base_probe, total_budget)
        probe = build_discover_request(self._next_msg_id(), MODERN_VERSIONS[0])
        try:
            result = self.transport.send_request(probe, probe_deadline)
        except McpHttpError as exc:
            supported = extract_supported_versions(exc.error or {})
            if supported is None:
                return self._legacy_handshake(deadline=_HANDSHAKE_TIMEOUT_S)
            return self._modern_after_unsupported(supported)
        except McpProtocolError as exc:
            supported = extract_supported_versions(getattr(exc, "error", None) or {})
            if supported is None:
                return self._legacy_handshake(deadline=_HANDSHAKE_TIMEOUT_S)
            return self._modern_after_unsupported(supported)
        except McpOutcomeUnknownError:
            if isinstance(self.transport, StdioTransport):
                # stdio 探测无响应：规范允许按旧服务器回退（探测本身无副作用）
                elapsed = 0.0 if total_budget is None else min(probe_deadline, _time.monotonic())
                remaining = None if total_budget is None else max(total_budget - elapsed, 0.05)
                return self._legacy_handshake(
                    deadline=_HANDSHAKE_TIMEOUT_S
                    if remaining is None
                    else min(_HANDSHAKE_TIMEOUT_S, remaining)
                )
            # HTTP 探测超时：服务器不可用，如实失败（不猜测旧时代）
            raise
        supported, capabilities, server_info = parse_discover_result(result)
        version = select_mutual_modern_version(supported)
        if version is None:
            raise McpProtocolError(
                f"MCP {self.spec.name} 现代版本无交集：服务器 {supported}，本端 {MODERN_VERSIONS}"
            )
        logger.info(
            "MCP %s 现代协议就绪（版本 %s，服务器 %s）",
            self.spec.name,
            version,
            server_info.get("name", "unknown"),
        )
        return ProtocolProfile(
            era=MODERN_ERA,
            version=version,
            server_info=server_info,
            capabilities=capabilities,
            server_supported_versions=supported,
        )

    def _modern_after_unsupported(self, supported: list[str]) -> ProtocolProfile:
        """UnsupportedProtocolVersionError：按 data.supported 选版本重试一次."""
        version = select_mutual_modern_version(supported)
        if version is None:
            raise McpProtocolError(
                f"MCP {self.spec.name} 现代版本无交集：服务器 {supported}，本端 {MODERN_VERSIONS}"
            )
        retry = build_discover_request(self._next_msg_id(), version)
        result = self.transport.send_request(
            retry,
            PROBE_TIMEOUT_S
            if self._probe_timeout_override is None
            else float(self._probe_timeout_override),
        )
        supported2, capabilities, server_info = parse_discover_result(result)
        return ProtocolProfile(
            era="modern",
            version=version,
            server_info=server_info,
            capabilities=capabilities,
            server_supported_versions=supported2,
        )

    def _legacy_handshake(self, deadline: float) -> ProtocolProfile:
        """旧时代 initialize 握手（stdio 与 Streamable HTTP 共用）."""
        init = build_initialize_request(self._next_msg_id(), LEGACY_VERSIONS[0])
        result = self.transport.send_request(init, deadline)
        version = negotiate_initialize_result(result, LEGACY_VERSIONS[0])
        self.transport.send_notification(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        raw_info = result.get("serverInfo")
        server_info = raw_info if isinstance(raw_info, dict) else {}
        raw_caps = result.get("capabilities")
        # P2-B：initialize result 的 capabilities 含 resources/prompts 宣告，
        # 此前未捕获导致旧时代纯资源服务器被判"无能力"。
        capabilities = raw_caps if isinstance(raw_caps, dict) else {}
        session_id = getattr(self.transport, "session_id", None)
        logger.info(
            "MCP %s 旧时代握手完成（版本 %s，服务器 %s，能力 %s）",
            self.spec.name,
            version,
            server_info.get("name", "unknown"),
            ",".join(sorted(capabilities)) or "无宣告",
        )
        return ProtocolProfile(
            era=LEGACY_ERA,
            version=version,
            server_info=dict(server_info),
            capabilities=dict(capabilities),
            http_session_id=session_id,
        )

    def _start_list_subscription(self) -> None:
        """现代连接：发起 subscriptions/listen 长驻订阅（stdio/HTTP 双通道）.

        - stdio：fire-and-forget 长驻请求，通知帧（_meta.subscriptionId 标记）
          由读循环路由至 _on_notification；派发失败 fail-open。
        - HTTP：POST 订阅 → X-Subscription-Id → 常驻 GET 流（后台线程读取），
          失败/断流 fail-open（stale 检测退化为显式 refresh，不自动重订阅）。
        """
        assert self.profile is not None
        request = build_subscribe_request(self._next_msg_id(), ["toolsListChanged"], self.profile)
        if isinstance(self.transport, StdioTransport):
            self.transport.dispatch(request)
            return
        if not isinstance(self.transport, HttpTransport):
            # LegacySseTransport（旧传输）：无常驻订阅 API；通知仅在流上
            # 主动到达时经 _on_notification 处理（fail-open，退化见 docstring）。
            logger.info(
                "MCP %s 传输 %s 不支持常驻订阅（fail-open；stale 检测退化为显式 refresh）",
                self.spec.name,
                self.spec.type,
            )
            return
        sid = self.transport.start_subscription(request, self._call_timeout)
        if sid is not None:
            logger.info(
                "MCP %s HTTP 常驻订阅就绪（subscription=%s；tools/list_changed → stale）",
                self.spec.name,
                sid,
            )

    def _list_all_tools(self) -> list[McpToolDef]:
        """tools/list 游标分页聚合（nextCursor 循环到耗尽）."""
        profile = self.profile
        assert profile is not None
        out: list[McpToolDef] = []
        cursor: str | None = None
        pages = 0
        while True:
            request = build_list_tools_request(self._next_msg_id(), cursor, profile)
            result = self.transport.send_request(request, self._call_timeout)
            for t in result.get("tools") or []:
                if not isinstance(t, dict) or not t.get("name"):
                    continue
                out.append(
                    McpToolDef(
                        name=str(t.get("name", "")),
                        description=str(t.get("description", "")),
                        input_schema=t.get("inputSchema") or {},
                    )
                )
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            cursor = next_cursor
            pages += 1
            if pages >= _MAX_LIST_PAGES:
                raise McpProtocolError(
                    f"MCP {self.spec.name} tools/list 分页超过 {_MAX_LIST_PAGES} 页（疑似循环游标）"
                )
        return out

    # ── P2-B：resources / prompts（FR-11，设计 §7.1）──
    def _require_capability(self, kind: str) -> ProtocolProfile:
        """能力门控：未宣告对应能力 → 如实报"仅提供未支持能力"（非服务器无能力）."""
        profile = self.profile
        if profile is None or self._closed:
            raise McpProtocolError(f"MCP {self.spec.name} 连接未就绪（尚未完成协议协商或已关闭）")
        if not profile.supports(kind):
            raise McpProtocolError(
                f"MCP {self.spec.name} 未宣告 {kind} 能力（仅提供未支持能力；服务器宣告: "
                f"{','.join(sorted(k for k in profile.capabilities if isinstance(k, str))) or '无'}）"
            )
        return profile

    def _list_paged(
        self, builder: Callable[[int, str | None], dict[str, Any]], key: str
    ) -> list[dict[str, Any]]:
        """游标分页聚合（resources/templates/prompts 清单共用；循环游标防护）."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while True:
            result = self.transport.send_request(builder(self._next_msg_id(), cursor), self._call_timeout)
            for item in result.get(key) or []:
                if isinstance(item, dict):
                    out.append(item)
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            cursor = next_cursor
            pages += 1
            if pages >= _MAX_LIST_PAGES:
                raise McpProtocolError(
                    f"MCP {self.spec.name} {key} 分页超过 {_MAX_LIST_PAGES} 页（疑似循环游标）"
                )
        return out

    def list_resources(self) -> list[dict[str, Any]]:
        """resources/list 全量聚合（uri/name/description/mimeType 保留原始字段）."""
        profile = self._require_capability("resources")
        return self._list_paged(
            lambda msg_id, cursor: build_list_resources_request(msg_id, cursor, profile), "resources"
        )

    def list_resource_templates(self) -> list[dict[str, Any]]:
        """resources/templates/list 全量聚合（uriTemplate 描述符）."""
        profile = self._require_capability("resources")
        return self._list_paged(
            lambda msg_id, cursor: build_list_resource_templates_request(msg_id, cursor, profile),
            "resourceTemplates",
        )

    def read_resource(self, uri: str) -> dict[str, Any]:
        """resources/read：contents 原样返回（text/blob 未解码，模型视图在上层）."""
        profile = self._require_capability("resources")
        request = build_read_resource_request(self._next_msg_id(), uri, profile)
        return self.transport.send_request(request, self._call_timeout)

    def list_prompts(self) -> list[dict[str, Any]]:
        """prompts/list 全量聚合（name/description/arguments 保留原始字段）."""
        profile = self._require_capability("prompts")
        return self._list_paged(
            lambda msg_id, cursor: build_list_prompts_request(msg_id, cursor, profile), "prompts"
        )

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """prompts/get：messages（role + typed content）原样返回，类型/角色由模型视图保留."""
        profile = self._require_capability("prompts")
        request = build_get_prompt_request(self._next_msg_id(), name, arguments, profile)
        return self.transport.send_request(request, self._call_timeout)


class McpTool:
    """MCP 工具适配器（注册表 Tool 协议：name/description/parameters/execute）.

    身份：server_name/mcp_name 保留原始字符串；mcp_identity = mcp.<server>.<tool>
    是防碰撞命名与精确所有权关闭的依据。注册名 name 可由调用方传入（防碰撞
    分配见 _assign_registry_names），缺省退回基础归一名。
    """

    def __init__(
        self,
        server_name: str,
        conn: McpConnection,
        tool_def: McpToolDef,
        registry_name: str | None = None,
    ) -> None:
        self.name = registry_name or _registry_name(server_name, tool_def.name)
        self.server_name = server_name
        self.mcp_name = tool_def.name
        self.mcp_identity = _mcp_identity(server_name, tool_def.name)
        self.connection = conn
        # 兼容旧内部属性（模块外无引用；保守保留一个过渡周期）
        self._server = server_name
        self._mcp_name = tool_def.name
        self._conn = conn
        self._description = (
            f"{tool_def.description or tool_def.name}（MCP 服务器 {server_name}，"
            f"经 {conn.transport_kind if isinstance(getattr(conn, 'transport_kind', None), str) else 'stdio'} 连接；服务器不可用会如实返回错误）"
        )
        # 契约保真：原样保留服务器声明的 inputSchema（$defs/oneOf/additionalProperties
        # 等任意 JSON Schema 关键字不删不改），仅补齐 provider 侧最低 object 骨架。
        schema = tool_def.input_schema if isinstance(tool_def.input_schema, dict) else {}
        if schema:
            self.parameters = copy.deepcopy(schema)
            self.parameters.setdefault("type", "object")
            if not isinstance(self.parameters.get("properties"), dict):
                self.parameters["properties"] = {}
            self.parameters.setdefault("required", [])
        else:
            self.parameters = {"type": "object", "properties": {}, "required": []}
        self._raw_input_schema = copy.deepcopy(schema)
        # 最近一次原始 result（best-effort 取回口；同工具并发时为最后完成者）
        self.last_raw_result: dict[str, Any] | None = None

    @property
    def description(self) -> str:
        """注册表 Tool 协议公开字段（registry.schemas/get_tool_schema 依赖）."""
        return self._description

    def _model_view(self, result: dict[str, Any]) -> str:
        """结果模型视图：全部 text 块 + 非文本/结构化部分指针（digest 可对回原始）."""
        digest = _result_digest(result)
        texts: list[str] = []
        pointers: list[str] = []
        for i, block in enumerate(result.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            else:
                btype = block.get("type") if isinstance(block, dict) else type(block).__name__
                pointers.append(
                    f"[MCP content 块 #{i} type={btype}（非文本，模型视图省略；"
                    f"原始结果 digest={digest}）]"
                )
        if isinstance(result.get("structuredContent"), dict):
            pointers.append(f"[structuredContent（模型视图省略；原始结果 digest={digest}）]")
        if result.get("_meta"):
            pointers.append(f"[result._meta（模型视图省略；原始结果 digest={digest}）]")
        text = "\n".join(t for t in texts if t).strip()
        if pointers:
            text = (text + "\n" if text else "") + "\n".join(pointers)
        return text or f"（MCP 工具返回无文本内容；原始结果 digest={digest}）"

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = self.connection.call_tool(self.mcp_name, kwargs or {})
        except McpOutcomeUnknownError as exc:
            # 程序通道错误 → ERROR 态；结果未知必须显式标注（不伪装成功、不静默重放）
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常][结果未知] MCP 工具 {self.name} 调用失败"
                    f"（{type(exc).__name__}: {exc}）。请求已派发但响应未确认，"
                    "未自动重放；副作用是否已发生未知，需调用方按需核实。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="mcp_outcome_unknown",
            )
        except McpProtocolError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常] MCP 工具 {self.name} 调用失败（{type(exc).__name__}: {exc}）。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="mcp_protocol_error",
            )
        except McpError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常] MCP 工具 {self.name} 调用失败（{type(exc).__name__}: {exc}）。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="mcp_error",
            )
        except RuntimeError as exc:
            # 兼容非类型化通道失败（如重连期间 connect() 启动失败）
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常] MCP 工具 {self.name} 调用失败（{type(exc).__name__}: {exc}）。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="runtime_error",
            )
        self.last_raw_result = result
        text = self._model_view(result)
        raw_observation = (
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
            if current_evidence_shadow_enabled.get()
            else None
        )
        if result.get("isError"):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] MCP 工具 {self.name} 返回错误：\n{text}",
                tool_call_id="",
                tool_name=self.name,
                raw_observation=raw_observation,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[状态: success] {text}",
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_observation,
        )


# ── P2-B：resources/prompts 模型工具（设计 §10.1：binding_id + URI/name + arguments）──

#: 单条 text 内容入模型视图上限（超出截断 + digest 指针，可对回原始）
_RESOURCE_TEXT_CAP_CHARS = 32_000


class _McpCapabilityRouter:
    """binding_id → McpConnection 路由基座（每注册表至多一份实例）.

    binding_id 语义：env 配置服务器名，或装配层 install_id:name（ServerBinding
    的 spec.name，见 mcp_assembly）。资源/提示的权限与来源边界以 binding
    所属服务器连接为准（§5.4 绑定身份要素）。
    """

    def __init__(self, base_name: str, fallback_name: str) -> None:
        self._base_name = base_name
        self._fallback_name = fallback_name
        self.name = base_name
        self.bindings: dict[str, McpConnection] = {}

    def _conn_for(self, binding_id: str) -> McpConnection:
        conn = self.bindings.get(binding_id)
        if conn is None or conn._closed:
            raise McpProtocolError(
                f"未知或已失效的 binding_id {binding_id!r}（当前可用: "
                f"{', '.join(sorted(self.bindings)) or '无'}）"
            )
        return conn

    def _error(self, exc: BaseException) -> ToolResult:
        if isinstance(exc, McpOutcomeUnknownError):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常][结果未知] {self.name} 调用失败（{exc}）。"
                    "请求已派发但响应未确认，未自动重放。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="mcp_outcome_unknown",
            )
        return ToolResult(
            status=ToolResultStatus.ERROR,
            content=f"[程序异常] {self.name} 调用失败（{type(exc).__name__}: {exc}）。",
            tool_call_id="",
            tool_name=self.name,
            error_type="mcp_protocol_error" if isinstance(exc, McpError) else "runtime_error",
        )

    @staticmethod
    def _raw_observation(payload: Any) -> str | None:
        if not current_evidence_shadow_enabled.get():
            return None
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


class McpResourceReadTool(_McpCapabilityRouter):
    """mcp_resource_read：resources/read + 清单发现（list=true）.

    模型视图保留：uri（来源）与 mimeType 原样回显；text 原文（超限截断+
    digest 指针）；blob → sha256 指针 + 字节数（二进制不灌入上下文）。
    """

    def __init__(self) -> None:
        super().__init__("mcp_resource_read", "mcp_lfl_resource_read")
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "binding_id": {
                    "type": "string",
                    "description": "MCP 服务器绑定标识（env 服务器名或 install_id:name）",
                },
                "uri": {"type": "string", "description": "resources/read 目标 URI（list=true 时可省略）"},
                "list": {
                    "type": "boolean",
                    "description": "true 时返回该服务器的资源与模板清单（uri/description/mimeType），用于发现 URI",
                    "default": False,
                },
            },
            "required": ["binding_id"],
        }

    @property
    def description(self) -> str:
        return (
            "读取 MCP 服务器资源（resources/read；binding_id + uri）。list=true 返回"
            "该服务器的资源/模板清单以发现可用 URI。text 原文返回，blob 以 digest"
            " 指针呈现；服务器未宣告 resources 能力时如实报错。"
        )

    def _render_read(self, result: dict[str, Any]) -> str:
        parts: list[str] = []
        contents = result.get("contents")
        for i, item in enumerate(contents if isinstance(contents, list) else []):
            if not isinstance(item, dict):
                parts.append(f"[内容 #{i} 非对象形态 {type(item).__name__}]")
                continue
            uri = str(item.get("uri", ""))
            mime = str(item.get("mimeType", "") or "text/plain")
            if isinstance(item.get("text"), str):
                text = item["text"]
                if len(text) > _RESOURCE_TEXT_CAP_CHARS:
                    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
                    parts.append(
                        f"[内容 #{i} uri={uri} mimeType={mime}]\n{text[:_RESOURCE_TEXT_CAP_CHARS]}"
                        f"\n[截断：全文 {len(text)} 字符，digest={digest}]"
                    )
                else:
                    parts.append(f"[内容 #{i} uri={uri} mimeType={mime}]\n{text}")
            elif isinstance(item.get("blob"), str):
                try:
                    data = base64.b64decode(item["blob"], validate=True)
                    note = f"{len(data)} 字节"
                except Exception:  # noqa: BLE001 — 非法 base64 如实呈现
                    data = b""
                    note = "（blob 非法 base64，按 0 字节计）"
                digest = hashlib.sha256(data).hexdigest()[:16]
                parts.append(
                    f"[内容 #{i} uri={uri} mimeType={mime} blob={note} sha256={digest}"
                    "（二进制不入上下文，指针可对回原始）]"
                )
            else:
                parts.append(
                    f"[内容 #{i} uri={uri} 未知内容形态 keys="
                    f"{sorted(str(k) for k in item) or '空'}]"
                )
        return "\n".join(parts) or "（resources/read 返回空 contents）"

    def execute(self, **kwargs: Any) -> ToolResult:
        binding_id = str(kwargs.get("binding_id") or "").strip()
        want_list = bool(kwargs.get("list"))
        payload: Any = None
        try:
            conn = self._conn_for(binding_id)
            if want_list:
                resources = conn.list_resources()
                try:
                    templates = conn.list_resource_templates()
                except McpProtocolError as exc:
                    templates = [{"note": f"模板清单不可用：{exc}"}]
                payload = {"resources": resources, "resourceTemplates": templates}
                text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
            else:
                uri = str(kwargs.get("uri") or "").strip()
                if not uri:
                    raise McpProtocolError("缺 uri（可先以 list=true 发现资源清单）")
                payload = conn.read_resource(uri)
                text = self._render_read(payload if isinstance(payload, dict) else {})
        except (McpError, RuntimeError) as exc:
            return self._error(exc)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[状态: success] {text}",
            tool_call_id="",
            tool_name=self.name,
            raw_observation=self._raw_observation(payload),
        )


class McpPromptGetTool(_McpCapabilityRouter):
    """mcp_prompt_get：prompts/get + 清单发现（list=true）.

    模型视图保留：消息 role（user/assistant 等）与内容块类型；text 原文；
    image/audio/resource 等非文本块 → 类型 + digest 指针；description 保留。
    """

    def __init__(self) -> None:
        super().__init__("mcp_prompt_get", "mcp_lfl_prompt_get")
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "binding_id": {
                    "type": "string",
                    "description": "MCP 服务器绑定标识（env 服务器名或 install_id:name）",
                },
                "name": {"type": "string", "description": "prompts/get 目标提示名（list=true 时可省略）"},
                "arguments": {
                    "type": "object",
                    "description": "提示参数（服务器声明的 arguments；缺省为空）",
                },
                "list": {
                    "type": "boolean",
                    "description": "true 时返回该服务器的提示清单（name/description/arguments），用于发现可用提示",
                    "default": False,
                },
            },
            "required": ["binding_id"],
        }

    @property
    def description(self) -> str:
        return (
            "获取 MCP 服务器提示（prompts/get；binding_id + name + arguments）。"
            "list=true 返回该服务器的提示清单。消息角色与内容块类型保留；"
            "服务器未宣告 prompts 能力时如实报错。"
        )

    def _render_prompt(self, result: dict[str, Any]) -> str:
        lines: list[str] = []
        description = result.get("description")
        if isinstance(description, str) and description:
            lines.append(f"（描述: {description}）")
        messages = result.get("messages")
        for msg in messages if isinstance(messages, list) else []:
            if not isinstance(msg, dict):
                lines.append(f"[消息 非对象形态 {type(msg).__name__}]")
                continue
            role = str(msg.get("role", "unknown"))
            content = msg.get("content")
            blocks = content if isinstance(content, list) else [content]
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    lines.append(f"[{role}] {block.get('text', '')}")
                elif isinstance(block, dict):
                    digest = _result_digest(block)
                    meta = {
                        str(k): v
                        for k, v in block.items()
                        if k not in ("data", "blob", "text")
                    }
                    lines.append(
                        f"[{role}] <非文本块 type={block.get('type')} digest={digest}；"
                        f"{json.dumps(meta, ensure_ascii=False, default=str)[:300]}>"
                    )
                else:
                    lines.append(f"[{role}] <内容块缺失>")
        return "\n".join(lines) or "（prompts/get 返回空 messages）"

    def execute(self, **kwargs: Any) -> ToolResult:
        binding_id = str(kwargs.get("binding_id") or "").strip()
        want_list = bool(kwargs.get("list"))
        payload: Any = None
        try:
            conn = self._conn_for(binding_id)
            if want_list:
                payload = conn.list_prompts()
                text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
            else:
                name = str(kwargs.get("name") or "").strip()
                if not name:
                    raise McpProtocolError("缺 name（可先以 list=true 发现提示清单）")
                raw_args = kwargs.get("arguments")
                arguments = raw_args if isinstance(raw_args, dict) else None
                payload = conn.get_prompt(name, arguments)
                text = self._render_prompt(payload if isinstance(payload, dict) else {})
        except (McpError, RuntimeError) as exc:
            return self._error(exc)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[状态: success] {text}",
            tool_call_id="",
            tool_name=self.name,
            raw_observation=self._raw_observation(payload),
        )


def _find_capability_tool(registry: Any, cls: type) -> tuple[str | None, _McpCapabilityRouter | None]:
    """注册表中既有路由工具（按类型精确识别；名称可因冲突回退不同）."""
    for name in registry.names():
        try:
            tool = registry.get(name)
        except Exception:  # noqa: BLE001 — 竞态下名称消失
            continue
        if isinstance(tool, cls):
            return name, tool
    return None, None


def _ensure_router_tool(registry: Any, tool: _McpCapabilityRouter) -> str | None:
    """确保路由工具在册（基名被非同类工具占用时退回 fallback 名；再冲突则放弃）."""
    existing_name, existing = _find_capability_tool(registry, type(tool))
    if existing is not None:
        return existing_name  # 已在册（refresh 复用同一实例）
    for candidate in (tool._base_name, tool._fallback_name):
        if not candidate:
            continue
        try:
            registry.get(candidate)
            continue  # 名称被其他工具占用
        except Exception:  # noqa: BLE001 — 不存在即可注册
            tool.name = candidate
            try:
                registry.register(tool)
            except Exception:  # noqa: BLE001
                logger.warning("MCP 能力路由工具注册失败: %s", candidate)
                return None
            return candidate
    logger.warning(
        "MCP 能力路由工具名冲突（%s/%s 均被占用），该能力面未注册", tool._base_name, tool._fallback_name
    )
    return None


def _bind_capability_routes(registry: Any, server_name: str, conn: McpConnection) -> list[str]:
    """按宣告能力把连接挂到路由工具（纯资源/提示服务器保活的前提）.

    同名 binding 重建（refresh）时关闭被替换的旧连接（幂等；与上层
    old-conns 关闭路径一致）。返回本服务器实际可用的路由注册名。
    """
    profile = conn.profile
    if profile is None:
        return []
    names: list[str] = []
    if profile.supports("resources"):
        registered = _ensure_router_tool(registry, McpResourceReadTool())
        if registered:
            router = registry.get(registered)
            assert isinstance(router, _McpCapabilityRouter)
            old = router.bindings.get(server_name)
            router.bindings[server_name] = conn
            if old is not None and old is not conn:
                try:
                    old.close()
                except Exception:  # noqa: BLE001
                    logger.warning("MCP 旧能力绑定连接关闭失败（忽略）: %s", server_name)
            names.append(registered)
    if profile.supports("prompts"):
        registered = _ensure_router_tool(registry, McpPromptGetTool())
        if registered:
            router = registry.get(registered)
            assert isinstance(router, _McpCapabilityRouter)
            old = router.bindings.get(server_name)
            router.bindings[server_name] = conn
            if old is not None and old is not conn:
                try:
                    old.close()
                except Exception:  # noqa: BLE001
                    logger.warning("MCP 旧能力绑定连接关闭失败（忽略）: %s", server_name)
            names.append(registered)
    return names


def _drop_capability_routes(registry: Any, server_name: str, close: bool = True) -> None:
    """移除服务器的能力绑定（配置移除/禁用路径；关闭其持有的连接）."""
    for cls in (McpResourceReadTool, McpPromptGetTool):
        _, router = _find_capability_tool(registry, cls)
        if router is None:
            continue
        conn = router.bindings.pop(server_name, None)
        if close and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("MCP 能力绑定连接关闭失败（忽略）: %s", server_name)


def register_mcp_tools(registry: Any, raw_servers: str) -> list[str]:
    """按 MCP_SERVERS 配置连接并注册 MCP 工具（每服务器独立 fail-open）.

    归一名冲突（如服务器 a.b 与 a_b 的同名工具）按原始身份 digest 确定性消歧，
    不再静默覆盖。

    Returns:
        成功注册的工具名列表（供日志/状态展示）。
    """
    registered: list[str] = []
    for spec in parse_servers(raw_servers):
        if not spec.enabled:
            logger.info("MCP 服务器 %s 已禁用（enabled=false），跳过", spec.name)
            continue
        try:
            conn = McpConnection(spec)
            tools = conn.connect()
        except Exception as exc:  # noqa: BLE001 — 单服务器失败不阻断整体
            logger.warning("MCP 服务器 %s 连接失败（fail-open，工具未注册）: %s", spec.name, exc)
            continue
        # P2-B（§7.1/T13）：有效能力集合涵盖 tools/resources/prompts；
        # 宣告 resources/prompts 的服务器即使 tools/list=0 也保活并挂能力路由。
        profile = conn.profile
        extras = bool(
            profile is not None and (profile.supports("resources") or profile.supports("prompts"))
        )
        if not tools:
            if extras:
                routes = _bind_capability_routes(registry, spec.name, conn)
                if routes:
                    registered.extend(routes)
                    logger.info(
                        "MCP 服务器 %s tools/list=0 但宣告 resources/prompts"
                        "（P2-B 保活，不隔离；能力路由 %s）",
                        spec.name,
                        ",".join(routes),
                    )
                    _advance_catalog_epoch("register", spec.name)
                    continue
                conn.close()
                logger.warning(
                    "MCP 服务器 %s tools/list=0 且能力路由注册失败，按 no-capability quarantine 关闭连接",
                    spec.name,
                )
                continue
            # R8.7: a connected MCP server with tools/list=0 has no capability to expose.
            # Do not keep an idle stdio process alive and do not create prompt surface.
            conn.close()
            logger.warning(
                "MCP 服务器 %s tools/list=0，按 no-capability quarantine 关闭连接",
                spec.name,
            )
            continue
        names = _assign_registry_names(spec.name, tools, _registry_identities(registry))
        count = 0
        for tool_def in tools:
            name = names[tool_def.name]
            try:
                registry.register(McpTool(spec.name, conn, tool_def, name))
                registered.append(name)
                count += 1
            except Exception:  # noqa: BLE001 — 单工具注册失败跳过
                logger.warning("MCP 工具注册失败: %s", name)
        routes = _bind_capability_routes(registry, spec.name, conn) if extras else []
        if count == 0 and not routes:
            conn.close()
            logger.warning(
                "MCP 服务器 %s 工具清单非空但有效注册数=0，按 no-capability quarantine 关闭连接",
                spec.name,
            )
            continue
        registered.extend(routes)
        logger.info(
            "MCP 服务器 %s 已连接，注册 %d 个工具%s",
            spec.name,
            count,
            f" + 能力路由 {','.join(routes)}" if routes else "",
        )
        _advance_catalog_epoch("register", spec.name)
    return registered


def _iter_mcp_tools(registry: Any) -> list[tuple[str, McpTool]]:
    """注册表中全部 McpTool 项（精确所有权扫描用；竞态下名称消失则跳过）."""
    items: list[tuple[str, McpTool]] = []
    for name in registry.names():
        try:
            tool = registry.get(name)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(tool, McpTool):
            items.append((name, tool))
    return items


def _server_tools(registry: Any, server_name: str) -> list[tuple[str, McpTool]]:
    """精确所有权：server_name 完全相等（非前缀匹配）的 McpTool 注册项."""
    return [
        (name, tool) for name, tool in _iter_mcp_tools(registry) if tool.server_name == server_name
    ]


def _registry_identities(registry: Any) -> dict[str, str | None]:
    """现有注册名 → Mcp 工具原始身份（非 McpTool 持有者为 None；防碰撞分配输入）."""
    out: dict[str, str | None] = {}
    for name in registry.names():
        try:
            out[name] = getattr(registry.get(name), "mcp_identity", None)
        except Exception:  # noqa: BLE001 — 竞态下名称消失按无身份处理
            out[name] = None
    return out


def _close_server_conns(registry: Any, server_name: str) -> None:
    """关闭某服务器全部现存工具持有的连接（精确所有权，幂等；供 refresh 重建用）.

    仅按 server_name 完全相等匹配（非前缀），避免 mcp_<a>_ 前缀误伤 mcp_<a_b>_。
    """
    seen: set[int] = set()
    for _, tool in _server_tools(registry, server_name):
        conn = tool.connection
        if id(conn) not in seen:
            seen.add(id(conn))
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — 关闭失败不影响刷新主流程
                logger.warning("MCP 连接关闭失败（忽略）: %s", server_name)


def refresh_mcp_tools(registry: Any, raw_servers: str) -> tuple[list[str], list[str]]:
    """热刷新 MCP 工具（EVO-20260819-f9e7ce23 二期；P0 先建后拆 2026-10-09）.

    每服务器：先建新连接 + 重拉 tools/list，成功后才卸载旧工具/关旧连接（新连接
    失败保留旧可用视图，不再先丢后建）；已从配置删除或禁用的服务器统一精确清理。
    每服务器独立 fail-open。

    Returns:
        (registered_names, unregistered_names) — 本轮净变化（供日志/状态展示）。
    """
    registered: list[str] = []
    unregistered: list[str] = []
    specs = parse_servers(raw_servers)
    enabled_names = {spec.name for spec in specs if spec.enabled}

    # 1) 精确清理：已从配置删除或禁用的服务器（diff 语义，非前缀扫描）。
    #    纯资源/提示服务器的连接只挂在能力路由上（无 McpTool），需一并收集。
    known_servers = {tool.server_name for _, tool in _iter_mcp_tools(registry)}
    for cls in (McpResourceReadTool, McpPromptGetTool):
        _, router = _find_capability_tool(registry, cls)
        if router is not None:
            known_servers.update(router.bindings)
    for server_name in sorted(known_servers - enabled_names):
        _close_server_conns(registry, server_name)
        _drop_capability_routes(registry, server_name, close=True)
        for name, _ in _server_tools(registry, server_name):
            if registry.unregister(name):
                unregistered.append(name)
        logger.info("MCP 服务器 %s 已从配置移除或禁用，工具已卸载", server_name)
        _advance_catalog_epoch("config_removed", server_name)

    # 2) 逐服务器先建后拆
    for spec in specs:
        if not spec.enabled:
            continue
        old_items = _server_tools(registry, spec.name)
        old_conns = {id(t.connection): t.connection for _, t in old_items}
        old_names = {name for name, _ in old_items}
        try:
            conn = McpConnection(spec)
            tools = conn.connect()
        except Exception as exc:  # noqa: BLE001 — 新连接失败：保留旧视图（先建后拆）
            logger.warning(
                "MCP 服务器 %s 刷新连接失败（fail-open，旧视图保留）: %s", spec.name, exc
            )
            continue
        new_names: set[str] = set()
        profile = conn.profile
        extras = bool(
            profile is not None and (profile.supports("resources") or profile.supports("prompts"))
        )
        if extras:
            routes = _bind_capability_routes(registry, spec.name, conn)
        else:
            # 能力面消失：清掉上一轮可能残留的路由绑定（含其连接），不留陈旧引用
            routes = []
            _drop_capability_routes(registry, spec.name, close=True)
        if routes:
            new_names.update(routes)
        if not tools and not routes:
            # no-capability server: close the fresh connection; teardown of old view below.
            conn.close()
            logger.warning(
                "MCP 服务器 %s tools/list=0，按 no-capability quarantine 关闭连接",
                spec.name,
            )
        elif tools:
            names = _assign_registry_names(spec.name, tools, _registry_identities(registry))
            new_names.update(names.values())
            count = 0
            for tool_def in tools:
                name = names[tool_def.name]
                try:
                    registry.register(McpTool(spec.name, conn, tool_def, name))
                    registered.append(name)
                    count += 1
                except Exception:  # noqa: BLE001 — 单工具注册失败跳过
                    logger.warning("MCP 工具注册失败: %s", name)
            if count == 0 and not routes:
                conn.close()
                logger.warning(
                    "MCP 服务器 %s 刷新后有效注册数=0，按 no-capability quarantine 关闭连接",
                    spec.name,
                )
            else:
                registered.extend(routes)
                logger.info(
                    "MCP 服务器 %s 刷新完成：注册 %d 个工具%s",
                    spec.name,
                    count,
                    f" + 能力路由 {','.join(routes)}" if routes else "",
                )
                _advance_catalog_epoch("refresh", spec.name)
        else:
            # 纯 resources/prompts 服务器（tools=0 但能力面在）：保活 + 路由
            registered.extend(routes)
            logger.info(
                "MCP 服务器 %s 刷新完成：tools/list=0 但宣告 resources/prompts"
                "（P2-B 保活；能力路由 %s）",
                spec.name,
                ",".join(routes),
            )
            _advance_catalog_epoch("refresh", spec.name)
        # 3) 拆旧：新视图已就绪（或确认 no-capability）才卸旧名、关旧连接
        for name in sorted(old_names - new_names):
            if registry.unregister(name):
                unregistered.append(name)
        if not tools and not routes and old_names:
            _advance_catalog_epoch("refresh_no_capability", spec.name)
        for old_conn in old_conns.values():
            try:
                old_conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("MCP 旧连接关闭失败（忽略）: %s", spec.name)
    return registered, unregistered
