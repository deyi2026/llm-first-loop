"""Web → 飞书会话实时推送（M56，薄壳适配器）.

当用户在 Web 端向"飞书来源"的会话发消息时，把用户消息 + AI 回答实时推送回对应
飞书会话（chat_id / open_id），实现两端会话实时传输。

- 复用 FeishuRestClient（不复制发送逻辑）；凭证从 env 直读（与飞书桥同源）。
- fail-open：推送失败如实记录日志，绝不阻断 Web 对话主链路。
- 密钥不出域：不落日志/不返回给前端。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "feishu:"


def parse_feishu_channel(channel: str) -> tuple[str, str] | None:
    """解析会话来源通道 → (receive_id, receive_id_type).

    支持:
    - "feishu:p2p:{open_id}"  → (open_id, "open_id")
    - "feishu:group:{chat_id}" → (chat_id, "chat_id")
    非飞书来源/格式非法 → None（调用方跳过推送）。
    """
    if not channel or not channel.startswith(_CHANNEL_PREFIX):
        return None
    parts = channel.split(":")
    if len(parts) < 3 or parts[1] not in ("p2p", "group"):
        return None
    kind, target = parts[1], parts[2]
    # 2026-08-16: 复合通道（共享会话 `+web` 后缀）——去后缀还原目标 id
    target = target.split("+")[0]
    if not target:
        return None
    return (target, "open_id" if kind == "p2p" else "chat_id")


def _build_lark_client(config: Any) -> Any:
    """构造共享 lark.Client（推送用，与飞书桥同构）."""
    import lark_oapi as lark  # pyright: ignore[reportMissingImports]

    return (
        lark.Client.builder()
        .app_id(config.app_id)
        .app_secret(config.app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )


def push_web_chat_to_feishu(channel: str, user_text: str, answer: str) -> bool:
    """把 Web 端对话推送到飞书会话（background task 调用）.

    Args:
        channel: 会话来源通道（"feishu:p2p:*" / "feishu:group:*"）。
        user_text: Web 端用户消息原文。
        answer: AI 回答（final_answer 原文）。

    Returns:
        True 推送成功；False 非飞书来源/未配置凭证/推送失败（均如实记录）。
    """
    parsed = parse_feishu_channel(channel)
    if parsed is None:
        return False
    receive_id, receive_id_type = parsed

    try:
        from llm_loop.feishu.config import load_feishu_config
        from llm_loop.feishu.rest import FeishuRestClient

        config = load_feishu_config()
        if not config.has_credentials:
            logger.warning("飞书推送跳过：FEISHU_APP_ID/FEISHU_APP_SECRET 未配置")
            return False
        client = FeishuRestClient(config, _build_lark_client(config))
        text = f"[Web 端消息] {user_text}\n\n{answer}"
        client.send_text(receive_id, text, receive_id_type)
        logger.info("飞书推送成功（%s=%s 前 8 位）", receive_id_type, receive_id[:8])
        return True
    except Exception as exc:  # noqa: BLE001 — 推送失败如实记录，不阻断 Web 主链路
        logger.warning("飞书推送失败（receive_id=%s）: %s", receive_id[:8], exc)
        return False
