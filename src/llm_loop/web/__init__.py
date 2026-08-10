"""Web 接入层（薄壳适配器，M36）。

复用 load_settings + build_engine（与 CLI 同源装配路径），核心零改动。
CLI / Web /（未来飞书）共用同一 LoopEngine 实例。
"""

import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from llm_loop.config import load_settings
from llm_loop.factory import build_engine

from .auth import require_api_key, validate_binding
from .routes import UTF8JSONResponse, router

__all__ = ["build_app", "main"]

_STATIC_DIR = Path(__file__).resolve().parent / "static"


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
        title="llm-first-loop-web", version="0.1.0", default_response_class=UTF8JSONResponse
    )
    app.state.engine = engine

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

    return app


def _is_loopback(host: str) -> bool:
    from .auth import is_loopback as _il

    return _il(host)


def main() -> None:
    """服务启动入口（python -m llm_loop.web）."""
    host = os.environ.get("WEB_HOST", "127.0.0.1").strip()
    port = int(os.environ.get("WEB_PORT", "8901").strip())

    try:
        validate_binding(host)
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

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
