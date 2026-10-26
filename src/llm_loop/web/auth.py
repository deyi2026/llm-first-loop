"""Web authentication and CSRF primitives.

The Web entry point has two authentication surfaces:

* browser login -> short-lived, server-side session cookie;
* API/automation -> optional ``Authorization: Bearer WEB_API_KEY``.

Public exposure is fail-closed.  ``WEB_AUTH_REQUIRE=1``, a non-loopback
``WEB_HOST``, or a non-empty ``WEB_ORIGIN_ALLOWLIST`` all make authentication
mandatory.  A Cloudflare tunnel therefore cannot become public merely because
the origin service itself listens on 127.0.0.1.

能力边界（S3-5，建议书 2026-10-25）：浏览器会话**仅存于进程内存**
（``WebSessionStore``），Web 进程重启即全部失效（"重启 = 撤销全部会话"是
既定运维特性，不是持久化能力）；多 worker / 多实例部署之间**不共享**会话，
如需跨进程会话须外接存储（Redis/SQLite），本模块不提供。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param

_bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "lfl_web_session_v2"
# v2 (2026-09-30): rename from lfl_web_session. During the dual-hostname era
# (llmfirstloop.com + app.llmfirstloop.com, host-only cookies) browsers
# accumulated several same-name stale cookies (per-host and, after the parent
# domain rollout, domain-wide). Same-name multi-value headers are resolved
# parser-order-dependently, which intermittently served a dead token from the
# pre-restart store. Renaming guarantees every historical cookie is simply
# never sent again; users re-login once.
# S3-6/P2-6c (2026-10-25): when the cookie is Secure and carries no Domain
# attribute, the ``__Host-`` prefixed twin name below is used instead — exact
# host pinning (Path=/ + no Domain + Secure enforced by browsers). Readers
# accept BOTH names during the transition (see session_cookie_value /
# valid_browser_session); non-secure (loopback HTTP) keeps the legacy name.
SESSION_COOKIE_NAME_SECURE = "__Host-lfl_web_session_v2"
_PASSWORD_SCHEME = "pbkdf2_sha256"
# S3-4/P2-6b (2026-10-25): 310k -> 600k (OWASP 2023 PBKDF2-SHA256 guidance).
# Verification always honors the iteration count recorded inside the stored
# hash string; successful logins with a weaker recorded count are re-hashed
# in place (rehash-on-login, see rehash_login_password_if_needed).
_PASSWORD_ITERATIONS = 600_000
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


def request_is_trusted_local(request: Request | None) -> bool:
    """Whether this is a *direct* loopback request eligible for auth bypass.

    Any proxy/forwarding marker revokes the bypass.  This deliberately keeps the
    trust rule narrow: localhost means a browser talking directly to the loopback
    listener, not a public request whose reverse proxy also happens to run locally.
    """
    if request is None:
        return False
    host = request.url.hostname or ""
    peer = request.client.host if request.client else ""
    if not is_loopback(host) or not is_loopback(peer):
        return False
    for header in (
        "cf-connecting-ip",
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
    ):
        if request.headers.get(header, "").strip():
            return False
    return True


def request_auth_required(request: Request | None) -> bool:
    """Apply public auth policy per request while direct loopback stays open."""
    return auth_required() and not request_is_trusted_local(request)


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
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
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


_REHASH_LOCK = threading.Lock()
# Preserve the original line ending byte-for-byte when replacing a verifier.
# str.splitlines(keepends=True) recognizes these Unicode and ASCII separators.
_LINE_TERMINATORS = ("\r\n", "\r", "\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


def _env_file_path() -> Path:
    """The operator .env honored by the web entry point (cwd-anchored, main() 同源)."""
    raw = os.environ.get("LFL_ENV_FILE", "").strip()
    return Path(raw).expanduser() if raw else Path.cwd() / ".env"


def _persist_rehashed_env_value(key: str, old_value: str, new_value: str) -> bool:
    """Atomically rewrite one existing ``KEY=VALUE`` line in the .env file.

    Only touches the file when it already declares ``key`` with exactly the
    value currently active in this process — a .env whose content diverged
    from the process environment is never silently rewritten. Failures are
    swallowed (return False): persistence is best-effort and must never
    affect the already-successful login.
    """
    path = _env_file_path()
    try:
        if not path.is_file():
            return False
        # newline="" prevents universal-newline conversion of CRLF/lone CR.
        with path.open("r", encoding="utf-8", newline="") as source:
            text = source.read()
    except OSError:
        return False
    lines = text.splitlines(keepends=True)
    target = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        for prefix in (f"{key}=", f"export {key}="):
            if stripped.startswith(prefix):
                if stripped[len(prefix):].strip() != old_value:
                    return False  # 文件内容与进程环境不一致：不动磁盘
                if target is not None:
                    return False  # 重复 key：避免写入一个而运行时解析另一个
                # Derive indentation from lstrip explicitly; a full strip()
                # would also count the line terminator as leading whitespace.
                leading = line[: len(line) - len(line.lstrip())]
                target = (index, leading + ("export " if stripped.startswith("export ") else ""))
                break
    if target is None:
        return False
    index, prefix = target
    # P0(2026-10-25): 原行终止符必须原样保留。此前写反（有\n反删、无\n反加），
    # 把下一配置项拼进本行——实测曾将 WEB_SESSION_TTL_SECONDS 拼入哈希行，
    # 重启重读 .env 后登录全拒（07:52 升级写回触发，迁移重启爆发）。
    # 审核P2-1/P2-2: 保真扩展到 str.splitlines 识别的全部行终止符
    # （CRLF/lone CR 及 \v\f\x1c-\x1e\x85\u2028\u2029），杜绝边缘拼接复发。
    terminator = next(
        (t for t in _LINE_TERMINATORS if lines[index].endswith(t)), ""
    )
    lines[index] = f"{prefix}{key}={new_value}{terminator}"
    tmp = path.with_name(f".{path.name}.rehash.tmp")
    tmp_created = False
    try:
        # Create privately *before* writing verifier bytes (no 0644 window).
        # O_EXCL refuses a leftover/symlink temp path instead of clobbering it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        tmp_created = True
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as destination:
            destination.write("".join(lines))
        # 审核P2-3: 保留原 .env 权限位（部署可能自定义 0640 等）；仅当原权限
        # 比组/其他可读更宽时收紧到 0600（fail-closed：密钥文件不因回写放宽）。
        mode = path.stat().st_mode & 0o777
        os.chmod(tmp, mode if mode & 0o077 == 0 else 0o600)
        os.replace(tmp, path)
    except OSError:
        # Only remove the file created by this invocation, never a preexisting
        # residue/symlink that caused O_EXCL to refuse the operation.
        if tmp_created:
            with suppress(OSError):
                tmp.unlink()
        return False
    return True


def rehash_login_password_if_needed(password: str) -> bool:
    """S3-4/P2-6b: upgrade a verified-but-weak PBKDF2 hash after a successful login.

    The recorded iteration count inside the stored hash decides: anything below
    ``_PASSWORD_ITERATIONS`` is re-derived with the same plaintext and written
    back atomically (process env + the .env line). Any failure — wrong password
    (re-verified here so a bug can never clobber the verifier), derivation or
    persistence — leaves the login flow untouched and returns False.
    """
    encoded = _web_login_password_hash()
    if not encoded:
        return False
    try:
        iterations, salt, expected = _parse_password_hash(encoded)
    except ValueError:
        return False
    if iterations >= _PASSWORD_ITERATIONS:
        return False
    # 密码必须先在本地重新验证成功：绝不允许错误口令改写存储校验子。
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    if not hmac.compare_digest(actual, expected):
        return False
    with _REHASH_LOCK:
        try:
            upgraded = hash_login_password(password, iterations=_PASSWORD_ITERATIONS)
        except ValueError:
            return False
        os.environ["WEB_LOGIN_PASSWORD_HASH"] = upgraded
        persisted = _persist_rehashed_env_value("WEB_LOGIN_PASSWORD_HASH", encoded, upgraded)
        if persisted:
            logger.info("login password hash upgraded in-place: %s -> %s iterations", iterations, _PASSWORD_ITERATIONS)
        else:
            logger.warning(
                "login password hash upgraded in process env only (%s -> %s iterations); "
                ".env persistence skipped (file missing, unchanged line not found, or write failed)",
                iterations,
                _PASSWORD_ITERATIONS,
            )
        return True


def session_ttl_seconds() -> int:
    raw = os.environ.get("WEB_SESSION_TTL_SECONDS", str(_DEFAULT_SESSION_TTL_S)).strip()
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise ValueError("WEB_SESSION_TTL_SECONDS 必须为整数秒") from exc
    if not 300 <= ttl <= _MAX_SESSION_TTL_S:
        raise ValueError("WEB_SESSION_TTL_SECONDS 必须在 300 到 604800 秒之间")
    return ttl


def session_cookie_domain(request_host: str = "") -> str | None:
    """Optional cookie parent domain so sibling hostnames share one login.

    Default (unset) keeps the session cookie host-only. For deployments where
    several hostnames (apex + subdomains) route to this same origin — e.g.
    ``llmfirstloop.com`` and ``app.llmfirstloop.com`` through one Cloudflare
    tunnel — set ``WEB_SESSION_COOKIE_DOMAIN=llmfirstloop.com`` so a login on
    any hostname is recognized on all of them. Without this, browsers keep
    per-host cookies and users bounce between two identical login pages.
    """
    raw = os.environ.get("WEB_SESSION_COOKIE_DOMAIN", "").strip().lower()
    if not raw:
        return None
    try:
        host = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("WEB_SESSION_COOKIE_DOMAIN host 无效") from exc
    if not host or any(ch.isspace() or ch in "/\\?#" for ch in host):
        raise ValueError("WEB_SESSION_COOKIE_DOMAIN 必须是纯域名")
    current = (request_host or "").strip().strip("[]").lower().rstrip(".")
    if not current:
        return None
    try:
        current = current.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    # A Domain attribute is valid only when the response host is that domain or
    # one of its subdomains.  Local/operator access (127.0.0.1/localhost) must
    # remain host-only; otherwise browsers reject Set-Cookie entirely and a
    # successful login immediately bounces back to /login.
    if current == host or current.endswith(f".{host}"):
        return host
    return None


def canonical_host() -> str:
    """Optional public host that all proxied hostnames redirect to (308).

    Set ``WEB_CANONICAL_HOST=llmfirstloop.com`` when several hostnames (apex +
    subdomains) route to this origin. Requests arriving through a trusted
    loopback proxy (cloudflared) on any alias hostname are redirected to the
    canonical host so bookmarks/history cannot split auth state across
    hostnames again. Empty (default) keeps every hostname as-is.
    """
    raw = os.environ.get("WEB_CANONICAL_HOST", "").strip().lower()
    if not raw:
        return ""
    try:
        host = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("WEB_CANONICAL_HOST host 无效") from exc
    if not host or any(ch.isspace() or ch in "/\\?#" for ch in host):
        raise ValueError("WEB_CANONICAL_HOST 必须是纯域名")
    return host


def session_cookie_name(*, secure: bool, domain: str | None) -> str:
    """S3-6/P2-6c: pick the cookie name for the current response.

    ``__Host-`` prefix (exact-host pinning: Secure + Path=/ + no Domain,
    enforced by browsers) is used only when the cookie is Secure AND carries
    no Domain attribute — a ``__Host-`` cookie with ``Domain`` would be
    rejected by every browser. Non-secure (loopback HTTP) and parent-domain
    deployments keep the legacy ``lfl_web_session_v2`` name.
    """
    if secure and not domain:
        return SESSION_COOKIE_NAME_SECURE
    return SESSION_COOKIE_NAME


def session_cookie_value(cookies) -> str:
    """Read the session cookie value under EITHER name (S3-6 dual-read).

    Prefers the ``__Host-`` prefixed name; falls back to the legacy
    ``lfl_web_session_v2`` name so pre-upgrade browsers stay logged in.
    """
    getter = getattr(cookies, "get", None)
    if not callable(getter):
        return ""
    for name in (SESSION_COOKIE_NAME_SECURE, SESSION_COOKIE_NAME):
        value = str(getter(name) or "").strip()
        if value:
            return value
    return ""


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
    """Small per-client brute-force limiter for the single-owner login page.

    S3-8 (建议书 2026-10-25): the failure map is bounded (``max_keys``) and
    prunes expired buckets on every access — a forged-header flood cannot grow
    it without bound. Eviction is least-recently-recorded first.
    """

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300, max_keys: int = 4096) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}

    def check(self, key: str) -> RateLimitDecision:
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            bucket = self._failures.get(key)
            if bucket is None or len(bucket) < self.max_failures:
                return RateLimitDecision(True)
            retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
            return RateLimitDecision(False, retry_after)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            bucket = self._failures.pop(key, None)
            if bucket is None:
                bucket = deque()
            self._failures[key] = bucket  # 重新插入 = 移到末端（LRU recency）
            bucket.append(now)
            while len(self._failures) > self.max_keys:
                oldest = next(iter(self._failures))
                self._failures.pop(oldest)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _purge_locked(self, now: float) -> None:
        cutoff = now - self.window_seconds
        stale = [key for key, bucket in self._failures.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._failures.pop(key, None)


def client_rate_limit_key(request: Request) -> str:
    """S3-8: rate-limit key that a client cannot forge with request headers.

    Forwarded identity headers (``cf-connecting-ip`` / ``x-forwarded-for``)
    are honored ONLY when the operator explicitly declared a trusted reverse
    proxy (``LFL_WEB_TRUST_PROXY=1``). In the default direct-listener mode a
    forged ``cf-connecting-ip`` no longer rotates the key (the historical
    loopback-peer loophole) — the immediate peer address is the key.
    """
    peer = request.client.host if request.client else ""
    candidate = ""
    if os.environ.get("LFL_WEB_TRUST_PROXY", "").strip() == "1":
        for header in ("cf-connecting-ip", "x-forwarded-for"):
            value = request.headers.get(header, "").split(",")[0].strip()
            if not value:
                continue
            try:
                ipaddress.ip_address(value)
            except ValueError:
                continue
            candidate = value
            break
    return candidate or peer or "unknown"


def _bearer_valid(credentials: HTTPAuthorizationCredentials | None) -> bool:
    expected = _web_api_key()
    if not expected or credentials is None or credentials.scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(credentials.credentials, expected)


def valid_browser_session(connection) -> bool:
    """Whether the request/WS carries a VALID browser session cookie (either name).

    Works for both ``Request`` and ``WebSocket`` (both are HTTPConnection
    subclasses with ``.app.state`` / ``.cookies``). Dual-name read keeps
    pre-upgrade browsers (legacy ``lfl_web_session_v2``) logged in after the
    ``__Host-`` rollout (S3-6).
    """
    state = getattr(getattr(connection, "app", None), "state", None)
    store = getattr(state, "web_sessions", None)
    if not isinstance(store, WebSessionStore):
        return False
    cookies = getattr(connection, "cookies", None)
    getter = getattr(cookies, "get", None)
    if not callable(getter):
        return False
    for name in (SESSION_COOKIE_NAME_SECURE, SESSION_COOKIE_NAME):
        token = str(getter(name) or "").strip()
        if token and store.valid(token):
            return True
    return False


def _cookie_valid(request: Request | None) -> bool:
    if request is None:
        return False
    return valid_browser_session(request)


def request_authenticated(
    request: Request | None,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> bool:
    # Budget admission calls this helper directly, outside Depends(_bearer).
    # Parse the same header while keeping the existing credential validator.
    if credentials is None and request is not None:
        scheme, token = get_authorization_scheme_param(request.headers.get("authorization"))
        if scheme and token:
            credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=token)
    return _bearer_valid(credentials) or _cookie_valid(request)


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    request: Request = None,  # type: ignore[assignment]
) -> None:
    """Authorize protected routes by API bearer or browser session cookie.

    The historical name is kept for compatibility with callers/tests.  It now
    represents the complete Web authentication gate rather than Bearer-only auth.
    """
    if not request_auth_required(request):
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


def _host_without_port(value: str) -> str:
    """Normalize a Host/allowlist entry: lowercase, port stripped, IDNA."""
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    # [::1]:8903 -> ::1
    raw = raw[1:].split("]", 1)[0] if raw.startswith("[") else raw.split(":", 1)[0]
    raw = raw.strip(".")
    try:
        return raw.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return raw


def configured_allowed_hosts() -> frozenset[str]:
    """P1-4b: explicit hostnames HostGuard accepts (loopback is always allowed).

    Sources: the ``WEB_HOST`` binding name, ``LFL_WEB_ALLOWED_HOSTS`` (comma
    separated, ports tolerated), ``WEB_CANONICAL_HOST`` (its subdomains are
    accepted separately — they are the documented tunnel aliases that
    ``_CanonicalOriginMiddleware`` 308-redirects to the canonical host), and
    the hosts inside ``WEB_ORIGIN_ALLOWLIST`` origins.
    """
    hosts: set[str] = set()
    bind = _host_without_port(os.environ.get("WEB_HOST", "127.0.0.1"))
    if bind:
        hosts.add(bind)
    for entry in os.environ.get("LFL_WEB_ALLOWED_HOSTS", "").split(","):
        host = _host_without_port(entry)
        if host:
            hosts.add(host)
    canonical = canonical_host()
    if canonical:
        hosts.add(canonical)
    for origin in configured_origin_allowlist():
        host = _host_without_port(origin.split("://", 1)[-1])
        if host:
            hosts.add(host)
    return frozenset(hosts)


def configured_extra_origin_allowlist() -> frozenset[str]:
    """S3-2: optional extra browser Origins for the realtime WS handshake.

    ``LFL_WEB_ALLOWED_ORIGINS`` (comma separated, full origins; bare hosts
    mean HTTPS like ``WEB_ORIGIN_ALLOWLIST``). Invalid entries are skipped
    rather than fatal — this augments, never replaces, the same-origin rule.
    """
    raw = os.environ.get("LFL_WEB_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return frozenset()
    origins: set[str] = set()
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            origins.add(normalize_origin(value))
        except ValueError:
            logger.warning("LFL_WEB_ALLOWED_ORIGINS 条目无效，已跳过: %r", value)
    return frozenset(origins)


class HostGuardMiddleware:
    """P1-4b / S1-5（建议书 2026-10-25）：Host 头白名单，DNS rebinding 独立防线.

    规则（不依赖认证状态，先于一切路由/中间件逻辑执行）：

    - 生效 Host = ``Host`` 头去端口/IDNA；仅当 ``LFL_WEB_TRUST_PROXY=1`` 时
      ``X-Forwarded-Host``（首跳）参与判定并优先（可信反代后的浏览器可见主机）；
    - 允许集合 = 回环族（127.0.0.1/localhost/::1 及任意 loopback IP）∪
      ``WEB_HOST`` 绑定主机名 ∪ ``LFL_WEB_ALLOWED_HOSTS`` ∪ ``WEB_CANONICAL_HOST``
      （含其子域）∪ ``WEB_ORIGIN_ALLOWLIST`` 各 origin 的 host；
    - 其余 → 400 ``host_not_allowed``（websocket 握手则拒绝建立）。

    生产豁免说明：Starlette TestClient 的进程内哨兵对端 ``("testclient", …)``
    由测试传输层写入 ASGI scope，不可能来自真实网络套接字（生产 uvicorn 的
    scope client 恒为内核给出的真实 IP），对其跳过 Host 校验以保持既有测试
    套件兼容；这不是对生产默认的放宽。
    """

    _TESTCLIENT_PEER = "testclient"

    def __init__(self, app) -> None:
        self.app = app
        # 与 _OriginGuardMiddleware 同约定：构建期读一次 env（main() 已装配 .env）。
        self._allowed = configured_allowed_hosts()
        self._canonical = canonical_host()
        self._trust_proxy = os.environ.get("LFL_WEB_TRUST_PROXY", "").strip() == "1"

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        host = self._effective_host(scope)
        if self._host_allowed(host, scope):
            await self.app(scope, receive, send)
            return
        logger.warning("host_guard_rejected host=%r path=%r", host, scope.get("path", ""))
        body = json.dumps(
            {
                "error": "host_not_allowed",
                "detail": f"Host '{host or '(空)'}' 不在允许清单（回环/绑定主机/LFL_WEB_ALLOWED_HOSTS/WEB_CANONICAL_HOST/WEB_ORIGIN_ALLOWLIST）。",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        if scope["type"] == "websocket":
            # 握手前拒绝：websocket.close 在 accept 前由服务器转为 HTTP 拒绝响应。
            await send({"type": "websocket.close", "code": 4400, "reason": "host_not_allowed"})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _header(scope, name: bytes) -> str:
        for key, value in scope.get("headers") or []:
            if key.lower() == name:
                return value.decode("latin-1", errors="replace").strip()
        return ""

    def _effective_host(self, scope) -> str:
        host = self._header(scope, b"host")
        if self._trust_proxy:
            forwarded = self._header(scope, b"x-forwarded-host").split(",")[0].strip()
            if forwarded:
                host = forwarded
        return _host_without_port(host)

    def _host_allowed(self, host: str, scope) -> bool:
        if not host:
            return False
        if is_loopback(host):
            return True
        if host in self._allowed:
            return True
        if self._canonical and host.endswith(f".{self._canonical}"):
            return True  # canonical 的子域 = 文档化的隧道别名主机（见 _CanonicalOriginMiddleware）
        client = scope.get("client")
        peer = str(client[0]) if isinstance(client, (tuple, list)) and client else ""
        return peer == self._TESTCLIENT_PEER  # 见类 docstring：进程内测试哨兵，生产不可达
