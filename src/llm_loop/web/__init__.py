"""Web 接入层（薄壳适配器，M36）。

复用 load_settings + build_engine（与 CLI 同源装配路径），核心零改动。
CLI / Web /（未来飞书）共用同一 LoopEngine 实例。
"""

import logging
import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from llm_loop.config import load_settings
from llm_loop.factory import build_engine

from .auth import is_loopback, require_api_key, validate_auth_require, validate_binding
from .routes import UTF8JSONResponse, router

logger = logging.getLogger(__name__)

__all__ = ["build_app", "main"]

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


class _OriginGuardMiddleware:
    """P2-1(2026-08-15，审计发现)：回环豁免部署的跨站写防护.

    默认本机部署（127.0.0.1 + 无 key）下浏览器任意网页可跨站 POST 本服务
    （表单/fetch 打 127.0.0.1）。浏览器跨站请求必带 Origin 头——mutating 方法
    携非回环 Origin → 403 如实拒绝；无 Origin（curl/脚本/服务器间）与非
    mutating 方法不受影响（零回归）。令牌鉴权开启时本层冗余但无害。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") in _MUTATING_METHODS:
            origin = ""
            for k, v in scope.get("headers") or []:
                if k == b"origin":
                    origin = v.decode("utf-8", errors="replace").strip()
                    break
            if origin:
                from urllib.parse import urlparse

                host = (urlparse(origin).hostname or "").lower()
                if not is_loopback(host):
                    body = (
                        '{"error":"foreign_origin_forbidden","detail":'
                        '"跨站 Origin 拒绝（本机服务仅接受回环来源的写请求）。"}'
                    ).encode()
                    await send({
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"application/json; charset=utf-8")],
                    })
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
        title="llm-first-loop-web", version="0.6.3", default_response_class=UTF8JSONResponse
    )
    app.state.engine = engine
    # P2-1: 跨站写防护（ASGI 中间件，mutating + 非回环 Origin → 403）
    app.add_middleware(_OriginGuardMiddleware)

    # T5.1: 会话级并发锁装配（spec.md 5.4.1，默认开启，SESSION_CONCURRENCY_LOCK=false 退化为无锁）
    _lock_enabled = os.environ.get("SESSION_CONCURRENCY_LOCK", "true").strip().lower() in ("true", "1", "")
    app.state.session_locks = {} if _lock_enabled else None

    # 鉴权：条件挂载到受保护路由（远程监听时要求 Bearer 令牌）
    if os.environ.get("WEB_AUTH_REQUIRE", "").strip() == "1":
        app.include_router(router, dependencies=[Depends(require_api_key)])
    else:
        host = os.environ.get("WEB_HOST", "127.0.0.1")
        if not _is_loopback(host):
            app.include_router(router, dependencies=[Depends(require_api_key)])
        else:
            app.include_router(router)

    # 静态前端资源挂载（M37：聊天页面 /static/*）
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # Web V2（React+TS，2026-08-15，对齐 DeepSeek Harness Web 端）：
    # 独立目录 webui/（独立分支 feature/web-v2），构建产物挂载 /ui/v2 与原版 / 并存。
    # 原版代码/资源保留不删不改；UI_V2_DIR 可覆盖（测试注入）；产物缺失时不挂载（零影响）。
    _ui_v2_dir = Path(os.environ.get("UI_V2_DIR", "") or Path(__file__).resolve().parents[3] / "webui" / "dist")
    if Path(_ui_v2_dir).is_dir():
        app.mount("/ui/v2", StaticFiles(directory=str(_ui_v2_dir), html=True), name="ui-v2")

    return app


def _is_loopback(host: str) -> bool:
    from .auth import is_loopback as _il

    return _il(host)


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
    # EVO-20260811-f94e5306: 记录进程启动版本（一致性检测）
    from llm_loop.introspection.proc_version import record_process_start

    record_process_start("web")
    host = os.environ.get("WEB_HOST", "127.0.0.1").strip()
    port = int(os.environ.get("WEB_PORT", "8902").strip())

    try:
        validate_binding(host)
        validate_auth_require()  # P2-1: WEB_AUTH_REQUIRE=1 无 key → 拒绝启动（fail-closed）
    except RuntimeError as exc:
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
