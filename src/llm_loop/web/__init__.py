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
from llm_loop.timekeeping import system_local_now

from .auth import (
    SESSION_COOKIE_NAME,
    LoginRateLimiter,
    WebSessionStore,
    canonical_host,
    configured_origin_allowlist,
    is_loopback,
    normalize_origin,
    request_auth_required,
    request_authenticated,
    require_api_key,
    validate_auth_require,
    validate_binding,
    validate_origin_allowlist,
)
from .auth_routes import router as auth_router
from .routes import UTF8JSONResponse, router
from .task_budget_canary import load_operator_web_canary

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
                    await send({
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"application/json; charset=utf-8")],
                    })
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)


class _CanonicalOriginMiddleware:
    """P0(2026-09-30): 公网 http→https 与别名主机名→canonical 308 归一.

    事故背景: 同一浏览器在 https://llmfirstloop.com 登录成功(Secure cookie),
    但历史记录/自动补全里还存在 http:// 或 https://app.llmfirstloop.com 入口。
    http 请求不携带 Secure cookie、别名主机名的 cookie 边界不同,于是同一用户
    "登录成功又被弹回登录页"交替出现(web.log favicon.svg 200/303 交替)。

    规则(全部满足才 308):
    - ASGI http 且「immediate peer 是 loopback」**或**「本进程 WEB_HOST 绑定本身是
      loopback」(绑定边界: 服务只可能被本机进程直连,头伪造面与原方案等价;
      真实缺陷修复 2026-09-30 P0: uvicorn ProxyHeadersMiddleware 先于本中间件把
      scope["client"] 改写成 X-Forwarded-For 的公网 IP,原 is_loopback(peer) 对
      公网流量恒 False,308 从未在公网触发,仅本地模拟直连测试暴露过假阳性);
    - 带可信 x-forwarded-proto 头(本地直连无此头,完全不受影响);
    - proto=http → 升级 https;或 host(去端口)≠ WEB_CANONICAL_HOST 且是
      canonical 或其子域 → 归一到 canonical。
    308 永久重定向且保留方法/请求体,POST /auth/login 等表单无缝升级。
    """

    def __init__(self, app):
        self.app = app
        self._canonical = canonical_host()
        self._listener_loopback = is_loopback(os.environ.get("WEB_HOST", "127.0.0.1"))

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not self._canonical:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        peer = str(client[0]) if isinstance(client, (tuple, list)) and client else ""
        if not (self._listener_loopback or is_loopback(peer)):
            await self.app(scope, receive, send)
            return
        forwarded = _scope_header(scope, b"x-forwarded-proto").split(",", 1)[0].strip().lower()
        if not forwarded:
            await self.app(scope, receive, send)
            return
        host = _scope_header(scope, b"host")
        try:
            host_name, _, port = host.partition(":")
            host_name = host_name.strip().strip("[]").lower()
            host_name = host_name.encode("idna").decode("ascii")
        except (UnicodeError, AttributeError):
            host_name = ""
        scheme_upgrade = forwarded == "http"
        host_is_alias = (
            bool(host_name)
            and host_name != self._canonical
            and (host_name.endswith(f".{self._canonical}"))
        )
        if not scheme_upgrade and not host_is_alias:
            await self.app(scope, receive, send)
            return
        target_scheme = "https"
        target_host = self._canonical if host_is_alias or host_name == self._canonical else host_name
        if not target_host:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "/") or "/"
        query = scope.get("query_string", b"").decode("latin-1", errors="replace")
        location = f"{target_scheme}://{target_host}{path}"
        if query:
            location += f"?{query}"
        # 端口仅当 Host 显式带非默认端口时保留(本地测试拓扑);公网 443 隐含。
        if port and port not in {"80", "443"}:
            location = f"{target_scheme}://{target_host}:{port}{path}"
            if query:
                location += f"?{query}"
        await send({
            "type": "http.response.start",
            "status": 308,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"location", location.encode("latin-1", errors="replace")),
                (b"cache-control", b"public, max-age=86400"),
            ],
        })
        await send({"type": "http.response.body", "body": b"permanent redirect"})


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
    # Default OFF. A single preconfigured Web session can use the admin-once
    # CAS plan or the existing separately signed operator plan.
    app.state.task_budget_web_canary = load_operator_web_canary(engine)
    # Central Run admission fence: no queue/sync/direct-Engine bypass of a
    # startup-authorized single-use session after its quota has been spent.
    from llm_loop.resources.task_budget_admin_once import AdminOnceEventPlan

    _canary = app.state.task_budget_web_canary
    engine._task_budget_restricted_session_id = (
        _canary.session_id
        if _canary is not None and isinstance(_canary.plan, AdminOnceEventPlan)
        else None
    )
    app.state.web_sessions = WebSessionStore()
    app.state.login_rate_limiter = LoginRateLimiter()
    # Login/logout/status are deliberately public; all engine/data APIs stay behind
    # the protected router below when public exposure is enabled.
    app.include_router(auth_router)
    # P2-1: 跨站写防护（ASGI 中间件，mutating + 非回环 Origin → 403）
    app.add_middleware(_OriginGuardMiddleware)

    # T5.1: 会话级并发锁装配（spec.md 5.4.1，默认开启，SESSION_CONCURRENCY_LOCK=false 退化为无锁）
    _lock_enabled = os.environ.get("SESSION_CONCURRENCY_LOCK", "true").strip().lower() in ("true", "1", "")
    app.state.session_locks = {} if _lock_enabled else None

    # 鉴权是请求级策略：同一进程允许 direct-loopback 无登录访问，同时要求
    # 公网域名/隧道请求使用浏览器 session 或 Bearer。
    app.include_router(router, dependencies=[Depends(require_api_key)])

    # v1（原版 M37 前端 /static）已弃用：保留 static/ 历史产物，但不再挂载路由。

    # Web V2（React+TS，2026-08-15，对齐 DeepSeek Harness Web 端）：
    # 独立目录 webui/（独立分支 feature/web-v2），构建产物挂载 /ui/v2 与原版 / 并存。
    # 原版代码/资源保留不删不改；UI_V2_DIR 可覆盖（测试注入）；产物缺失时不挂载（零影响）。
    _ui_v2_dir = Path(os.environ.get("UI_V2_DIR", "") or Path(__file__).resolve().parents[3] / "webui" / "dist")
    if Path(_ui_v2_dir).is_dir():
        @app.middleware("http")
        async def _ui_v2_auth_gate(request: Request, call_next):
            # Mounted StaticFiles does not inherit APIRouter dependencies. Protect it
            # explicitly so unauthenticated users cannot load the application shell/assets.
            if (
                request_auth_required(request)
                and request.url.path.startswith("/ui/v2")
                and not request_authenticated(request)
            ):
                # P1(2026-09-30): 弹回登录页时记录 host/scheme/cookie 存在性——
                # 2026-09-30 事故里 access log 无 Host,双域名/http 混用定位耗时
                # 数小时。只记布尔与头名,不落任何 token 值。
                logger.info(
                    "auth_gate_redirect host=%s xfp=%s cookie_present=%s path=%s",
                    request.headers.get("host", "-"),
                    request.headers.get("x-forwarded-proto", "-"),
                    SESSION_COOKIE_NAME in request.cookies,
                    request.url.path,
                )
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

    # P0(2026-09-30): http→https + 别名主机名→canonical 308 归一。必须在所有
    # @app.middleware("http") 装饰器（auth gate / no-cache）之后注册——Starlette
    # 后注册者在更外层——否则 auth gate 会先以未认证 303 抢答，归一永远不执行
    # （首版实现即栽在此：/ui/v2/ 的 http 请求被 auth gate 303 到相对路径 /login，
    # 仍停留在 http）。
    app.add_middleware(_CanonicalOriginMiddleware)

    return app


