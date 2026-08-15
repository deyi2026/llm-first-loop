"""MCP 客户端接入（P3-1，2026-08-15）.

`MCP_SERVERS` env JSON 配置 stdio MCP 服务器；启动时连接握手 + 拉取工具清单，
以 `mcp.<server>.<tool>` 名注册进 ToolRegistry（inputSchema 透传为 parameters），
执行走统一注册表通道（线程超时 / 输出分层 / 审计复用），结果五态包装
（success / failure / blocked / timeout / error，对齐 ToolResultStatus）。

诚实边界（fail-open）：
- 服务器启动/握手失败 → 该服务器工具不注册，其余服务器/工具不受影响（日志如实）
- 调用时进程失联 → 单次重连重试；仍失败 → ERROR 态如实回执（不伪装成功）
- 工具返回 isError=True → FAILURE 态（content 原样透传）
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
_CALL_TIMEOUT_S = 120.0
_HANDSHAKE_TIMEOUT_S = 15.0


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
            if self._proc is None or self._proc.poll() is not None:
                raise RuntimeError(f"MCP 服务器 {self.spec.name} 进程已退出")
            msg_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
            deadline = _HANDSHAKE_TIMEOUT_S if method == "initialize" else self._call_timeout
            try:
                while True:
                    got_id, resp = self._queue.get(timeout=deadline)
                    if got_id != msg_id:
                        continue
                    if "error" in resp:
                        raise RuntimeError(
                            f"MCP {self.spec.name} {method} 错误: {resp['error']}"
                        )
                    return resp.get("result") or {}
            except queue.Empty as exc:
                raise RuntimeError(
                    f"MCP 服务器 {self.spec.name} {method} 超时（{deadline:.0f}s）"
                ) from exc

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具；进程失联时重连一次（fail-open 重试语义）."""
        try:
            return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        except RuntimeError as first_err:
            # 失联重连一次：仍失败如实上抛
            try:
                self.close()
                self.connect()
                return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
            except Exception as retry_err:  # noqa: BLE001
                raise RuntimeError(
                    f"MCP 服务器 {self.spec.name} 调用失败（重连后仍失败: {retry_err}；"
                    f"原始错误: {first_err}）"
                ) from retry_err


def _content_text(result: dict[str, Any]) -> str:
    """MCP result content blocks → 文本（text 块拼接；无文本如实标注）."""
    parts: list[str] = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    joined = "\n".join(parts).strip()
    return joined or "（MCP 工具返回无文本内容）"


class McpTool:
    """MCP 工具适配器（注册表 Tool 协议：name/description/parameters/execute）."""

    def __init__(self, server_name: str, conn: McpConnection, tool_def: McpToolDef) -> None:
        self.name = f"mcp.{server_name}.{tool_def.name}"
        self._server = server_name
        self._mcp_name = tool_def.name
        self._conn = conn
        self._description = (
            f"{tool_def.description or tool_def.name}（MCP 服务器 {server_name}，"
            f"经 stdio 连接；服务器不可用会如实返回错误）"
        )
        schema = tool_def.input_schema or {}
        self.parameters = {
            "type": "object",
            "properties": schema.get("properties") or {},
            "required": schema.get("required") or [],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = self._conn.call_tool(self._mcp_name, kwargs or {})
        except RuntimeError as exc:
            # 程序通道错误 → ERROR 态（区别于工具自身失败）
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[程序异常] MCP 工具 {self.name} 调用失败（{type(exc).__name__}: {exc}）。",
                tool_call_id="",
                tool_name=self.name,
            )
        text = _content_text(result)
        if result.get("isError"):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] MCP 工具 {self.name} 返回错误：\n{text}",
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[状态: success] {text}",
            tool_call_id="",
            tool_name=self.name,
        )


def register_mcp_tools(registry: Any, raw_servers: str) -> list[str]:
    """按 MCP_SERVERS 配置连接并注册 MCP 工具（每服务器独立 fail-open）.

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
        count = 0
        for tool_def in tools:
            try:
                registry.register(McpTool(spec.name, conn, tool_def))
                registered.append(f"mcp.{spec.name}.{tool_def.name}")
                count += 1
            except Exception:  # noqa: BLE001 — 单工具注册失败跳过
                logger.warning("MCP 工具注册失败: mcp.%s.%s", spec.name, tool_def.name)
        logger.info("MCP 服务器 %s 已连接，注册 %d 个工具", spec.name, count)
    return registered
