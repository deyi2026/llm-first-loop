"""MCP HTTP OAuth 与凭证绑定（设计 §8.2；FR-05）.

P1-B 协议层切片（mcp_protocol=帧 / mcp_transport=通道 / 本模块=身份）：
- credential_ref 解析：SecretStore 中性接口（env:VAR 实现）；缺凭证可诊断
  （McpCredentialError 附服务器名与 ref，不泄漏值本身）
- 受保护资源发现：401 + WWW-Authenticate（resource_metadata）→
  RFC 9728 资源元数据 → RFC 8414 授权服务器元数据
- 动态客户端注册（RFC 7591，服务器声明 registration_endpoint 时）
- 授权码 + PKCE(S256) + state；授权 URL 交由上层完成"真实授权请求"
  （Web 发起授权交接属后续阶段；本层提供 pending 授权事实与 code 交换）
- client_credentials（S2S）：凭证 ref 解析出 secret 且 AS 支持时直接换 token
- 令牌缓存按（资源源， 授权身份）隔离——同端点不同 credential_ref 不共享
  token/身份；单写者加锁；401 使缓存 token 失效一次

明确边界：本层不交互式获取授权（不弹 UI / 不发消息）；token/secret
不进日志、不进安装记录；非 loopback 场景 TLS 由调用方（transport）约束。
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import secrets
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from llm_loop.config import _raw_env
from llm_loop.tools.mcp_protocol import McpError

logger = logging.getLogger(__name__)

_AUTH_HTTP_TIMEOUT_S = 10.0
#: 访问令牌提前失效余量（秒）：避免边界竞态（刚拿到就过期）
_TOKEN_EXPIRY_MARGIN_S = 30.0
#: pending 授权环形缓冲上限（诊断事实；只存 URL/state，不存机密）
_PENDING_AUTH_MAX = 32


class McpCredentialError(McpError):
    """凭证缺失/不可解析（可诊断：附服务器名与 credential_ref，不泄漏值）."""

    def __init__(self, server: str, ref: str, detail: str) -> None:
        super().__init__(f"MCP 服务器 {server} 凭证不可用（credential_ref={ref}）: {detail}")
        self.server = server
        self.ref = ref


class McpAuthRequiredError(McpError):
    """需要交互式授权（携带 authorization_url 与 state；不自动重放）."""

    def __init__(self, server: str, authorization_url: str, state: str) -> None:
        super().__init__(f"MCP 服务器 {server} 需要授权：完成浏览器授权后以 code+state 交换令牌")
        self.server = server
        self.authorization_url = authorization_url
        self.state = state


class SecretStore(Protocol):
    """凭证解析中性接口（值只在内存短暂存活，不落日志）."""

    def resolve(self, ref: str) -> str | None: ...


class EnvSecretStore:
    """`env:VAR_NAME` 引用 → 统一配置层读取；未定义为缺凭证（可诊断）.

    借道 config._raw_env（而非直读 os.environ）：环境访问点收口，
    且剥离行内注释避免脏值（runtime env access 审计）。
    """

    def resolve(self, ref: str) -> str | None:
        if not ref.startswith("env:"):
            return None
        value = _raw_env(ref[len("env:") :])
        return value or None


@dataclass(frozen=True)
class AuthorizationServerMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    grant_types: tuple[str, ...]
    code_challenge_methods: tuple[str, ...]

    @property
    def supports_pkce_s256(self) -> bool:
        return "S256" in self.code_challenge_methods

    @property
    def supports_client_credentials(self) -> bool:
        return "client_credentials" in self.grant_types


@dataclass
class _Token:
    access_token: str
    expires_at: float
    token_type: str = "Bearer"


@dataclass
class _PendingAuthorization:
    server: str
    state: str
    code_verifier: str
    authorization_url: str
    client_id: str
    token_endpoint: str
    resource: str
    created_at: float = field(default_factory=time.monotonic)


_TOKEN_LOCK = threading.Lock()
_TOKENS: dict[tuple[str, str], _Token] = {}
_CLIENT_LOCK = threading.Lock()
_CLIENTS: dict[str, str] = {}  # registration_endpoint → client_id
_PENDING_AUTH: deque[_PendingAuthorization] = deque(maxlen=_PENDING_AUTH_MAX)
_PENDING_LOCK = threading.Lock()


def pending_authorizations() -> tuple[dict[str, Any], ...]:
    """最近 pending 授权事实（URL/state/服务器；供诊断与上层交接）."""
    with _PENDING_LOCK:
        return tuple(
            {
                "server": p.server,
                "authorization_url": p.authorization_url,
                "state": p.state,
                "created_at": p.created_at,
            }
            for p in _PENDING_AUTH
        )


def _http_json(
    method: str, url: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """最小 JSON GET/POST（OAuth 元数据/注册/令牌端点用；每请求独立建连）."""
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        # URL 残缺（无 host）时显式失败，而不是依赖标准库对 host=None 的隐式行为
        raise ValueError(f"MCP OAuth endpoint URL missing host: {url!r}")
    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            host, parts.port or 443, timeout=_AUTH_HTTP_TIMEOUT_S
        )
    else:
        conn = http.client.HTTPConnection(
            host, parts.port or 80, timeout=_AUTH_HTTP_TIMEOUT_S
        )
    try:
        payload = json.dumps(body) if body is not None else None
        merged = {"Accept": "application/json"}
        if payload is not None:
            merged["Content-Type"] = "application/json"
        merged.update(headers or {})
        conn.request(method, parts.path or "/", body=payload, headers=merged)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        status = resp.status
    finally:
        conn.close()
    parsed: dict[str, Any] | list[Any] | None = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
    return status, parsed


def parse_www_authenticate(header: str) -> dict[str, str]:
    """解析 WWW-Authenticate（Bearer 质询；提取 resource_metadata 等 named param）."""
    params: dict[str, str] = {}
    scheme, _, rest = header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return params
    # 形如 key="value", key2="value2"（RFC 9728 值均为带引号 URL）
    for chunk in rest.split(","):
        key, sep, value = chunk.partition("=")
        if sep:
            params[key.strip().lower()] = value.strip().strip('"')
    return params


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class McpOAuthClient:
    """单服务器 OAuth 客户端（identity = credential_ref 解析出的授权身份）."""

    def __init__(
        self,
        server: str,
        resource_url: str,
        secret_store: SecretStore | None = None,
        credential_ref: str | None = None,
    ) -> None:
        self.server = server
        self.resource_url = resource_url
        self.secret_store = secret_store or EnvSecretStore()
        self.credential_ref = credential_ref
        self._cache_key = (_origin(resource_url), credential_ref or "<anonymous>")

    # ── 主入口：401 响应处理 ──
    def on_401(self, www_authenticate: str) -> str:
        """401 质询处理：缓存/换新 token，成功返回 Bearer 值.

        - 命中有效缓存 → 直接返回（401 视作令牌提前失效，先丢弃再换新）
        - 凭证可用且 AS 支持 client_credentials → 直接换取（非交互）
        - 否则发起授权码 + PKCE → 抛 McpAuthRequiredError（交上层交接）
        """
        params = parse_www_authenticate(www_authenticate)
        resource_meta_url = params.get("resource_metadata")
        if not resource_meta_url:
            raise McpCredentialError(
                self.server,
                self.credential_ref or "",
                "401 质询未带 resource_metadata，无法发现授权服务器",
            )
        # 401 = 缓存令牌已被服务器拒绝：丢弃后重取
        with _TOKEN_LOCK:
            _TOKENS.pop(self._cache_key, None)
        metadata = self._discover(resource_meta_url)
        token = self._token_via_client_credentials(metadata)
        if token is not None:
            return token.access_token
        raise self._begin_authorization_code(metadata)

    def cached_bearer(self) -> str | None:
        """未过期的缓存 token（请求头预置用；不触发网络）."""
        with _TOKEN_LOCK:
            token = _TOKENS.get(self._cache_key)
            if token and token.expires_at - _TOKEN_EXPIRY_MARGIN_S > time.monotonic():
                return token.access_token
        return None

    # ── 发现链 ──
    def _discover(self, resource_meta_url: str) -> AuthorizationServerMetadata:
        status, resource_meta = _http_json("GET", resource_meta_url)
        if status != 200 or not isinstance(resource_meta, dict):
            raise McpCredentialError(
                self.server,
                self.credential_ref or "",
                f"受保护资源元数据不可用（{resource_meta_url}, status={status}）",
            )
        servers = resource_meta.get("authorization_servers")
        if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
            raise McpCredentialError(
                self.server, self.credential_ref or "", "资源元数据缺少 authorization_servers"
            )
        issuer = servers[0]
        well_known = issuer.rstrip("/") + "/.well-known/oauth-authorization-server"
        status, meta = _http_json("GET", well_known)
        if status != 200 or not isinstance(meta, dict):
            raise McpCredentialError(
                self.server,
                self.credential_ref or "",
                f"授权服务器元数据不可用（{well_known}, status={status}）",
            )
        return AuthorizationServerMetadata(
            issuer=issuer,
            authorization_endpoint=str(meta.get("authorization_endpoint") or ""),
            token_endpoint=str(meta.get("token_endpoint") or ""),
            registration_endpoint=(
                str(meta["registration_endpoint"]) if meta.get("registration_endpoint") else None
            ),
            grant_types=tuple(
                str(g) for g in (meta.get("grant_types_supported") or ["authorization_code"])
            ),
            code_challenge_methods=tuple(
                str(m) for m in (meta.get("code_challenge_methods_supported") or ["S256"])
            ),
        )

    # ── 客户端注册（DCR）──
    def _ensure_client_id(self, metadata: AuthorizationServerMetadata) -> str:
        if not metadata.registration_endpoint:
            raise McpCredentialError(
                self.server,
                self.credential_ref or "",
                "授权服务器不支持动态客户端注册且未提供 client_id",
            )
        with _CLIENT_LOCK:
            cached = _CLIENTS.get(metadata.registration_endpoint)
            if cached:
                return cached
        status, reg = _http_json(
            "POST",
            metadata.registration_endpoint,
            body={
                "client_name": "llm-first-loop-mcp",
                "grant_types": ["authorization_code", "client_credentials"],
                "token_endpoint_auth_method": "none",  # 公共客户端 + PKCE
                "redirect_uris": ["http://127.0.0.1/callback"],
            },
        )
        if status not in (200, 201) or not isinstance(reg, dict) or not reg.get("client_id"):
            raise McpCredentialError(
                self.server,
                self.credential_ref or "",
                f"动态客户端注册失败（status={status}）",
            )
        client_id = str(reg["client_id"])
        with _CLIENT_LOCK:
            _CLIENTS[metadata.registration_endpoint] = client_id
        return client_id

    # ── 令牌获取 ──
    def _token_via_client_credentials(self, metadata: AuthorizationServerMetadata) -> _Token | None:
        """S2S 路径：credential_ref 解析出 secret 且 AS 支持 client_credentials."""
        if not self.credential_ref:
            return None
        if not metadata.supports_client_credentials:
            return None
        secret = self.secret_store.resolve(self.credential_ref)
        if secret is None:
            raise McpCredentialError(
                self.server, self.credential_ref, "凭证未定义或引用格式不受支持"
            )
        body = {
            "grant_type": "client_credentials",
            "client_id": self._ensure_client_id(metadata),
            "resource": self.resource_url,
        }
        status, token_resp = _http_json(
            "POST",
            metadata.token_endpoint,
            body=body,
            headers={"Authorization": f"Bearer {secret}"},
        )
        if status != 200 or not isinstance(token_resp, dict) or not token_resp.get("access_token"):
            logger.info(
                "MCP %s client_credentials 换取失败（status=%s），转授权码流",
                self.server,
                status,
            )
            return None
        return self._store_token(token_resp)

    def _begin_authorization_code(
        self, metadata: AuthorizationServerMetadata
    ) -> McpAuthRequiredError:
        """发起授权码 + PKCE：登记 pending，抛带 authorization_url 的可诊断错误."""
        if not metadata.authorization_endpoint or not metadata.token_endpoint:
            raise McpCredentialError(
                self.server, self.credential_ref or "", "授权服务器元数据缺少端点"
            )
        client_id = self._ensure_client_id(metadata)
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "resource": self.resource_url,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        authorization_url = f"{metadata.authorization_endpoint}?{query}"
        pending = _PendingAuthorization(
            server=self.server,
            state=state,
            code_verifier=verifier,
            authorization_url=authorization_url,
            client_id=client_id,
            token_endpoint=metadata.token_endpoint,
            resource=self.resource_url,
        )
        with _PENDING_LOCK:
            _PENDING_AUTH.append(pending)
        logger.info(
            "MCP %s 需要交互式授权（state=%s…，URL 已登记 pending）", self.server, state[:6]
        )
        return McpAuthRequiredError(self.server, authorization_url, state)

    def complete_authorization(self, code: str, state: str) -> None:
        """外部完成授权后：以 code+state 交换令牌（PKCE 校验在 AS 侧）."""
        with _PENDING_LOCK:
            match = next(
                (p for p in _PENDING_AUTH if p.state == state and p.server == self.server), None
            )
            if match is None:
                raise McpCredentialError(
                    self.server,
                    self.credential_ref or "",
                    "无匹配 pending 授权（state 不符或已过期）",
                )
            _PENDING_AUTH.remove(match)
        status, token_resp = _http_json(
            "POST",
            match.token_endpoint,
            body={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": match.client_id,
                "code_verifier": match.code_verifier,
                "resource": match.resource,
            },
        )
        if status != 200 or not isinstance(token_resp, dict) or not token_resp.get("access_token"):
            raise McpCredentialError(
                self.server,
                self.credential_ref or "",
                f"授权码交换失败（status={status}）",
            )
        self._store_token(token_resp)
        logger.info("MCP %s 授权完成，令牌已缓存（身份=%s）", self.server, self._cache_key[1])

    def _store_token(self, token_resp: dict[str, Any]) -> _Token:
        ttl = float(token_resp.get("expires_in") or 3600)
        token = _Token(
            access_token=str(token_resp["access_token"]),
            expires_at=time.monotonic() + ttl,
            token_type=str(token_resp.get("token_type") or "Bearer"),
        )
        with _TOKEN_LOCK:
            _TOKENS[self._cache_key] = token
        return token