def _install_exit_signal_log() -> None:
    """P1-3-R1: web 退出信号记录（对齐 feishu `_log_exit` 范式，仅记录不改变退出行为）.

    SIGTERM/SIGINT/SIGHUP 到达时追加写 `data/web_exit.log`（时刻/pid/信号名）。
    fail-open：写失败静默、信号注册异常不阻塞启动。
    """
    import contextlib
    import signal

    exit_log_path = os.path.join(os.environ.get("DATA_DIR", "data"), "web_exit.log")

    def _log_web_exit(reason: str) -> None:
        try:
            with open(exit_log_path, "a", encoding="utf-8") as f:
                f.write(f"{system_local_now().isoformat()} pid={os.getpid()} {reason}\n")
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


def _register_stack_dump_signal() -> None:
    """SIGUSR1 → faulthandler 全线程栈转储到 stderr（进 web.log）.

    2026-09-23 CPU 失控诊断：活动 run 期间 web 持续 ~100% CPU 但外部采样
    （sample/top）无法归属——SIGUSR1 按需转储 Python 栈，零常驻开销。
    操作员：kill -USR1 <web_pid>。
    """
    import signal

    try:
        import faulthandler

        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
        logger.info("stack dump signal registered: SIGUSR1 -> stderr")
    except (ImportError, OSError, ValueError):  # pragma: no cover - 非 POSIX/受限环境
        logger.warning("faulthandler SIGUSR1 注册失败（诊断不可用，不影响服务）")


