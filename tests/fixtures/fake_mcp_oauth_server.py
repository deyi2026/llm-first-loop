"""本地 OAuth 授权服务器 fixture（FR-05 测试契约）.

模拟 MCP HTTP OAuth 所需端点（全部 loopback、无状态持久化）：
- GET  /.well-known/oauth-protected-resource → RFC 9728 资源元数据
- GET  /.well-known/oauth-authorization-server → RFC 8414 AS 元数据
       （声明 authorization_code + client_credentials + S256 + DCR）
- POST /register → 动态客户端注册（client_id）
- GET  /authorize → 校验 PKCE 参数、登记 challenge、直接签发 code+state
       （测试契约：不经浏览器重定向，直接返回 JSON）
- POST /token：
       client_credentials：任意 Bearer secret 均可（identity = 该 secret；
       模拟"每个客户端凭证一个身份"），校验 resource 参数
       authorization_code：code 单次有效；code_verifier(S256) 必须匹配
       /authorize 登记的 challenge

诊断计数器：register_count / token_exchange_count / pkce_verified。
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.client_counter = 0
        self.code_counter = 0
        self.token_counter = 0
        self.register_count = 0
        self.token_exchange_count = 0
        self.pkce_verified = False
        # state → PKCE challenge（authorize 登记，token 校验）
        self.challenges: dict[str, tuple[str, str]] = {}  # state → (challenge, client_id)
        # code → (state, client_id)（单次使用）
        self.codes: dict[str, tuple[str, str]] = {}
        # token → {"identity": str, "grant": str}
        self.tokens: dict[str, dict[str, str]] = {}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FakeOAuthAS/1.0"

    @property
    def state(self) -> _State:
        return self.server.state  # type: ignore[attr-defined]

    @property
    def base(self) -> str:
        return self.server.base_url  # type: ignore[attr-defined]

    def log_message(self, *args: Any) -> None:  # 静音
        pass

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/.well-known/oauth-protected-resource":
            self._send(200, {"authorization_servers": [self.base]})
            return
        if path == "/.well-known/oauth-authorization-server":
            self._send(
                200,
                {
                    "issuer": self.base,
                    "authorization_endpoint": f"{self.base}/authorize",
                    "token_endpoint": f"{self.base}/token",
                    "registration_endpoint": f"{self.base}/register",
                    "grant_types_supported": ["authorization_code", "client_credentials"],
                    "code_challenge_methods_supported": ["S256"],
                    "response_types_supported": ["code"],
                },
            )
            return
        if path == "/authorize":
            query = parse_qs(urlsplit(self.path).query)
            state = (query.get("state") or [""])[0]
            challenge = (query.get("code_challenge") or [""])[0]
            method = (query.get("code_challenge_method") or [""])[0]
            client_id = (query.get("client_id") or [""])[0]
            if (
                (query.get("response_type") or [""])[0] != "code"
                or not state
                or not challenge
                or method != "S256"
                or not client_id
            ):
                self._send(400, {"error": "invalid_request"})
                return
            with self.state.lock:
                self.state.challenges[state] = (challenge, client_id)
                self.state.code_counter += 1
                code = f"code-{self.state.code_counter}"
                self.state.codes[code] = (state, client_id)
            self._send(200, {"code": code, "state": state})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid_request"})
            return
        if not isinstance(body, dict):
            self._send(400, {"error": "invalid_request"})
            return
        if path == "/register":
            with self.state.lock:
                self.state.register_count += 1
                self.state.client_counter += 1
                client_id = f"client-{self.state.client_counter}"
            self._send(200, {"client_id": client_id, "token_endpoint_auth_method": "none"})
            return
        if path == "/token":
            self._handle_token(body)
            return
        self._send(404, {"error": "not_found"})

    def _handle_token(self, body: dict[str, Any]) -> None:
        grant = str(body.get("grant_type") or "")
        if grant == "client_credentials":
            auth = self.headers.get("Authorization") or ""
            if not auth.startswith("Bearer ") or not auth[len("Bearer ") :]:
                self._send(401, {"error": "invalid_client"})
                return
            identity = auth[len("Bearer ") :]
            self._issue_token({"identity": identity, "grant": grant})
            return
        if grant == "authorization_code":
            code = str(body.get("code") or "")
            verifier = str(body.get("code_verifier") or "")
            client_id = str(body.get("client_id") or "")
            with self.state.lock:
                record = self.state.codes.pop(code, None)  # 单次使用
            if record is None:
                self._send(400, {"error": "invalid_grant"})
                return
            state, issued_client = record
            with self.state.lock:
                challenge_pair = self.state.challenges.get(state)
            if (
                challenge_pair is None
                or client_id != issued_client
                or client_id != challenge_pair[1]
            ):
                self._send(400, {"error": "invalid_grant"})
                return
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            if expected != challenge_pair[0]:
                self._send(400, {"error": "invalid_grant", "error_description": "pkce_mismatch"})
                return
            with self.state.lock:
                self.state.pkce_verified = True
                self.state.challenges.pop(state, None)
            self._issue_token({"identity": f"user:{state[:8]}", "grant": grant})
            return
        self._send(400, {"error": "unsupported_grant_type"})

    def _issue_token(self, binding: dict[str, str]) -> None:
        with self.state.lock:
            self.state.token_exchange_count += 1
            self.state.token_counter += 1
            token = f"tok-{self.state.token_counter}"
            self.state.tokens[token] = binding
        self._send(200, {"access_token": token, "token_type": "Bearer", "expires_in": 3600})


class FakeOAuthAuthorizationServer:
    """loopback OAuth AS（ThreadingHTTPServer）；is_valid_token 供 MCP 门禁复用."""

    def __init__(self) -> None:
        self.state = _State()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.state = self.state
        self._httpd.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        import threading as _t

        self.thread = _t.Thread(target=self._httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return str(self._httpd.base_url)

    @property
    def protected_metadata_url(self) -> str:
        return f"{self.url}/.well-known/oauth-protected-resource"

    @property
    def register_count(self) -> int:
        with self.state.lock:
            return self.state.register_count

    @property
    def token_exchange_count(self) -> int:
        with self.state.lock:
            return self.state.token_exchange_count

    @property
    def pkce_verified(self) -> bool:
        with self.state.lock:
            return self.state.pkce_verified

    def is_valid_token(self, token: str | None) -> bool:
        if not token:
            return False
        with self.state.lock:
            return token in self.state.tokens

    def token_identity(self, token: str) -> str | None:
        with self.state.lock:
            binding = self.state.tokens.get(token)
            return binding["identity"] if binding else None

    def authorize(self, authorization_url: str) -> dict[str, str]:
        """测试 helper：GET /authorize（authorization_url 来自 McpAuthRequiredError）."""
        import http.client
        from urllib.parse import urlsplit

        parts = urlsplit(authorization_url)
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)
        try:
            conn.request("GET", f"{parts.path}?{parts.query}")
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()
        assert isinstance(payload, dict)
        return payload

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self.thread.join(timeout=3)
