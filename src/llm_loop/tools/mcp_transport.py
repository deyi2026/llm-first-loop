"""MCP 传输层（IO）— DESIGN-20261009 §6/§11 P1-B.

两个实现：
- StdioTransport：子进程 newline-delimited JSON-RPC（P0 的进程管理与
  typed dispatch 语义原样迁移：未派发/结果未知/协议错误三分）。
- HttpTransport：Streamable HTTP（单端点 POST）。双时代：
  * 现代（2026-07-28）：每请求 header Mcp-Method/Mcp-Name/
    MCP-Protocol-Version（与 params._meta 一致），无会话；
  * 旧时代（≤2025-11-25）：initialize 握手 + Mcp-Session-Id 会话头，
    202 Accepted 通知，JSON 或 SSE 响应。

同步契约：request() 阻塞至响应或超时（LFL Tool.execute 同步桥）。
HTTP 连接按请求建立（无池化）；写后读超时=结果未知，连接失败=未派发。
"""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
import os
import queue
import socket
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from llm_loop.tools.mcp_auth import McpOAuthClient
from llm_loop.tools.mcp_protocol import (
    META_VERSION,
    McpError,
    McpNotDispatchedError,
    McpOutcomeUnknownError,
    McpProtocolError,
    encode_header_value,
)

logger = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT_S = 10.0
#: era 探测（server/discover）等待上限；无响应按旧时代回退（规范允许）
PROBE_TIMEOUT_S = 5.0

#: 通知上送回调：(method, params, generation)。generation = 通道创建时的
#: 连接代际（由编排层在建立新通道时回填）；旧代通道晚到的通知据此被
#: 上层按代际丢弃（设计 §7.3：不得匹配到新代请求/目录状态）。
NotificationHandler = Callable[[str, dict[str, Any], int], None]


