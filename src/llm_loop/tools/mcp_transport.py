"""MCP 传输层（IO）— DESIGN-20261009 §6/§11 P1-B.

两个实现：
- StdioTransport：子进程 newline-delimited JSON-RPC（P0 的进程管理与
  typed dispatch 语义原样迁移：未派发/结果未知/协议错误三分）。
- HttpTransport：Streamable HTTP（单端点 POST）。双时代：
  * 现代（2026-07-28）：每请求 header Mcp-Method/Mcp-Name/
    MCP-Protocol-Version（与 params._meta 一致），无会话；
  * 旧时代（≤2025-11-25）：initialize 握手 + Mcp-Session-Id 会话头，
    202 Accepted 通知，JSON 或 SSE 响应。
- LegacySseTransport（P2-B）：legacy HTTP+SSE 旧传输——GET SSE 流 +
  endpoint 事件下发消息端点 + POST 202 受理、响应经流回送；仅显式
  spec type="sse" 选择；消息端点同 origin 强校验（凭证不越 origin）。

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
from urllib.parse import SplitResult, urljoin, urlsplit

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
        # 401 时由 transport 层填充（WWW-Authenticate 头），供 OAuth 质询解析；
        # 其余状态保持空串。
        self.www_authenticate: str = ""


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


def _url_origin(parts: SplitResult) -> tuple[str, str, int]:
    """(scheme, host, effective_port) origin 三元组（比较用）."""
    scheme = parts.scheme.lower()
    default_port = 443 if scheme == "https" else 80
    return (scheme, (parts.hostname or "").lower(), parts.port or default_port)


class LegacySseTransport(McpTransport):
    """MCP legacy HTTP+SSE 传输（旧时代官方流式形态，P2-B 显式选择）.

    语义（设计 §3/T04；与 Streamable HTTP 的 SSE 响应不同，默认不启用，
    仅 spec type="sse" 显式选择本传输）：
    1. GET <sse_url>（Accept: text/event-stream）→ 常驻 SSE 流；
    2. 服务器 `endpoint` 事件下发消息端点（相对路径或绝对 URL）；
    3. 请求 POST 到消息端点（期望 202 Accepted），响应帧在 SSE 流上按 id 匹配。

    安全（fail-closed，T04）：
    - 消息端点跨 origin（scheme/host/port 任一不同）→ McpProtocolError 拒绝，
      防止携带凭证的 POST 被导向其他源（凭证不越 origin）；
    - 认证头仅随同 origin 消息端点请求发送（由上一条保证）。

    会话失效：POST 404 → McpHttpError(404)（上层置 session_id=None 走既有
    重握手路径；setter 同步作废流与端点，下次请求重建）。断流：pending
    等待者按 McpOutcomeUnknownError 收尾（已派发、结果未知，不自动重放）；
    端点作废后下一次请求重新建流取新端点（旧时代会话随流存亡）。
    """

    #: GET 流 socket 读超时：超时视作断流（下次请求重建），不无限阻塞线程。
    STREAM_IDLE_TIMEOUT_S = 620.0
    #: 建流后等待 endpoint 事件的时限。
    ENDPOINT_WAIT_TIMEOUT_S = 10.0

    _EOF = object()  # 断流哨兵（读线程 → 等待者）

    def __init__(self, name: str, url: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(name)
        self.url = url
        self.extra_headers = {
            str(k): str(v) for k, v in (headers or {}).items() if isinstance(k, str)
        }
        self._sse_parts = urlsplit(url)
        self._sse_origin = _url_origin(self._sse_parts)
        self._stream_lock = threading.Lock()
        self._conn: http.client.HTTPConnection | None = None
        self._reader: threading.Thread | None = None
        self._message_url: str | None = None
        self._endpoint_ready = threading.Event()
        self._endpoint_error: McpError | None = None
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._session_id: str | None = None

    # ── 会话失效路径（McpConnection 404 处理：session_id = None → 重建） ──
    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value
        if value is None:
            self._teardown_stream()

    # ── 流建立/拆除 ──
    def _teardown_stream(self) -> None:
        """作废当前 SSE 流与消息端点（唤醒 pending；下次请求重建）."""
        self._stop.set()
        with self._stream_lock:
            conn, self._conn = self._conn, None
            self._message_url = None
        if conn is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()
        reader = self._reader
        if reader is not None and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        self._wake_pending_eof()

    def _wake_pending_eof(self) -> None:
        with self._pending_lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for q in waiters:
            q.put(self._EOF)

    def _ensure_stream(self) -> None:
        """确保 SSE 流与同 origin 消息端点就绪（幂等；断流后重建）."""
        with self._stream_lock:
            if self._message_url is not None and self._reader is not None and self._reader.is_alive():
                return
            # 清场（旧流残留）
            self._stop.set()
            old_conn, self._conn = self._conn, None
            if old_conn is not None:
                with contextlib.suppress(Exception):  # noqa: BLE001
                    old_conn.close()
            self._message_url = None
            self._endpoint_ready.clear()
            self._endpoint_error = None
            self._stop.clear()
            # 建流
            parts = self._sse_parts
            host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
            if parts.scheme == "https":
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    host, port, timeout=self.ENDPOINT_WAIT_TIMEOUT_S
                )
            elif parts.scheme == "http":
                conn = http.client.HTTPConnection(
                    host, port, timeout=self.ENDPOINT_WAIT_TIMEOUT_S
                )
            else:
                raise McpError(
                    f"MCP legacy SSE {self.name} 端点 scheme 不支持: {parts.scheme!r}（仅 http/https）"
                )
            try:
                conn.request(
                    "GET",
                    (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
                    headers={"Accept": "text/event-stream", **self.extra_headers},
                )
                resp = conn.getresponse()
                sock = conn.sock  # getresponse() 对 will_close 响应会接管 socket
                # 建流完成：读侧改用长空闲超时（超时视作断流，由读线程重建路径接管）
                if sock is not None:
                    sock.settimeout(self.STREAM_IDLE_TIMEOUT_S)
            except _POST_SEND_FAILURES as exc:
                with contextlib.suppress(Exception):  # noqa: BLE001
                    conn.close()
                if isinstance(exc, ConnectionRefusedError):
                    raise McpNotDispatchedError(
                        f"MCP legacy SSE {self.name} 建流被拒绝（请求未派发）: {exc}"
                    ) from exc
                raise McpOutcomeUnknownError(
                    f"MCP legacy SSE {self.name} 建流传输失败（结果未知）: {exc}"
                ) from exc
            if resp.status >= 400:
                raw = resp.read().decode("utf-8", errors="replace")
                with contextlib.suppress(Exception):  # noqa: BLE001
                    conn.close()
                raise McpHttpError(resp.status, None, raw[:500])
            if (resp.getheader("Content-Type") or "").split(";")[0].strip() != "text/event-stream":
                with contextlib.suppress(Exception):  # noqa: BLE001
                    conn.close()
                raise McpProtocolError(
                    f"MCP legacy SSE {self.name} 建流响应非 text/event-stream（非 SSE 服务器？）"
                )
            self._conn = conn
            self._reader = threading.Thread(
                target=self._reader_main,
                args=(conn, resp, sock),
                name=f"mcp-legacy-sse-{self.name}",
                daemon=True,
            )
            self._reader.start()
        if not self._endpoint_ready.wait(self.ENDPOINT_WAIT_TIMEOUT_S):
            self._teardown_stream()
            raise McpProtocolError(
                f"MCP legacy SSE {self.name} 建流后 {self.ENDPOINT_WAIT_TIMEOUT_S}s 内未收到 endpoint 事件"
            )
        if self._endpoint_error is not None:
            error = self._endpoint_error
            self._teardown_stream()
            raise error

    def _reader_main(
        self, conn: http.client.HTTPConnection, resp: http.client.HTTPResponse, sock: Any
    ) -> None:
        """SSE 流读取线程：endpoint 事件定端点；message 帧按 id 分发/通知上送."""
        event_name = ""
        data_lines: list[str] = []
        try:
            while not self._stop.is_set():
                raw = resp.readline()
                if not raw:
                    break  # 服务器关闭流
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if data_lines or event_name:
                        self._handle_stream_event(event_name, "\n".join(data_lines))
                    event_name, data_lines = "", []
                    continue
                if line.startswith(":"):
                    continue  # SSE 注释/keepalive
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip(" "))
        except _POST_SEND_FAILURES as exc:
            logger.info("MCP legacy SSE %s 流中断（下次请求重建）: %s", self.name, exc)
        finally:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()
            with self._stream_lock:
                if self._conn is conn:
                    self._conn = None
                self._message_url = None
            if not self._endpoint_ready.is_set():
                # 流在 endpoint 前结束：让建流方如实失败
                self._endpoint_error = McpProtocolError(
                    f"MCP legacy SSE {self.name} 流在 endpoint 事件前结束"
                )
                self._endpoint_ready.set()
            self._wake_pending_eof()

    def _handle_stream_event(self, event_name: str, payload: str) -> None:
        if event_name == "endpoint":
            self._set_message_endpoint(payload.strip())
            return
        # 旧时代规范默认事件名为 message；容错无名事件（部分实现缺省 event: 行）
        try:
            msg = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        msg_id = msg.get("id")
        if "method" in msg and not ("result" in msg or "error" in msg):
            if msg_id is not None:
                # 服务器→客户端请求（如 sampling）：本端不支持，如实记日志不响应
                logger.info(
                    "MCP legacy SSE %s 收到服务器发起请求（不支持，忽略）: %s",
                    self.name,
                    msg.get("method"),
                )
                return
            raw_params = msg.get("params")
            params = raw_params if isinstance(raw_params, dict) else {}
            handler = self.notification_handler
            if handler is not None:
                try:
                    handler(str(msg.get("method")), params, self.generation)
                except Exception:  # noqa: BLE001
                    logger.debug("MCP legacy SSE %s 通知处理异常", self.name, exc_info=True)
            return
        if isinstance(msg_id, int):
            with self._pending_lock:
                q = self._pending.get(msg_id)
            if q is None:
                return
            if "error" in msg:
                error = msg["error"] if isinstance(msg.get("error"), dict) else None
                q.put(
                    McpProtocolError(
                        f"MCP legacy SSE {self.name} 响应错误: {msg['error']}", error
                    )
                )
            else:
                q.put(("result", msg.get("result") or {}))

    def _set_message_endpoint(self, endpoint: str) -> None:
        """校验并固定消息端点（同 origin 强校验；跨 origin fail-closed）."""
        try:
            absolute = urljoin(self.url, endpoint)
        except ValueError as exc:
            self._endpoint_error = McpProtocolError(
                f"MCP legacy SSE {self.name} endpoint 事件值非法: {endpoint!r:.120}（{exc}）"
            )
            self._endpoint_ready.set()
            return
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            self._endpoint_error = McpProtocolError(
                f"MCP legacy SSE {self.name} 消息端点 scheme 不支持: {parts.scheme!r}"
            )
        elif _url_origin(parts) != self._sse_origin:
            # T04：跨 origin 端点 → 拒绝（凭证不越 origin，fail-closed）
            self._endpoint_error = McpProtocolError(
                f"MCP legacy SSE {self.name} 消息端点跨 origin 被拒: "
                f"{absolute!r:.200}（SSE origin {self._sse_origin}；凭证不越 origin）"
            )
        else:
            with self._stream_lock:
                self._message_url = absolute
            logger.info("MCP legacy SSE %s 消息端点就绪: %s", self.name, absolute)
        self._endpoint_ready.set()

    # ── 发送 ──
    def send_request(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        msg_id = request.get("id")
        if not isinstance(msg_id, int):
            raise McpError("legacy SSE 请求缺少整数 id")
        self._ensure_stream()
        q: queue.Queue = queue.Queue()
        with self._pending_lock:
            self._pending[msg_id] = q
        try:
            self._post_message(request, timeout)
            try:
                item = q.get(timeout=max(float(timeout), 0.1))
            except queue.Empty:
                raise McpOutcomeUnknownError(
                    f"MCP legacy SSE {self.name} {request.get('method')} 等待响应超时"
                    f"（已派发，结果未知，不自动重放）"
                ) from None
            if item is self._EOF:
                raise McpOutcomeUnknownError(
                    f"MCP legacy SSE {self.name} {request.get('method')} 期间断流（结果未知，不自动重放）"
                )
            if isinstance(item, BaseException):
                raise item
            _, result = item
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(msg_id, None)

    def _post_message(self, message: dict[str, Any], timeout: float) -> None:
        """POST 消息到消息端点（202=受理；直接 JSON 响应兜底支持）."""
        url = self._message_url
        assert isinstance(url, str)
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
        body = json.dumps(message)
        headers = {"Content-Type": "application/json", **self.extra_headers}
        target = parts.path or "/"
        if parts.query:  # 消息端点 query 携带会话（如 sessionId），不可丢弃
            target = f"{target}?{parts.query}"
        if parts.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            try:
                conn.request("POST", target, body=body, headers=headers)
                resp = conn.getresponse()
            except ConnectionRefusedError as exc:
                raise McpNotDispatchedError(
                    f"MCP legacy SSE {self.name} POST 被拒绝（请求未派发）: {exc}"
                ) from exc
            except _POST_SEND_FAILURES as exc:
                raise McpOutcomeUnknownError(
                    f"MCP legacy SSE {self.name} POST 传输失败（结果未知，不自动重放）: {exc}"
                ) from exc
            status = resp.status
            content_type = (resp.getheader("Content-Type") or "").split(";")[0].strip()
            if status == 202:
                resp.read()
                return  # 受理；响应帧在 SSE 流上
            if status >= 400:
                raw = resp.read().decode("utf-8", errors="replace")
                error: dict[str, Any] | None = None
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                        error = parsed["error"]
                except json.JSONDecodeError:
                    pass
                raise McpHttpError(status, error, raw[:500])
            # 200/201：容错部分实现直接回 JSON-RPC 响应
            if content_type == "application/json":
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    return
                if isinstance(msg, dict) and msg.get("id") is not None:
                    self._handle_stream_event("message", raw)
                return
            resp.read()
        finally:
            with contextlib.suppress(Exception):  # noqa: BLE001
                conn.close()

    def send_notification(self, notification: dict[str, Any]) -> None:
        try:
            self._ensure_stream()
            self._post_message(notification, HANDSHAKE_TIMEOUT_S)
        except McpError as exc:
            logger.warning("MCP legacy SSE %s 通知发送失败（fail-open）: %s", self.name, exc)

    def close(self) -> None:
        self._teardown_stream()
        self._stop.set()
