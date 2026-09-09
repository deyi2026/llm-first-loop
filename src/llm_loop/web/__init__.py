"""Web 接入层（薄壳适配器，M36）。

复用 load_settings + build_engine（与 CLI 同源装配路径），核心零改动。
CLI / Web /（未来飞书）共用同一 LoopEngine 实例。
"""

import logging
import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine

from .auth import (
    LoginRateLimiter,
    WebSessionStore,
    auth_required,
    configured_origin_allowlist,
    is_loopback,
    normalize_origin,
    request_authenticated,
    require_api_key,
    validate_auth_require,
    validate_binding,
    validate_origin_allowlist,
)
from .auth_routes import router as auth_router
from .routes import UTF8JSONResponse, router

logger = logging.getLogger(__name__)

__all__ = ["build_app", "main"]

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _scope_header(scope, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1", errors="replace").strip()
    return ""


def _effective_request_origin(scope) -> str:
    """Build the browser-visible request Origin for exact CSRF comparison.

    Proxy scheme is trusted only from a loopback immediate peer (the supported
    local cloudflared/reverse-proxy topology). Host remains the HTTP Host header
    seen by the application, preserving public-domain and explicit-port identity.
    """
    scheme = str(scope.get("scheme") or "http").lower()
    client = scope.get("client")
    peer = str(client[0]) if isinstance(client, (tuple, list)) and client else ""
    if is_loopback(peer):
        forwarded = _scope_header(scope, b"x-forwarded-proto").split(",", 1)[0].strip().lower()
        if forwarded in {"http", "https"}:
            scheme = forwarded
    host = _scope_header(scope, b"host")
    if not host:
        return ""
    try:
        return normalize_origin(f"{scheme}://{host}", default_scheme=scheme)
    except ValueError:
        return ""


class _OriginGuardMiddleware:
    """P2-1(2026-08-15，审计发现)：回环豁免部署的跨站写防护.

    默认本机部署也不能把“所有 loopback host”当同源：scheme/host/port 任一不同都
    是不同浏览器 Origin。mutating 请求带 Origin 时，只接受当前请求的精确同源，
    或 WEB_ORIGIN_ALLOWLIST 明确列出的完整 Origin；无 Origin（curl/脚本/服务器间）
    与非 mutating 方法不受影响。

    隧道/反代场景可显式列出公网 Origin；裸域名兼容项按 HTTPS 解释。allowlist
    比较保留 scheme + host + 非默认 port，避免 host-only 白名单把同主机其它端口
    的不可信页面误当成已授权写来源。
    """

    def __init__(self, app):
        self.app = app
        # 启动期读取一次（env 在 main() 中 load_env_file 后、build_app 前已装配）
        self.origin_allowlist = configured_origin_allowlist()

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") in _MUTATING_METHODS:
            origin = ""
            for k, v in scope.get("headers") or []:
                if k == b"origin":
                    origin = v.decode("utf-8", errors="replace").strip()
                    break
            if origin:
                try:
                    browser_origin = normalize_origin(origin)
                except ValueError:
                    browser_origin = ""
                request_origin = _effective_request_origin(scope)
                if not browser_origin or (
                    browser_origin != request_origin and browser_origin not in self.origin_allowlist
                ):
                    body = (
                        '{"error":"foreign_origin_forbidden","detail":'
                        '"跨站 Origin 拒绝（写请求仅接受当前同源或显式完整 Origin 白名单）。"}'
                    ).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 403,
                            "headers": [(b"content-type", b"application/json; charset=utf-8")],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)


