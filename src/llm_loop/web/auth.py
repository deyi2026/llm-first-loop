"""Web authentication and CSRF primitives.

The Web entry point has two authentication surfaces:

* browser login -> short-lived, server-side session cookie;
* API/automation -> optional ``Authorization: Bearer WEB_API_KEY``.

Public exposure is fail-closed.  ``WEB_AUTH_REQUIRE=1``, a non-loopback
``WEB_HOST``, or a non-empty ``WEB_ORIGIN_ALLOWLIST`` all make authentication
mandatory.  A Cloudflare tunnel therefore cannot become public merely because
the origin service itself listens on 127.0.0.1.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

SESSION_COOKIE_NAME = "lfl_web_session"
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 310_000
_PASSWORD_MIN_ITERATIONS = 100_000
_PASSWORD_MAX_ITERATIONS = 2_000_000
_DEFAULT_SESSION_TTL_S = 12 * 60 * 60
_MAX_SESSION_TTL_S = 7 * 24 * 60 * 60


def _web_api_key() -> str:
    return os.environ.get("WEB_API_KEY", "").strip()


def _web_login_password_hash() -> str:
    return os.environ.get("WEB_LOGIN_PASSWORD_HASH", "").strip()


def is_loopback(host: str) -> bool:
    """Return whether *host* is a loopback address/name."""
    host = (host or "").strip().strip("[]").lower()
    if host in {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def auth_required() -> bool:
    """Single source of truth for whether Web requests require authentication."""
    if os.environ.get("WEB_AUTH_REQUIRE", "").strip() == "1":
        return True
    if os.environ.get("WEB_ORIGIN_ALLOWLIST", "").strip():
        return True
    return not is_loopback(os.environ.get("WEB_HOST", "127.0.0.1"))


def auth_configured() -> bool:
    """Whether at least one usable authentication mechanism is configured."""
    return bool(_web_api_key() or _web_login_password_hash())


def browser_login_configured() -> bool:
    return bool(_web_login_password_hash())


def normalize_origin(value: str, *, default_scheme: str = "https") -> str:
    """Return a canonical HTTP(S) Origin (scheme + host + optional non-default port).

    Bare host entries are accepted for backward compatibility and mean HTTPS.
    Paths, credentials, queries and fragments are rejected because an Origin does
    not contain them.  This keeps the allowlist an exact browser-origin boundary
    instead of a hostname-only approximation.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Origin 不能为空")
    if "://" not in raw:
        raw = f"{default_scheme}://{raw}"
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Origin 端口无效") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Origin 仅支持 http/https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Origin 不允许包含用户凭据")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Origin 不允许包含 path/query/fragment")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("Origin 缺少 host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Origin host 无效") from exc
    authority = f"[{host}]" if ":" in host else host
    if port is not None and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        authority += f":{port}"
    return f"{scheme}://{authority}"


def configured_origin_allowlist() -> frozenset[str]:
    """Parse WEB_ORIGIN_ALLOWLIST into exact canonical origins.

    Existing bare-host config remains valid and is interpreted as HTTPS, matching
    the public-tunnel deployment this setting was introduced for.
    """
    raw = os.environ.get("WEB_ORIGIN_ALLOWLIST", "").strip()
    if not raw:
        return frozenset()
    origins: set[str] = set()
    for item in raw.split(","):
        value = item.strip()
        if value:
            origins.add(normalize_origin(value))
    return frozenset(origins)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_login_password(password: str, *, iterations: int = _PASSWORD_ITERATIONS) -> str:
    """Create the canonical PBKDF2 password verifier stored in ``.env``.

    The plaintext password is never persisted by this helper.
    """
    if len(password) < 12:
        raise ValueError("Web 登录密码至少需要 12 个字符")
    if not (_PASSWORD_MIN_ITERATIONS <= iterations <= _PASSWORD_MAX_ITERATIONS):
        raise ValueError("PBKDF2 iterations 超出安全范围")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PASSWORD_SCHEME}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def _parse_password_hash(encoded: str) -> tuple[int, bytes, bytes]:
    try:
        scheme, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        iterations = int(raw_iterations)
        salt = _b64decode(raw_salt)
        digest = _b64decode(raw_digest)
    except (ValueError, TypeError) as exc:
        raise ValueError("WEB_LOGIN_PASSWORD_HASH 格式无效") from exc
    if scheme != _PASSWORD_SCHEME:
        raise ValueError("WEB_LOGIN_PASSWORD_HASH 使用了不支持的算法")
    if not (_PASSWORD_MIN_ITERATIONS <= iterations <= _PASSWORD_MAX_ITERATIONS):
        raise ValueError("WEB_LOGIN_PASSWORD_HASH iterations 超出安全范围")
    if len(salt) < 16 or len(digest) != hashlib.sha256().digest_size:
        raise ValueError("WEB_LOGIN_PASSWORD_HASH 参数长度无效")
    return iterations, salt, digest


def verify_login_password(password: str) -> bool:
    """Constant-time verification of the configured browser password."""
    encoded = _web_login_password_hash()
    if not encoded:
        return False
    try:
        iterations, salt, expected = _parse_password_hash(encoded)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def validate_login_password_hash() -> None:
    encoded = _web_login_password_hash()
    if encoded:
        _parse_password_hash(encoded)


