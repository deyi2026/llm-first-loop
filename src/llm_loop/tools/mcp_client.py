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
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_evidence_shadow_enabled

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
_CALL_TIMEOUT_S = 120.0
_HANDSHAKE_TIMEOUT_S = 15.0

# LLM 协议工具名约束（OpenAI 兼容: ^[a-zA-Z0-9_-]+$）——mcp.<server>.<tool> 含点号
# 会被提供方 400 拒绝，注册名统一替换为下划线；底层 MCP 调用仍用原始 tool 名。
_REGISTRY_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _registry_name(server_name: str, tool_name: str) -> str:
    """注册表工具名（协议合法）：mcp.<server>.<tool> → mcp_<server>_<tool>（非法字符 → _）."""
    return _REGISTRY_NAME_RE.sub("_", f"mcp.{server_name}.{tool_name}")


# ── typed 错误（P0：调用方可精确区分"能否安全重试"）──
class McpError(RuntimeError):
    """MCP 调用错误基类（继承 RuntimeError：兼容既有 except RuntimeError 路径）."""


class McpNotDispatchedError(McpError):
    """请求确认未派发（写入前进程已退出/连接缺失）→ 重连重试安全."""


class McpOutcomeUnknownError(McpError):
    """请求已派发但结果未知（超时/通道断开/写入失败）→ 禁止自动重放（防重复副作用）."""


class McpProtocolError(McpError):
    """服务器以 JSON-RPC error 应答（派发已确认）→ 效果已知，不重放."""


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
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


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
        logger.warning("MCP_SERVERS 必须为 JSON 数组（当前 %s），MCP 工具未加载", type(data).__name__)
        return []
    out: list[McpServerSpec] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("MCP_SERVERS[%d] 非对象，跳过", i)
            continue
        name = str(item.get("name", "")).strip()
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
                enabled=bool(item.get("enabled", True)),
            )
        )
    return out