def main() -> None:
    """服务启动入口（python -m llm_loop.web）."""
    # R1（RUNTIME-SOT-WIRE）: workspace 身份守卫——错配时 shadow 仅告警/enforce 拒绝启动。
    # 锚定 CWD（与下方 .env 同约定）；模块 repo 与 CWD 不一致 = 共享 venv/PYTHONPATH 串区。
    from llm_loop.runtime.identity import enforce_identity

    enforce_identity(Path.cwd())
    # 补齐手动启动缺口：shell 未注入 .env 时也能可靠读配置（MCP_SERVERS 等）。
    # 锚定 CWD（与 data_dir="./data" 同约定，重启脚本均 cd 到各自项目根）；
    # 不可用默认 __file__ 锚定（历史事故防御，机制保留）——双区时代共享代码曾让旧主区进程
    # 误读本区 .env 的 WEB_PORT/LFL_DATA_DIR；现本区即唯一区（2026-09-29 主区退役），cwd 锚定
    # 仍是正确语义（服务一律从本仓库根启动）。
    _env_file = (Path.cwd() / ".env").resolve()
    os.environ.setdefault("LFL_ENV_FILE", str(_env_file))
    load_env_file(_env_file)
    # P0(2026-09-30): llm_loop.* INFO 日志可见化——auth_gate_redirect 等诊断日志
    # 依赖 root logger,而 root 默认 WARNING 把 INFO 全吞(web.log 只有 uvicorn access
    # 行,事故定位缺 Host/scheme 线索数小时)。仅配 llm_loop 命名空间,第三方库不受影响。
    _diag_logger = logging.getLogger("llm_loop")
    _diag_logger.setLevel(logging.INFO)
    if not _diag_logger.handlers:
        _handler = logging.StreamHandler(sys.stderr)
        _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        _diag_logger.addHandler(_handler)
    # P1 route attribution: 服务入口本身是 route 的权威事实；显式 LFL_ROUTE 仍优先。
    os.environ.setdefault("LFL_ROUTE", "web")
    # EVO-20260811-f94e5306: 记录进程启动版本（一致性检测）
    from llm_loop.introspection.proc_version import record_process_start

    record_process_start("web")
    _register_stack_dump_signal()
    # R3（RUNTIME-SOT-WIRE）: 进程身份+配置指纹落盘（fail-open 不阻断启动）；
    # /health 读回暴露——跨区污染秒级诊断。
    from llm_loop.runtime.manifest import write_runtime_manifest

    write_runtime_manifest("web")
    host = os.environ.get("WEB_HOST", "127.0.0.1").strip()
    # 2026-09-24 修正: 默认端口 8903（.env WEB_PORT=8903 固化，唯一区既定端口）——
    # 旧默认 8902 属已退役主区残留，环境未带 WEB_PORT 直启时会错绑。
    port = int(os.environ.get("WEB_PORT", "8903").strip())

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
    # SPEC-20260923-queue-recovery：生产入口启动排队恢复巡检——"恢复后自动
    # 继续"的承诺不再依赖浏览器派发循环存活。队列单例预置进 app.state
    # （与请求侧 _human_turn_queue 同 key 构造，复用同一实例）；测试注入
    # 引擎的 build_app 路径不经过这里。
    from llm_loop.web.human_turn_queue import HumanTurnQueue
    from llm_loop.web.queue_recovery import QueueServerFallback
    from llm_loop.web.routes import _queue_claim_state

    _data_dir = str(Path(str(getattr(settings, "data_dir", "./data"))).expanduser().resolve())
    _hq = HumanTurnQueue(
        _data_dir,
        claim_state_probe=lambda sid, qid: _queue_claim_state(engine, sid, qid),
    )
    app.state.human_turn_queues = {_data_dir: _hq}
    # R2（antidrift_impl 批1）: 收敛回执队列压力 probe 注入（fail-open：读失败→None
    # →回执段如实 unavailable(queue_read_failed)）；CLI/feishu 装配不经此处=不注入。
    def _interjection_pressure_probe(session_id: str):
        try:
            return _hq.interject_pressure(session_id)
        except Exception:
            return None

    engine.interjection_pressure_probe = _interjection_pressure_probe

    _fallback = QueueServerFallback(engine, _hq)
    _fallback.start()
    app.state.queue_server_fallback = _fallback

    _binding_notifier = None
    if bool(getattr(settings, "chatgpt_web_enabled", False)):
        from llm_loop.llm.chatgpt_surface import ChatGPTSessionBindingStore
        from llm_loop.llm.chatgpt_web import CHATGPT_WEB_SEGMENT_BUDGET_RATIO
        from llm_loop.runtime.chatgpt_binding_health import (
            inspect_chatgpt_binding_health,
        )
        from llm_loop.runtime.chatgpt_binding_notifications import (
            ChatGPTBindingAlertNotifier,
        )

        _binding_store = ChatGPTSessionBindingStore(
            Path(_data_dir) / "chatgpt-web-provider" / "sessions"
        )
        _segment_max_chars = max(
            1,
            int(
                int(getattr(settings, "chatgpt_web_max_request_chars", 150_000))
                * CHATGPT_WEB_SEGMENT_BUDGET_RATIO
            ),
        )

        def _binding_health_probe():
            return inspect_chatgpt_binding_health(
                _binding_store,
                engine.session,
                segment_max_chars=_segment_max_chars,
                min_gc_age_days=30,
            )

        _binding_notifier = ChatGPTBindingAlertNotifier(
            _data_dir,
            _binding_health_probe,
        )
        _binding_notifier.start()
    app.state.chatgpt_binding_alert_notifier = _binding_notifier

    import uvicorn

    _install_exit_signal_log()  # P1-3-R1: 退出信号记录（web_exit.log，不改变退出行为）
    # P1: 优雅退出超时（SIGTERM 后最多 10s 内自然退出，< restart_system.sh 的 GRACE_S=15，
    # 避免同步 LLM 长请求阻塞导致 SIGKILL 强杀）
    try:
        uvicorn.run(app, host=host, port=port, timeout_graceful_shutdown=10)
    finally:
        if _binding_notifier is not None:
            _binding_notifier.stop()
        # P2-4(2026-08-15): 服务退出关闭 LLM 连接（httpx Client 连接池不泄漏）
        engine.close()


if __name__ == "__main__":
    main()
