"""Browser login/logout endpoints for the Web UI."""

from __future__ import annotations

import html
import json
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .auth import (
    SESSION_COOKIE_NAME,
    LoginRateLimiter,
    WebSessionStore,
    auth_required,
    browser_login_configured,
    client_rate_limit_key,
    is_loopback,
    normalize_origin,
    request_authenticated,
    session_ttl_seconds,
    verify_login_password,
)

router = APIRouter()

_MAX_LOGIN_BODY_BYTES = 16 * 1024


def _safe_next(value: str | None) -> str:
    """Allow only same-origin absolute paths as post-login redirects."""
    candidate = (value or "/ui/v2/").strip()
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate)
    ):
        return "/ui/v2/"
    try:
        parsed = urlsplit(candidate)
        decoded_path = unquote(parsed.path)
    except (ValueError, UnicodeError):
        return "/ui/v2/"
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return "/ui/v2/"
    if (
        decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded_path)
    ):
        return "/ui/v2/"
    return candidate


def _login_html(*, next_path: str, error: str = "", unavailable: bool = False) -> str:
    safe_next = html.escape(_safe_next(next_path), quote=True)
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    disabled = " disabled" if unavailable else ""
    hint = (
        "浏览器登录尚未配置。请先在本机配置 WEB_LOGIN_PASSWORD_HASH。"
        if unavailable
        else "登录成功后会建立仅 HttpOnly Cookie 可见的短期会话。"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LLM First Loop · 登录</title>
<style>
:root{{font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color-scheme:light dark}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#11151b;color:#eef2f7}}
main{{width:min(420px,calc(100vw - 40px));padding:32px;border:1px solid #2b3440;border-radius:18px;background:#171d25;box-shadow:0 18px 60px #0006}}
h1{{margin:0 0 8px;font-size:24px}}p{{margin:0 0 22px;color:#aeb8c5;line-height:1.55}}
label{{display:block;margin-bottom:8px;font-size:14px}}input{{box-sizing:border-box;width:100%;padding:13px 14px;border:1px solid #3a4553;border-radius:10px;background:#0f141a;color:#fff;font-size:16px}}
button{{width:100%;margin-top:14px;padding:13px;border:0;border-radius:10px;background:#eef2f7;color:#11151b;font-weight:700;font-size:15px;cursor:pointer}}
button:disabled{{opacity:.45;cursor:not-allowed}}.error{{margin-bottom:14px;padding:10px 12px;border:1px solid #6a2f35;border-radius:9px;background:#2b171a;color:#ffb8bd}}
small{{display:block;margin-top:18px;color:#768396;line-height:1.5}}
.plain-password{{-webkit-text-security:disc}}
</style>
</head>
<body><main>
<h1>LLM First Loop</h1>
<p>{html.escape(hint)}</p>
{error_html}
<form method="post" action="/auth/login" autocomplete="off">
<input type="hidden" name="next" value="{safe_next}">
<label for="password">登录密码</label>
<input class="plain-password" id="password" name="password" type="text" inputmode="text" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" enterkeyhint="go" required{disabled}>
<small class="paste-hint">手机端使用普通键盘，可直接长按粘贴或调用系统剪贴板；WebKit 会用圆点遮挡输入内容。服务器仍按原文校验，不 trim、不改写。</small>
<button type="submit"{disabled}>登录</button>
</form>
<small>会话 Cookie 为 HttpOnly + SameSite=Strict；公网 HTTPS 下强制 Secure。脚本访问仍可使用独立 Bearer API key。</small>
</main></body></html>"""


def _login_response(*, next_path: str, error: str = "", status_code: int = 200) -> HTMLResponse:
    response = HTMLResponse(
        _login_html(
            next_path=next_path,
            error=error,
            unavailable=not browser_login_configured(),
        ),
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    # no-referrer makes browsers send Origin: null for this same-origin POST.
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _secure_cookie(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else ""
    if is_loopback(peer):
        forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
        if forwarded == "https":
            return True
    origin = request.headers.get("origin", "").strip()
    if origin:
        try:
            return normalize_origin(origin).startswith("https://")
        except ValueError:
            return False
    return False


async def _bounded_login_body(request: Request) -> bytes:
    raw_length = request.headers.get("content-length", "").strip()
    if raw_length:
        try:
            declared = int(raw_length)
        except ValueError:
            declared = -1
        if declared > _MAX_LOGIN_BODY_BYTES:
            raise HTTPException(status_code=413, detail="login payload too large")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_LOGIN_BODY_BYTES:
            raise HTTPException(status_code=413, detail="login payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _login_payload(request: Request) -> tuple[str, str, bool]:
    content_type = request.headers.get("content-type", "").lower()
    raw_body = await _bounded_login_body(request)
    if "application/json" in content_type:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return "", "/ui/v2/", True
        if not isinstance(payload, dict):
            return "", "/ui/v2/", True
        return str(payload.get("password", "")), _safe_next(str(payload.get("next", ""))), True
    body = raw_body.decode("utf-8", errors="replace")
    form = parse_qs(body, keep_blank_values=True)
    password = form.get("password", [""])[0]
    next_path = _safe_next(form.get("next", ["/ui/v2/"])[0])
    return password, next_path, False


@router.get("/", response_model=None)
def browser_entry(request: Request):
    if not auth_required():
        from .routes import root as service_root

        return service_root()
    if request_authenticated(request):
        return RedirectResponse("/ui/v2/", status_code=303)
    return RedirectResponse("/login?next=/ui/v2/", status_code=303)


@router.get("/auth/login", response_model=None, include_in_schema=False)
@router.get("/login", response_model=None)
def login_page(request: Request, next: str = "/ui/v2/"):
    next_path = _safe_next(next)
    if request_authenticated(request):
        return RedirectResponse(next_path, status_code=303)
    return _login_response(next_path=next_path)


@router.post("/auth/login", response_model=None)
async def login(request: Request):
    password, next_path, wants_json = await _login_payload(request)
    if not browser_login_configured():
        if wants_json:
            return JSONResponse({"error": "browser_login_not_configured"}, status_code=503)
        return _login_response(
            next_path=next_path,
            error="浏览器登录尚未配置。",
            status_code=503,
        )

    limiter = getattr(request.app.state, "login_rate_limiter", None)
    if not isinstance(limiter, LoginRateLimiter):
        limiter = LoginRateLimiter()
        request.app.state.login_rate_limiter = limiter
    key = client_rate_limit_key(request)
    decision = limiter.check(key)
    if not decision.allowed:
        headers = {"Retry-After": str(decision.retry_after)}
        if wants_json:
            return JSONResponse({"error": "too_many_login_attempts"}, status_code=429, headers=headers)
        response = _login_response(
            next_path=next_path,
            error="尝试次数过多，请稍后再试。",
            status_code=429,
        )
        response.headers.update(headers)
        return response

    if not verify_login_password(password):
        limiter.record_failure(key)
        if wants_json:
            return JSONResponse({"error": "invalid_credentials"}, status_code=401)
        return _login_response(next_path=next_path, error="密码错误。", status_code=401)

    limiter.record_success(key)
    store = getattr(request.app.state, "web_sessions", None)
    if not isinstance(store, WebSessionStore):
        store = WebSessionStore()
        request.app.state.web_sessions = store
    ttl = session_ttl_seconds()
    token = store.create(ttl_seconds=ttl)

    if wants_json:
        response = JSONResponse({"status": "ok", "next": next_path})
    else:
        response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/auth/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    store = getattr(request.app.state, "web_sessions", None)
    if isinstance(store, WebSessionStore):
        store.revoke(token)
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/status")
def auth_status(request: Request):
    """Minimal public readiness/auth status; intentionally excludes engine/config details."""
    return JSONResponse(
        {
            "status": "ok",
            "authenticated": request_authenticated(request),
            "browser_login": browser_login_configured(),
        },
        headers={"Cache-Control": "no-store"},
    )