def build_app(settings=None, engine=None) -> FastAPI:
    """装配 FastAPI 应用（薄壳）。

    - settings=None 时复用 load_settings（env 装配，与 CLI 同源）。
    - engine 显式传入时跳过真实装配（测试注入 FakeLLM 引擎）。
    app.state.engine 持有单引擎实例（装配一次复用全部请求，不每请求重建）。
    """
    if engine is None:
        if settings is None:
            settings = load_settings()
        engine = build_engine(settings)

    app = FastAPI(
        title="llm-first-loop-web", version="0.6.6", default_response_class=UTF8JSONResponse
    )
    app.state.engine = engine
    app.state.web_sessions = WebSessionStore()
    app.state.login_rate_limiter = LoginRateLimiter()
    # Login/logout/status are deliberately public; all engine/data APIs stay behind
    # the protected router below when public exposure is enabled.
    app.include_router(auth_router)
    # P2-1: 跨站写防护（ASGI 中间件，mutating + 非回环 Origin → 403）
    app.add_middleware(_OriginGuardMiddleware)

    # T5.1: 会话级并发锁装配（spec.md 5.4.1，默认开启，SESSION_CONCURRENCY_LOCK=false 退化为无锁）
    _lock_enabled = os.environ.get("SESSION_CONCURRENCY_LOCK", "true").strip().lower() in (
        "true",
        "1",
        "",
    )
    app.state.session_locks = {} if _lock_enabled else None

    # 鉴权：公网/隧道暴露时，API 接受浏览器 session cookie 或 Bearer API key。
    # auth_required() 同时覆盖 WEB_AUTH_REQUIRE、非回环绑定和 origin allowlist，
    # 避免 cloudflared 回源 127.0.0.1 时误触回环豁免。
    if auth_required():
        app.include_router(router, dependencies=[Depends(require_api_key)])
    else:
        app.include_router(router)

    # v1（原版 M37 前端 /static）已弃用：保留 static/ 历史产物，但不再挂载路由。

    # Web V2（React+TS，2026-08-15，对齐 DeepSeek Harness Web 端）：
    # 独立目录 webui/（独立分支 feature/web-v2），构建产物挂载 /ui/v2 与原版 / 并存。
    # 原版代码/资源保留不删不改；UI_V2_DIR 可覆盖（测试注入）；产物缺失时不挂载（零影响）。
    _ui_v2_dir = Path(
        os.environ.get("UI_V2_DIR", "") or Path(__file__).resolve().parents[3] / "webui" / "dist"
    )
    if Path(_ui_v2_dir).is_dir():

        @app.middleware("http")
        async def _ui_v2_auth_gate(request: Request, call_next):
            # Mounted StaticFiles does not inherit APIRouter dependencies. Protect it
            # explicitly so unauthenticated users cannot load the application shell/assets.
            if (
                auth_required()
                and request.url.path.startswith("/ui/v2")
                and not request_authenticated(request)
            ):
                from urllib.parse import quote

                target = request.url.path
                if request.url.query:
                    target += "?" + request.url.query
                return RedirectResponse(
                    url="/login?next=" + quote(target, safe="/"),
                    status_code=303,
                )
            return await call_next(request)

        app.mount("/ui/v2", StaticFiles(directory=str(_ui_v2_dir), html=True), name="ui-v2")

        # Web V2 缓存策略：index.html 不缓存（迭代频繁，浏览器必须每次拉新；
        # 此前仅 ETag 时部分浏览器刷新不重新验证导致"刷新没变化"）。JS/CSS 带
        # 内容 hash，命中缓存安全；仅作用于 /ui/v2/ 静态路径，不影响 API。
        @app.middleware("http")
        async def _ui_v2_no_cache(request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/ui/v2/"):
                response.headers["Cache-Control"] = "no-store"
            return response

    return app


def _install_exit_signal_log() -> None:
    """P1-3-R1: web 退出信号记录（对齐 feishu `_log_exit` 范式，仅记录不改变退出行为）.

    SIGTERM/SIGINT/SIGHUP 到达时追加写 `data/web_exit.log`（时刻/pid/信号名）。
    fail-open：写失败静默、信号注册异常不阻塞启动。
    """
    import contextlib
    import datetime
    import signal

    exit_log_path = os.path.join(os.environ.get("DATA_DIR", "data"), "web_exit.log")

    def _log_web_exit(reason: str) -> None:
        try:
            with open(exit_log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat()} pid={os.getpid()} {reason}\n")
        except OSError as exc:  # fail-open：退出日志写失败不影响启动
            logger.debug("退出日志写失败（fail-open）: %s", exc)

    def _on_signal(signum, frame):  # noqa: ARG001 — signal handler 签名固定
        try:
            name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            name = str(signum)
        _log_web_exit(f"收到信号 {signum} ({name})")

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    with contextlib.suppress(AttributeError, ValueError, OSError):
        signal.signal(signal.SIGHUP, _on_signal)  # 终端关闭保护


def main() -> None:
    """服务启动入口（python -m llm_loop.web）."""
    # R1（RUNTIME-SOT-WIRE）: workspace 身份守卫——错配时 shadow 仅告警/enforce 拒绝启动。
    # 锚定 CWD（与下方 .env 同约定）；模块 repo 与 CWD 不一致 = 共享 venv/PYTHONPATH 串区。
    from llm_loop.runtime.identity import enforce_identity

    enforce_identity(Path.cwd())
    # 补齐手动启动缺口：shell 未注入 .env 时也能可靠读配置（MCP_SERVERS 等）。
    # 锚定 CWD（与 data_dir="./data" 同约定，重启脚本均 cd 到各自项目根）；
    # 不可用默认 __file__ 锚定——共享代码（venv .pth 指向镜像 src）会让主区进程
    # 误读镜像 .env 的 WEB_PORT=8903/LFL_DATA_DIR，主区 web 绑镜像端口直接起不来。
    load_env_file(Path.cwd() / ".env")
    # P1 route attribution: 服务入口本身是 route 的权威事实；显式 LFL_ROUTE 仍优先。
    os.environ.setdefault("LFL_ROUTE", "web")
    # EVO-20260811-f94e5306: 记录进程启动版本（一致性检测）
    from llm_loop.introspection.proc_version import record_process_start

    record_process_start("web")
    # R3（RUNTIME-SOT-WIRE）: 进程身份+配置指纹落盘（fail-open 不阻断启动）；
    # /health 读回暴露——跨区污染秒级诊断。
    from llm_loop.runtime.manifest import write_runtime_manifest

    write_runtime_manifest("web")
    host = os.environ.get("WEB_HOST", "127.0.0.1").strip()
    port = int(os.environ.get("WEB_PORT", "8902").strip())

    try:
        validate_binding(host)
        validate_auth_require()  # P2-1: WEB_AUTH_REQUIRE=1 无 key → 拒绝启动（fail-closed）
        validate_origin_allowlist()  # P3: allowlist 非空（公网暴露意图）无 key → 拒绝启动（fail-closed）
    except (RuntimeError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    engine = build_engine(settings)
    app = build_app(settings=settings, engine=engine)

    import uvicorn

    _install_exit_signal_log()  # P1-3-R1: 退出信号记录（web_exit.log，不改变退出行为）
    # P1: 优雅退出超时（SIGTERM 后最多 10s 内自然退出，< restart_system.sh 的 GRACE_S=15，
    # 避免同步 LLM 长请求阻塞导致 SIGKILL 强杀）
    try:
        uvicorn.run(app, host=host, port=port, timeout_graceful_shutdown=10)
    finally:
        # P2-4(2026-08-15): 服务退出关闭 LLM 连接（httpx Client 连接池不泄漏）
        engine.close()


if __name__ == "__main__":
    main()
