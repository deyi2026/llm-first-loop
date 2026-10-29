"""企微智能机器人桥装配与启动（M0，平移 feishu/__init__.py 范式）.

复用 load_settings + build_engine（与 CLI/Web/飞书同源装配），核心零改动。
build_bridge(engine=None) 支持测试注入；以 -m 方式执行 llm_loop.wecom 即启动
（runtime.launch 经 runpy 以 __main__ 执行本入口）。
"""

import contextlib
import logging
import sys
from pathlib import Path

from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine

from .config import WeComConfig, load_wecom_config
from .session_map import WeComSessionMap

__all__ = ["build_bridge", "start_bridge", "main"]

logger = logging.getLogger(__name__)


def build_bridge(
    engine=None,
    config: WeComConfig | None = None,
    client_factory=None,
    lock_path: str | None = None,
):
    """装配企微桥（薄壳）：config + engine + session_map + bridge + handler.

    装配顺序：bridge 先建 → handler reply_fn=bridge.send_text（绑定 req_id）
    → bridge.attach_handler（handlers 零改动）。SDK 客户端工厂可注入（测试零真实 WS）。
    """
    if config is None:
        config = load_wecom_config()
    if engine is None:
        settings = load_settings()
        engine = build_engine(settings)
    # SDK-heavy bridge/handler 仅在实际装配时导入（纯控制模块无 SDK 依赖可导入）
    from .bridge import WeComBridge
    from .handlers import WeComMessageHandler

    session_map = WeComSessionMap(
        engine.session,
        path=config.session_map_path,
        owner_userid=config.owner_userid,
    )
    bridge = WeComBridge(
        config,
        handler=None,
        client_factory=client_factory,
        lock_path=lock_path,
    )
    handler = WeComMessageHandler(
        engine,
        session_map,
        bridge.send_text,  # WeComReplyFn：(req_id, receive_id, text, receive_id_type)
        chunk_limit=config.chunk_limit,
    )
    bridge.attach_handler(handler)
    return bridge, handler, session_map


def start_bridge(bridge) -> bool:
    """启动桥（启用条件 + 单实例锁 + 连接）."""
    return bridge.start()


def main() -> None:
    """企微桥启动入口（-m 执行 llm_loop.wecom / runtime.launch wecom）."""
    from llm_loop.runtime.identity import enforce_identity

    enforce_identity(Path.cwd())
    # 补齐手动启动缺口：shell 未注入 .env 时也能可靠读配置（锚定 CWD，与飞书一致）
    load_env_file(Path.cwd() / ".env")
    try:
        config = load_wecom_config()
    except ValueError as exc:
        # 缺 WECHAT_BOT_ID / WECHAT_BOT_SECRET：清晰报错退出（不连空凭据、不挂起）
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    try:
        bridge, handler, session_map = build_bridge(config=config)  # noqa: F841 — 装配引用
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not start_bridge(bridge):
        print(
            "企微桥启动失败（凭据未配置 / 单实例锁被占用 / 连接失败，详见日志）。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print("企微桥已启动（Ctrl+C 停止）。")
    # 优雅停机：SIGTERM/SIGINT/SIGHUP → stop_event → bridge.stop() → 关引擎
    import os
    import signal
    import threading

    from llm_loop.timekeeping import system_local_now

    _exit_log_path = os.path.join(os.environ.get("DATA_DIR", "data"), "wecom_exit.log")

    def _log_exit(reason: str) -> None:
        try:
            with open(_exit_log_path, "a", encoding="utf-8") as f:
                f.write(f"{system_local_now().isoformat()} pid={os.getpid()} {reason}\n")
        except OSError as exc:
            logger.debug("退出日志写失败（fail-open）: %s", exc)

    _log_exit("启动")
    stop_event = threading.Event()
    received_signal = [None]

    def _request_stop(signum, frame):  # noqa: ARG001 — signal handler 签名固定
        received_signal[0] = signum
        try:
            name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            name = str(signum)
        _log_exit(f"收到信号 {signum} ({name})")
        stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    with contextlib.suppress(AttributeError, ValueError, OSError):
        signal.signal(signal.SIGHUP, _request_stop)  # 终端关闭保护
    try:
        while not stop_event.wait(1):
            pass
    except BaseException as exc:  # noqa: BLE001 — 任何主循环异常都如实记录再退出
        _log_exit(f"主循环异常退出: {type(exc).__name__}: {exc}")
        raise
    finally:
        bridge.stop()  # worker drain + SDK 断开 + loop 线程停止 + 释放单实例锁
        engine = getattr(handler, "_engine", None)
        closer = getattr(engine, "close", None)
        if closer is not None:
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 — 关闭失败 fail-open
                logger.warning("引擎关闭失败（fail-open）: %s", exc)
        _log_exit(f"优雅退出完成（信号 {received_signal[0]}）")
        print("企微桥已停止。")


if __name__ == "__main__":
    main()