class McpConnection:
    """stdio MCP 连接（JSON-RPC 行协议；读线程 + 队列 + 超时；连接级锁串行）."""

    def __init__(self, spec: McpServerSpec, call_timeout: float = _CALL_TIMEOUT_S) -> None:
        self.spec = spec
        self._call_timeout = call_timeout
        self._proc: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._next_id = 1
        self._closed = False

    # ── 生命周期 ──
    def connect(self) -> list[McpToolDef]:
        """启动进程 + 握手 + 拉取工具清单；失败抛 RuntimeError（调用方 fail-open）."""
        with self._lock:
            self._start_process()
            try:
                self._rpc("initialize", {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "llm-first-loop", "version": "0.6.0"},
                })
                self._notify("notifications/initialized", {})
                result = self._rpc("tools/list", {})
                tools = result.get("tools") or []
                return [
                    McpToolDef(
                        name=str(t.get("name", "")),
                        description=str(t.get("description", "")),
                        input_schema=t.get("inputSchema") or {},
                    )
                    for t in tools
                    if t.get("name")
                ]
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        """终止进程（幂等）."""
        self._closed = True
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001 — 收尸失败不阻断
                import contextlib

                with contextlib.suppress(Exception):  # noqa: BLE001
                    proc.kill()

    # ── 内部 ──
    def _start_process(self) -> None:
        self._closed = False
        env = dict(os.environ)
        env.update(self.spec.env)
        try:
            self._proc = subprocess.Popen(
                [self.spec.command, *self.spec.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            raise RuntimeError(f"MCP 服务器 {self.spec.name} 启动失败: {exc}") from exc
        self._queue = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"mcp-{self.spec.name}", daemon=True
        )
        self._reader.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        while True:
            try:
                line = proc.stdout.readline()
            except Exception:  # noqa: BLE001 — 读失败按断连
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_id = msg.get("id")
            if isinstance(msg_id, int):
                self._queue.put((msg_id, msg))
            # 无 id 的通知（log/message）忽略（fail-open）

    def _write(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError(f"MCP 服务器 {self.spec.name} 通道不可用")
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            # 写入前进程已退出 → 请求必然未派发，重连重试安全
            if self._proc is None or self._proc.poll() is not None:
                raise McpNotDispatchedError(
                    f"MCP 服务器 {self.spec.name} 进程已退出（请求未派发）"
                )
            msg_id = self._next_id
            self._next_id += 1
            try:
                self._write({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
            except OSError as exc:
                # 写入失败无法证明请求未送达 → 按结果未知处理（不重放）
                self.close()
                raise McpOutcomeUnknownError(
                    f"MCP 服务器 {self.spec.name} 请求写入失败（派发状态未知）: {exc}"
                ) from exc
            deadline = _HANDSHAKE_TIMEOUT_S if method == "initialize" else self._call_timeout
            try:
                while True:
                    got_id, resp = self._queue.get(timeout=deadline)
                    if got_id != msg_id:
                        continue
                    if "error" in resp:
                        # 服务器已收到并以 JSON-RPC error 拒绝 → 派发已确认，不重放
                        raise McpProtocolError(
                            f"MCP {self.spec.name} {method} 错误: {resp['error']}"
                        )
                    return resp.get("result") or {}
            except queue.Empty as exc:
                # 已派发但响应未达 → 结果未知，禁止自动重放（防重复副作用）
                raise McpOutcomeUnknownError(
                    f"MCP 服务器 {self.spec.name} {method} 超时（{deadline:.0f}s；"
                    "请求已派发、结果未知，不自动重放）"
                ) from exc

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具；仅"确认未派发"失败才重连重试一次（防未知效果重放）."""
        try:
            return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        except McpNotDispatchedError:
            # 请求确认未派发 → 重连后重放无重复副作用风险（仍失败如实上抛）
            self.close()
            self.connect()
            return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        # McpOutcomeUnknownError / McpProtocolError 如实上抛，不自动重放


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
            f"经 stdio 连接；服务器不可用会如实返回错误）"
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
                    f"[程序异常] MCP 工具 {self.name} 调用失败"
                    f"（{type(exc).__name__}: {exc}）。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="mcp_protocol_error",
            )
        except McpError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    f"[程序异常] MCP 工具 {self.name} 调用失败"
                    f"（{type(exc).__name__}: {exc}）。"
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
                    f"[程序异常] MCP 工具 {self.name} 调用失败"
                    f"（{type(exc).__name__}: {exc}）。"
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
        if not tools:
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
        if count == 0:
            conn.close()
            logger.warning(
                "MCP 服务器 %s 工具清单非空但有效注册数=0，按 no-capability quarantine 关闭连接",
                spec.name,
            )
            continue
        logger.info("MCP 服务器 %s 已连接，注册 %d 个工具", spec.name, count)
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
    return [(name, tool) for name, tool in _iter_mcp_tools(registry) if tool.server_name == server_name]


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

    # 1) 精确清理：已从配置删除或禁用的服务器（diff 语义，非前缀扫描）
    known_servers = {tool.server_name for _, tool in _iter_mcp_tools(registry)}
    for server_name in sorted(known_servers - enabled_names):
        _close_server_conns(registry, server_name)
        for name, _ in _server_tools(registry, server_name):
            if registry.unregister(name):
                unregistered.append(name)
        logger.info("MCP 服务器 %s 已从配置移除或禁用，工具已卸载", server_name)

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
        if not tools:
            # no-capability server: close the fresh connection; teardown of old view below.
            conn.close()
            logger.warning(
                "MCP 服务器 %s tools/list=0，按 no-capability quarantine 关闭连接",
                spec.name,
            )
        else:
            names = _assign_registry_names(spec.name, tools, _registry_identities(registry))
            new_names = set(names.values())
            count = 0
            for tool_def in tools:
                name = names[tool_def.name]
                try:
                    registry.register(McpTool(spec.name, conn, tool_def, name))
                    registered.append(name)
                    count += 1
                except Exception:  # noqa: BLE001 — 单工具注册失败跳过
                    logger.warning("MCP 工具注册失败: %s", name)
            if count == 0:
                conn.close()
                logger.warning(
                    "MCP 服务器 %s 刷新后有效注册数=0，按 no-capability quarantine 关闭连接",
                    spec.name,
                )
            else:
                logger.info("MCP 服务器 %s 刷新完成：注册 %d 个工具", spec.name, count)
        # 3) 拆旧：新视图已就绪（或确认 no-capability）才卸旧名、关旧连接
        for name in sorted(old_names - new_names):
            if registry.unregister(name):
                unregistered.append(name)
        for old_conn in old_conns.values():
            try:
                old_conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("MCP 旧连接关闭失败（忽略）: %s", spec.name)
    return registered, unregistered