class McpHttpError(McpProtocolError):
    """HTTP 层错误（状态码 ≥400）携带原始 body 供 era 判定/会话恢复."""

    def __init__(self, status: int, error: dict[str, Any] | None, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.error = error  # 解析出的 JSON-RPC error（可能无 id；可能 None）
        self.body_text = detail


class McpTransport(ABC):
    """面向 JSON-RPC 消息的同步双工通道."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.notification_handler: NotificationHandler | None = None
        # 连接代际（0 = 未标记；编排层每次建立新通道时递增并回填）。
        # 语义：同代通道的通知/响应共享同一请求 id 命名空间时代；重连后
        # 旧代通道的晚到通知必须被上层丢弃，不得套用到新代状态。
        self.generation: int = 0

    @abstractmethod
    def send_request(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        """发送请求并等待对应 id 的 result.

        返回 result dict；失败按 typed 语义上抛：
        未派发（McpNotDispatchedError）/ 结果未知（McpOutcomeUnknownError）/
        协议拒绝（McpProtocolError，HTTP 层为 McpHttpError）。
        """

    @abstractmethod
    def send_notification(self, notification: dict[str, Any]) -> None:
        """发送通知（fire-and-forget；通道级失败按 fail-open 记日志）."""

    @abstractmethod
    def close(self) -> None:
        """终止通道（幂等）."""


class StdioTransport(McpTransport):
    """子进程 stdio 传输（newline-delimited JSON-RPC）."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str]) -> None:
        super().__init__(name)
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self._proc: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        self._lock = threading.Lock()

    # ── 生命周期 ──
    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        env = dict(os.environ)
        env.update(self.env)
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            raise McpNotDispatchedError(f"MCP 服务器 {self.name} 启动失败: {exc}") from exc
        self._queue = queue.Queue()
        threading.Thread(target=self._read_loop, name=f"mcp-stdio-{self.name}", daemon=True).start()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
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

    # ── IO ──
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
                continue
            method = msg.get("method")
            if isinstance(method, str):
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                handler = self.notification_handler
                if handler is not None:
                    try:
                        handler(method, params, self.generation)
                    except Exception:  # noqa: BLE001 — 通知处理失败不影响读循环
                        logger.debug("MCP %s 通知处理异常", self.name, exc_info=True)

    def _write(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpNotDispatchedError(f"MCP 服务器 {self.name} 通道不可用")
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def send_request(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        msg_id = request.get("id")
        if not isinstance(msg_id, int):
            raise McpError("Stdio 请求缺少整数 id")
        with self._lock:
            if not self.alive:
                # 写入前进程已退出 → 请求必然未派发，重连重试安全
                raise McpNotDispatchedError(f"MCP 服务器 {self.name} 进程已退出（请求未派发）")
            try:
                self._write(request)
            except McpNotDispatchedError:
                raise
            except OSError as exc:
                # 写入失败无法证明请求未送达 → 按结果未知处理（不重放）
                self.close()
                raise McpOutcomeUnknownError(
                    f"MCP 服务器 {self.name} 请求写入失败（派发状态未知）: {exc}"
                ) from exc
            try:
                while True:
                    got_id, resp = self._queue.get(timeout=timeout)
                    if got_id != msg_id:
                        continue
                    if "error" in resp:
                        # 服务器已收到并以 JSON-RPC error 拒绝 → 派发已确认，不重放
                        error = resp["error"] if isinstance(resp.get("error"), dict) else None
                        raise McpProtocolError(
                            f"MCP {self.name} {request.get('method')} 错误: {resp['error']}",
                            error,
                        )
                    return resp.get("result") or {}
            except queue.Empty as exc:
                # 已派发但响应未达 → 结果未知，禁止自动重放（防重复副作用）
                raise McpOutcomeUnknownError(
                    f"MCP 服务器 {self.name} {request.get('method')} 超时"
                    f"（{timeout:.0f}s；请求已派发、结果未知，不自动重放）"
                ) from exc

    def dispatch(self, request: dict[str, Any]) -> None:
        """只写不等待（长驻请求如 subscriptions/listen；响应帧由后续读循环跳过）."""
        try:
            self._write(request)
        except (McpNotDispatchedError, OSError) as exc:
            logger.warning("MCP %s 长驻请求派发失败（fail-open）: %s", self.name, exc)

    def send_notification(self, notification: dict[str, Any]) -> None:
        try:
            self._write(notification)
        except (McpNotDispatchedError, OSError) as exc:
            logger.warning("MCP %s 通知发送失败（fail-open）: %s", self.name, exc)


class HttpTransport(McpTransport):
    """Streamable HTTP 传输（双时代；现代无会话，旧时代 Mcp-Session-Id）."""

    def __init__(
        self,
        name: str,
        url: str,
        extra_headers: dict[str, str] | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(name)
        self.url = url
        self.extra_headers = dict(extra_headers or {})
        self.session_id = session_id  # 旧时代会话（initialize 后设置）
        # 常驻订阅（现代 subscriptions/listen）状态
        self._sub_lock = threading.Lock()
        self._sub_stop = threading.Event()
        self._sub_thread: threading.Thread | None = None
        self._sub_sid: str | None = None
        self._sub_conn: http.client.HTTPConnection | None = None
        # GET 流的原始 socket 引用：will_close 响应会让 http.client 在
        # getresponse() 内自动 close 并置 conn.sock=None，socket 所有权移交给
        # 响应对象；想从外部 shutdown 唤醒阻塞读，必须在此另存原始引用
        self._sub_sock: socket.socket | None = None
        # OAuth 客户端（FR-05）：由编排层（McpConnection）按 credential_ref 注入；
        # None = 无授权（服务器 401 直接按可诊断错误上抛）
        self.oauth: McpOAuthClient | None = None

    def close(self) -> None:
        # 终止常驻订阅流（若有）：shutdown 原始 socket——close() 在部分平台
        # （macOS）不会唤醒阻塞中的 recv/readline，shutdown(SHUT_RDWR) 才可靠
        self._sub_stop.set()
        with self._sub_lock:
            conn = self._sub_conn
            sock = self._sub_sock
            self._sub_conn = None
            self._sub_sid = None
            self._sub_sock = None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()
        if conn is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()
        thread = self._sub_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        # 无长连接可关（按请求建连）；旧时代会话按 DELETE 终止属可选，留空
        self.session_id = None

    # ── 请求 ──
    def _build_headers(self, request: dict[str, Any]) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        raw_params = request.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        raw_meta = params.get("_meta")
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        version = meta.get(META_VERSION)
        if isinstance(version, str):
            headers["MCP-Protocol-Version"] = version
            headers["Mcp-Method"] = str(request.get("method") or "")
            name_value = params.get("name") or params.get("uri")
            if isinstance(name_value, str):
                headers["Mcp-Name"] = encode_header_value(name_value)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        headers.update(self.extra_headers)
        return headers

    def send_request(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        """请求（含 OAuth：401 → 换取/取令牌 → 同请求重放一次）."""
        try:
            return self._send_request_once(request, timeout)
        except McpHttpError as exc:
            if exc.status != 401 or self.oauth is None:
                raise
            # 401 = 服务器拒绝当前凭证：OAuth 处理（缺凭证/需交互授权会抛可诊断
            # McpCredentialError / McpAuthRequiredError，不吞不包装），成功则重放一次
            bearer = self.oauth.on_401(getattr(exc, "www_authenticate", "") or "")
            return self._send_request_once(request, timeout, {"Authorization": f"Bearer {bearer}"})

    def _auth_headers(self) -> dict[str, str]:
        """缓存令牌预置（不触发网络；无 oauth/无令牌则空）."""
        if self.oauth is None:
            return {}
        bearer = self.oauth.cached_bearer()
        return {"Authorization": f"Bearer {bearer}"} if bearer else {}

    def _send_request_once(
        self,
        request: dict[str, Any],
        timeout: float,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        msg_id = request.get("id")
        if not isinstance(msg_id, int):
            raise McpError("HTTP 请求缺少整数 id")
        body = json.dumps(request)
        headers = {**self._auth_headers(), **self._build_headers(request), **(extra_headers or {})}
        parts = urlsplit(self.url)
        host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            try:
                conn.request("POST", parts.path or "/", body=body, headers=headers)
                resp = conn.getresponse()
            except ConnectionRefusedError as exc:
                # TCP 层拒绝：请求字节必然未送达服务器 → 未派发，重试安全
                raise McpNotDispatchedError(
                    f"MCP HTTP {self.name} 连接被拒绝（请求未派发）: {exc}"
                ) from exc
            except _POST_SEND_FAILURES as exc:
                # 已发出（或无法证明未发出）：按结果未知处理（不重放）
                raise McpOutcomeUnknownError(
                    f"MCP HTTP {self.name} {request.get('method')} 传输失败（结果未知，不自动重放）: {exc}"
                ) from exc
            status = resp.status
            content_type = (resp.getheader("Content-Type") or "").split(";")[0].strip()
            session_header = resp.getheader("Mcp-Session-Id")
            if session_header:
                # 旧时代会话（现代规范已移除；出现即捕获，幂等刷新）
                self.session_id = session_header
            if status == 202:  # 通知语义（请求不应走到这）
                raise McpProtocolError(f"MCP HTTP {self.name} 对请求返回 202 Accepted")
            if status >= 400:
                raw = resp.read().decode("utf-8", errors="replace")
                error: dict[str, Any] | None = None
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                        error = parsed["error"]
                except json.JSONDecodeError:
                    pass
                http_error = McpHttpError(status, error, raw[:500])
                if status == 401:
                    http_error.www_authenticate = resp.getheader("WWW-Authenticate") or ""
                raise http_error
            if content_type == "text/event-stream":
                return self._read_sse_response(resp, msg_id)
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise McpProtocolError(f"MCP HTTP {self.name} 响应非 JSON: {raw[:200]!r}") from exc
            if not isinstance(msg, dict):
                raise McpProtocolError(f"MCP HTTP {self.name} 响应非对象: {raw[:200]!r}")
            if "error" in msg:
                error = msg["error"] if isinstance(msg.get("error"), dict) else None
                raise McpProtocolError(
                    f"MCP HTTP {self.name} {request.get('method')} 错误: {msg['error']}",
                    error,
                )
            return msg.get("result") or {}
        finally:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()

    def send_notification(self, notification: dict[str, Any]) -> None:
        body = json.dumps(notification)
        headers = {**self._auth_headers(), **self._build_headers(notification)}
        parts = urlsplit(self.url)
        host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=HANDSHAKE_TIMEOUT_S)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=HANDSHAKE_TIMEOUT_S)
        try:
            try:
                conn.request("POST", parts.path or "/", body=body, headers=headers)
                resp = conn.getresponse()
                resp.read()
                if resp.status == 401 and self.oauth is not None:
                    # OAuth 换取后重放一次（通知语义仍 fail-open：不抛不重试第二次）
                    try:
                        bearer = self.oauth.on_401(resp.getheader("WWW-Authenticate") or "")
                    except McpError:
                        return
                    conn.request(
                        "POST",
                        parts.path or "/",
                        body=body,
                        headers={**headers, "Authorization": f"Bearer {bearer}"},
                    )
                    conn.getresponse().read()
            except _POST_SEND_FAILURES as exc:
                logger.warning("MCP HTTP %s 通知发送失败（fail-open）: %s", self.name, exc)
        finally:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()

    # ── 常驻订阅（现代 subscriptions/listen；设计 §7.3 HTTP 常驻监听） ──
    def start_subscription(self, request: dict[str, Any], timeout: float) -> str | None:
        """现代 HTTP 常驻订阅：POST subscriptions/listen → 读 X-Subscription-Id → 起 GET 常驻流.

        流程（对齐 streamable HTTP subscriptions 草案约定，X-Subscription-Id 头）：
        1. POST 订阅请求 → 服务器 200 + 响应头 X-Subscription-Id；
        2. 同端点 GET（X-Subscription-Id + Accept: text/event-stream）→ 常驻 SSE 流，
           后台线程逐事件解析，通知帧经 notification_handler(method, params, generation)
           上送（generation = 建订阅时的连接代际）；
        3. 任一步失败 fail-open 返回 None（stale 检测退化为显式 refresh）；
           GET 流中断仅记日志（不自动重订阅，refresh/重连时重建）。

        Returns:
            subscription id（成功）| None（fail-open）。
        """
        assert isinstance(request.get("id"), int)
        body = json.dumps(request)
        parts = urlsplit(self.url)
        host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)

        def _post(extra_headers: dict[str, str] | None = None) -> tuple[int, str, str]:
            headers = {
                **self._auth_headers(),
                **self._build_headers(request),
                **(extra_headers or {}),
            }
            if parts.scheme == "https":
                post_conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    host, port, timeout=timeout
                )
            else:
                post_conn = http.client.HTTPConnection(host, port, timeout=timeout)
            try:
                post_conn.request("POST", parts.path or "/", body=body, headers=headers)
                post_resp = post_conn.getresponse()
                post_resp.read()
                return (
                    post_resp.status,
                    post_resp.getheader("X-Subscription-Id") or "",
                    post_resp.getheader("WWW-Authenticate") or "",
                )
            finally:
                with contextlib.suppress(Exception):  # noqa: BLE001
                    post_conn.close()

        sid: str | None = None
        try:
            status, raw_sid, www_auth = _post()
            if status == 401 and self.oauth is not None:
                # OAuth 换取后同请求重放一次（可诊断失败 fail-open 退回显式 refresh）
                try:
                    bearer = self.oauth.on_401(www_auth)
                    status, raw_sid, _ = _post({"Authorization": f"Bearer {bearer}"})
                except McpError as exc:
                    logger.warning(
                        "MCP HTTP %s 订阅授权失败（fail-open，stale 检测退化为显式 refresh）: %s",
                        self.name,
                        exc,
                    )
                    return None
        except _POST_SEND_FAILURES as exc:
            logger.warning("MCP HTTP %s 订阅请求发送失败（fail-open）: %s", self.name, exc)
            return None
        sid = raw_sid or None
        if status != 200 or not sid:
            logger.warning(
                "MCP HTTP %s 订阅请求失败（status=%s, sid=%r，fail-open）",
                self.name,
                status,
                sid,
            )
            return None
        self._sub_stop.clear()
        with self._sub_lock:
            self._sub_sid = sid
        self._sub_thread = threading.Thread(
            target=self._subscription_reader,
            args=(sid,),
            name=f"mcp-http-sub-{self.name}",
            daemon=True,
        )
        self._sub_thread.start()
        return sid

    def _subscription_reader(self, sid: str) -> None:
        """GET 常驻流读取线程：SSE 事件 → 通知上送；断流/停机即退出（fail-open）."""
        parts = urlsplit(self.url)
        host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
        headers = {
            **self._auth_headers(),
            "Accept": "text/event-stream",
            "X-Subscription-Id": sid,
            **self.extra_headers,
        }
        try:
            if parts.scheme == "https":
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port)
            else:
                conn = http.client.HTTPConnection(host, port)
        except OSError as exc:
            logger.warning("MCP HTTP %s 订阅流建连失败（fail-open）: %s", self.name, exc)
            return
        with self._sub_lock:
            if self._sub_stop.is_set():
                with contextlib.suppress(Exception):  # noqa: BLE001
                    conn.close()
                return
            self._sub_conn = conn
        try:
            conn.request("GET", parts.path or "/", headers=headers)
            sock = conn.sock  # getresponse() 对 will_close 响应会接管 socket 并置 conn.sock=None
            resp = conn.getresponse()
            if resp.status != 200:
                logger.warning(
                    "MCP HTTP %s 订阅流被拒（status=%s，fail-open，stale 检测退化为显式 refresh）",
                    self.name,
                    resp.status,
                )
                return
            with self._sub_lock:
                self._sub_sock = sock
            data_lines: list[str] = []
            while not self._sub_stop.is_set():
                raw = resp.readline()
                if not raw:
                    break  # 流正常结束（服务器关闭）
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if data_lines:
                        self._dispatch_subscription_event("\n".join(data_lines))
                        data_lines = []
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip(" "))
            if data_lines and not self._sub_stop.is_set():
                self._dispatch_subscription_event("\n".join(data_lines))
            logger.info("MCP HTTP %s 订阅流结束（subscription=%s）", self.name, sid)
        except Exception as exc:  # noqa: BLE001 — 断流 fail-open：不自动重订阅
            logger.info("MCP HTTP %s 订阅流中断（fail-open）: %s", self.name, exc)
        finally:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()
            with self._sub_lock:
                if self._sub_conn is conn:
                    self._sub_conn = None
                if self._sub_sock is not None and self._sub_sock.fileno() == -1:
                    self._sub_sock = None

    def _dispatch_subscription_event(self, payload: str) -> None:
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        method = msg.get("method")
        if not isinstance(method, str):
            return
        raw_params = msg.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        handler = self.notification_handler
        if handler is not None:
            try:
                handler(method, params, self.generation)
            except Exception:  # noqa: BLE001
                logger.debug("MCP %s 订阅通知处理异常", self.name, exc_info=True)

    # ── SSE ──
    def _read_sse_response(self, resp: http.client.HTTPResponse, msg_id: int) -> dict[str, Any]:
        """读取 SSE 流：通知交给 handler，取 id 匹配的响应后停.

        读流期间超时/断连：请求已派发但响应未达 → McpOutcomeUnknownError
        （不自动重放）。
        """
        data_lines: list[str] = []
        found = False
        result: dict[str, Any] = {}
        try:
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if data_lines:
                        found, result = self._handle_sse_event("\n".join(data_lines), msg_id)
                        if found:
                            return result
                        data_lines = []
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip(" "))
            if data_lines:
                found, result = self._handle_sse_event("\n".join(data_lines), msg_id)
                if found:
                    return result
        except _POST_SEND_FAILURES as exc:
            raise McpOutcomeUnknownError(
                f"MCP HTTP {self.name} SSE 流中断（结果未知，不自动重放）: {exc}"
            ) from exc
        raise McpOutcomeUnknownError(
            f"MCP HTTP {self.name} SSE 流结束而无 id={msg_id} 响应（结果未知）"
        )

    def _handle_sse_event(self, payload: str, msg_id: int) -> tuple[bool, dict[str, Any]]:
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            return (False, {})
        if not isinstance(msg, dict):
            return (False, {})
        if msg.get("id") == msg_id:
            if "error" in msg:
                error = msg["error"] if isinstance(msg.get("error"), dict) else None
                raise McpProtocolError(f"MCP HTTP {self.name} SSE 响应错误: {msg['error']}", error)
            return (True, msg.get("result") or {})
        if "method" in msg and isinstance(msg.get("method"), str):
            raw_params = msg.get("params")
            params = raw_params if isinstance(raw_params, dict) else {}
            handler = self.notification_handler
            if handler is not None:
                try:
                    handler(msg["method"], params, self.generation)
                except Exception:  # noqa: BLE001
                    logger.debug("MCP %s SSE 通知处理异常", self.name, exc_info=True)
        return (False, {})


#: 已发出（或无法证明未发出）的传输失败 → 结果未知（保守不重放）。
#: ConnectionRefusedError 单列（见 send_request）：TCP 拒绝=必然未派发。
_POST_SEND_FAILURES = (
    socket.timeout,
    ConnectionError,
    http.client.HTTPException,
    OSError,
)
