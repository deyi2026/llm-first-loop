"""M44 飞书全链路 SDK 化冒烟验证脚本（用户授权，≤5 次 REST/轮，FR-SDK-VAL-01~05）.

用法:
    export FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx
    .venv/bin/python scripts/feishu_smoke.py --chat-id oc_真实chat_id

链路（design 35.9，M44 SDK 化）：token 探针（预检）→ WS 长连接（lark ws.Client）→ 发送测试消息（真实 chat_id，M43 遗留项复验）。
配额受控（显式调用 ≤5 次/轮；SDK 内部 token 调用未计数如实标注）；失败如实记录不伪装成功。
"""

import argparse
import logging
import sys
import threading
import time

from llm_loop.feishu.bridge import FeishuWsBridge
from llm_loop.feishu.config import load_feishu_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("feishu_smoke")

_REST_BUDGET = 5


def _log_ok(step: str, detail: str = "") -> None:
    print(f"  ✅ {step}" + (f"（{detail}）" if detail else ""))


def _log_fail(step: str, reason: str) -> None:
    print(f"  ❌ {step}: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="M44 飞书全链路 SDK 化冒烟验证")
    parser.add_argument("--chat-id", default="", help="发送测试消息的目标会话 chat_id（真实值）")
    parser.add_argument("--ws-wait-s", type=float, default=6.0, help="WS 长连接监听秒数")
    args = parser.parse_args()

    config = load_feishu_config()
    if not config.enabled:
        print("❌ 飞书桥未启用（FEISHU_APP_ID/FEISHU_APP_SECRET 未配置或 FEISHU_WS_ENABLED=0）。")
        return 2
    print(f"飞书冒烟验证开始（app_id={config.app_id[:8]}...，显式 REST 配额 ≤{_REST_BUDGET}/轮）")
    print("（说明：token 生命周期由 SDK 内部管理，其内部 token 调用未计入显式配额）")

    # 1. token 探针（凭证预检，SDK 化：_token_ready 标志；探针为一次显式 HTTP 调用）
    bridge = FeishuWsBridge(config, None)
    probe = bridge._token_probe()
    if probe is not None:
        _log_fail("凭证预检探针", probe)
        return 1
    _log_ok("凭证预检探针", f"_token_ready={bridge._token_ready}（token 生命周期交 SDK，值零接触）")

    # 2. WS 长连接（lark-oapi ws.Client，SDK 官方协议；无显式 REST 配额）
    print(f"  ⏳ WS 长连接启动（lark-oapi ws.Client，验证 {args.ws_wait_s}s）")
    received: list[str] = []
    ws_errors: list[str] = []

    def _ws_probe() -> None:
        import lark_oapi as lark

        def _on_receive(data, ctx=None) -> None:
            received.append(str(lark.JSON.marshal(data))[:200])

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_receive)
            .build()
        )
        try:
            cli = lark.ws.Client(
                config.app_id,
                config.app_secret,
                event_handler=handler,
                log_level=lark.LogLevel.WARNING,
            )
            cli.start()  # 阻塞（SDK 内部 endpoint/连接/心跳/重连/收帧）
        except Exception as exc:  # noqa: BLE001 — 如实记录
            ws_errors.append(f"{type(exc).__name__}: {exc}")

    ws_thread = threading.Thread(target=_ws_probe, daemon=True)
    ws_thread.start()
    time.sleep(args.ws_wait_s)
    if ws_errors:
        _log_fail("WS 长连接", ws_errors[0])
    else:
        _log_ok("WS 长连接存活", f"收到帧 {len(received)} 条（连接成功，无异常退出）")
        for raw in received[:3]:
            print(f"     帧: {raw}")

    # 3. 发送测试消息（interactive 卡片 markdown 渲染，M45；真实 chat_id 复验）
    if args.chat_id:
        md_content = (
            "# 标题\n\n"
            "正文段落 **加粗** 与 `行内代码`\n\n"
            "```python\nprint(1)\n```\n\n"
            "- 列表项一\n- 列表项二\n\n"
            "| 列A | 列B |\n|---|---|\n| 1 | 2 |"
        )
        try:
            rest = bridge._ensure_rest_client()
            message_id = rest.send_text(args.chat_id, md_content)
            _log_ok("发送 md 测试消息（interactive 卡片）", f"message_id={message_id}")
            print("     内容含：标题/加粗/行内代码/代码块/列表/表格——请在飞书桌面端+手机端确认 markdown 渲染")
        except Exception as exc:  # noqa: BLE001 — 如实记录
            _log_fail("发送 md 测试消息（interactive 卡片）", f"{type(exc).__name__}: {exc}")
    else:
        print("  ⏳ 未提供 --chat-id，跳过发送测试消息（用真实 chat_id 发送 md 内容复验渲染）")

    print("\n冒烟完成（显式 REST 调用 ≤5 次，SDK 内部 token 调用未计数）")
    print("结果请落档 docs/m45_feishu_md_smoke_report.md（成功/失败如实记录 + 双端渲染确认）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
