"""飞书桥装配与启动（M42，薄壳适配器）.

复用 load_settings + build_engine（与 CLI/Web 同源装配），核心零改动。
build_bridge(engine=None) 支持测试注入；python -m llm_loop.feishu 启动入口。
"""

import sys

from llm_loop.config import load_settings
from llm_loop.factory import build_engine

from .bridge import FeishuWsBridge
from .config import FeishuConfig, load_feishu_config
from .handlers import FeishuMessageHandler
from .session_map import SessionMap

__all__ = ["build_bridge", "start_bridge", "main"]


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
    session_map = SessionMap(engine.session, path=config.session_map_path)
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
    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bridge.stop()
        print("飞书桥已停止。")


if __name__ == "__main__":
    main()