def session_ttl_seconds() -> int:
    raw = os.environ.get("WEB_SESSION_TTL_SECONDS", str(_DEFAULT_SESSION_TTL_S)).strip()
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise ValueError("WEB_SESSION_TTL_SECONDS 必须为整数秒") from exc
    if not 300 <= ttl <= _MAX_SESSION_TTL_S:
        raise ValueError("WEB_SESSION_TTL_SECONDS 必须在 300 到 604800 秒之间")
    return ttl


class WebSessionStore:
    """In-memory, revocable browser sessions.

    Restarting the Web process intentionally invalidates all browser sessions.
    This avoids durable bearer cookies and makes server restart a clean revoke-all.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires: dict[str, float] = {}

    def create(self, *, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        expires = time.monotonic() + ttl_seconds
        with self._lock:
            self._purge_locked()
            self._expires[token] = expires
        return token

    def valid(self, token: str) -> bool:
        if not token:
            return False
        now = time.monotonic()
        with self._lock:
            expires = self._expires.get(token)
            if expires is None:
                return False
            if expires <= now:
                self._expires.pop(token, None)
                return False
            return True

    def revoke(self, token: str) -> None:
        if not token:
            return
        with self._lock:
            self._expires.pop(token, None)

    def _purge_locked(self) -> None:
        now = time.monotonic()
        expired = [token for token, expires in self._expires.items() if expires <= now]
        for token in expired:
            self._expires.pop(token, None)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


class LoginRateLimiter:
    """Small per-client brute-force limiter for the single-owner login page."""

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitDecision:
        now = time.monotonic()
        with self._lock:
            bucket = self._failures[key]
            self._prune(bucket, now)
            if len(bucket) < self.max_failures:
                return RateLimitDecision(True)
            retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
            return RateLimitDecision(False, retry_after)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._failures[key]
            self._prune(bucket, now)
            bucket.append(now)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()


def client_rate_limit_key(request: Request) -> str:
    """Prefer Cloudflare's client IP only when the immediate peer is loopback."""
    peer = request.client.host if request.client else ""
    candidate = ""
    if is_loopback(peer):
        candidate = request.headers.get("cf-connecting-ip", "").strip()
        if candidate:
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                candidate = ""
    return candidate or peer or "unknown"


def _bearer_valid(credentials: HTTPAuthorizationCredentials | None) -> bool:
    expected = _web_api_key()
    if not expected or credentials is None or credentials.scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(credentials.credentials, expected)


def _cookie_valid(request: Request | None) -> bool:
    if request is None:
        return False
    store = getattr(request.app.state, "web_sessions", None)
    if not isinstance(store, WebSessionStore):
        return False
    return store.valid(request.cookies.get(SESSION_COOKIE_NAME, ""))


def request_authenticated(
    request: Request | None,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> bool:
    return _bearer_valid(credentials) or _cookie_valid(request)


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    request: Request = None,  # type: ignore[assignment]
) -> None:
    """Authorize protected routes by API bearer or browser session cookie.

    The historical name is kept for compatibility with callers/tests.  It now
    represents the complete Web authentication gate rather than Bearer-only auth.
    """
    if not auth_required():
        return
    if not auth_configured():
        raise HTTPException(
            status_code=503,
            detail="Web 鉴权已启用但未配置 WEB_LOGIN_PASSWORD_HASH 或 WEB_API_KEY，fail-closed 拒绝服务。",
        )
    if request_authenticated(request, credentials):
        return
    raise HTTPException(status_code=401, detail="需要登录或有效的 Authorization: Bearer 令牌。")


def validate_auth_require() -> None:
    validate_login_password_hash()
    if browser_login_configured():
        session_ttl_seconds()
    if os.environ.get("WEB_AUTH_REQUIRE", "").strip() == "1" and not auth_configured():
        raise RuntimeError(
            "WEB_AUTH_REQUIRE=1 但未配置 WEB_LOGIN_PASSWORD_HASH 或 WEB_API_KEY："
            "fail-closed 拒绝启动。"
        )


def validate_binding(host: str) -> None:
    """A non-loopback listener must never start without an auth mechanism."""
    if not is_loopback(host) and not auth_configured():
        raise RuntimeError(
            "远程监听（WEB_HOST 非回环）须先配置 WEB_LOGIN_PASSWORD_HASH 或 WEB_API_KEY；"
            "本机使用请保持 WEB_HOST=127.0.0.1。"
        )


def validate_origin_allowlist() -> None:
    """Validate public origins and require auth whenever any are configured."""
    raw = os.environ.get("WEB_ORIGIN_ALLOWLIST", "").strip()
    if not raw:
        return
    try:
        configured_origin_allowlist()
    except ValueError as exc:
        raise RuntimeError(f"WEB_ORIGIN_ALLOWLIST 无效：{exc}") from exc
    if not auth_configured():
        raise RuntimeError(
            "WEB_ORIGIN_ALLOWLIST 非空（隧道/反代公网暴露意图）但没有可用鉴权："
            "请先配置 WEB_LOGIN_PASSWORD_HASH 或 WEB_API_KEY。"
        )
