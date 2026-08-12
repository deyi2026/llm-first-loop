"""飞书桥装配与启动（M42，薄壳适配器）.

复用 load_settings + build_engine（与 CLI/Web 同源装配），核心零改动。
build_bridge(engine=None) 支持测试注入；python -m llm_loop.feishu 启动入口。
"""

import contextlib
import logging
import os
import sys

from llm_loop.config import load_settings
from llm_loop.factory import build_engine

from .bridge import FeishuWsBridge
from .config import FeishuConfig, load_feishu_config
from .handlers import FeishuMessageHandler
from .session_map import SessionMap

__all__ = ["build_bridge", "start_bridge", "main"]

logger = logging.getLogger(__name__)

# P1-3-R2: 优雅退出时间契约 —— wait(10) + drain(3) = 13s ≤ GRACE_S(15) − 2s 余量。
# 硬编码 30s > GRACE_S 15s 是 2026-08-12 22:41 feishu 被 SIGKILL 强杀的直接原因。
def _env_float(name: str, default: float) -> float:
    """读取 env 浮点值（非法值回退默认，fail-open）."""
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


_EXIT_WAIT_S: float = _env_float("FEISHU_EXIT_WAIT_S", 10)
_EXIT_DRAIN_S: float = _env_float("FEISHU_EXIT_DRAIN_S", 3)


def build_bridge(engine=None, config: FeishuConfig | None = None, lark_client=None):
    """装配飞书桥（薄壳）：config + engine + session_map + bridge + handler.

    M44 SDK 化：共享 lark.Client（builder 模式创建 / lark_client 参数可注入 Mock）→ 注入 bridge → rest
    （token 生命周期交 SDK 内部管理）；装配顺序：bridge 先建 → handler reply_fn=bridge.send_text →
    register_attachment_download(bridge.download_attachment) → attach_handler（handlers.py 零改动）。
    """
    if config is None:
        config = load_feishu_config()
    if engine is None:
        settings = load_settings()
        engine = build_engine(settings)
    if lark_client is None:
        import lark_oapi as lark

        lark_client = (
            lark.Client.builder()
            .app_id(config.app_id)
            .app_secret(config.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
    session_map = SessionMap(
        engine.session,
        path=config.session_map_path,
        owner_open_id=config.owner_open_id,
    )
    bridge = FeishuWsBridge(config, handler=None, lark_client=lark_client)
    handler = FeishuMessageHandler(
        engine,
        session_map,
        # 装配真实发送（返回 bool 兼容 ReplyFn 的 None 返回——返回值被忽略，pyright arg-type）
        reply_fn=bridge.send_text,  # type: ignore[arg-type]
        chunk_limit=config.chunk_limit,
        # M46：处理中动作显示（Typing reaction + 状态卡），开关对齐 本地既有实现 命名
        rest_client=bridge._ensure_rest_client(),
        lark_client=lark_client,
        typing_ack=config.typing_ack,
        streaming=config.streaming,
    )
    handler.register_attachment_download(bridge.download_attachment)
    bridge.attach_handler(handler)
    return bridge, handler, session_map


def start_bridge(bridge: FeishuWsBridge) -> bool:
    """启动桥（启用条件 + 预检 + 后台线程）."""
    return bridge.start()


def main() -> None:
    """飞书桥启动入口（python -m llm_loop.feishu）."""
    # EVO-20260811-f94e5306: 记录进程启动版本（一致性检测）
    from llm_loop.introspection.proc_version import record_process_start

    record_process_start("feishu")
    config = load_feishu_config()
    if not config.enabled:
        print(
            "飞书桥未启用（FEISHU_APP_ID/FEISHU_APP_SECRET 未配置或 FEISHU_WS_ENABLED=0）。",
            file=sys.stderr,
        )
        raise SystemExit(0)
    try:
        bridge, handler, session_map = build_bridge(config=config)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not start_bridge(bridge):
        print("飞书桥启动失败（凭证预检未通过）。", file=sys.stderr)
        raise SystemExit(2)
    print("飞书桥已启动（Ctrl+C 停止）。")
    # 优雅停机：SIGTERM（restart_system.sh）/ SIGINT / SIGHUP 均触发 bridge.stop()。
    # 退出原因记录到 data/feishu_exit.log（精确定位信号来源/异常退出，便于诊断反复退出）。
    import datetime
    import os
    import signal
    import threading

    _exit_log_path = os.path.join(
        os.environ.get("DATA_DIR", "data"), "feishu_exit.log"
    )

    def _log_exit(reason: str) -> None:
        try:
            with open(_exit_log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat()} pid={os.getpid()} {reason}\n")
        except OSError as exc:  # fail-open：退出日志写失败不影响退出
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
        signal.signal(signal.SIGHUP, _request_stop)  # 终端关闭保护（默认 SIGHUP 直接终止）
    try:
        while not stop_event.wait(1):
            pass
    except BaseException as exc:  # noqa: BLE001 — 任何主循环异常都如实记录再退出
        _log_exit(f"主循环异常退出: {type(exc).__name__}: {exc}")
        raise
    finally:
        # P1-3-R2: 优雅退出时间契约 —— wait 上限可配（默认 10s ≤ GRACE_S 15s 余量），
        # 超时如实记录（不再静默被 SIGKILL 强杀）；wait_until_idle 本体零改动。
        drained = False
        with contextlib.suppress(Exception):
            drained = bool(handler.wait_until_idle(_EXIT_WAIT_S))
        if not drained:
            logger.warning("优雅退出: 等待处理中消息超时 %.0fs（busy 未归零）", _EXIT_WAIT_S)
        bridge.stop()
        if drained:
            _log_exit(f"优雅退出完成（信号 {received_signal[0]}）")
        else:
            _log_exit(f"优雅退出超时未完成（等待 {_EXIT_WAIT_S:.0f}s，busy 未归零）")
        print("飞书桥已停止。")


if __name__ == "__main__":
    main()
