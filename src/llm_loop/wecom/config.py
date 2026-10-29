"""企微智能机器人桥配置读取（M0-2，平移 feishu/config.py 范式）.

凭据仅从进程 env 读取（键名对齐官方 README：WECHAT_BOT_ID / WECHAT_BOT_SECRET），
缺失时抛 ValueError（错误信息含字段名），不给静默默认值。
会话映射文件默认 {DATA_DIR}/wecom_session_map.json——与飞书
feishu_session_map.json 分离，避免跨通道污染（M0-6 硬约束）。
"""

import os
from dataclasses import dataclass

BOT_ID_ENV = "WECHAT_BOT_ID"
SECRET_ENV = "WECHAT_BOT_SECRET"
SESSION_MAP_PATH_ENV = "WECHAT_SESSION_MAP_PATH"
OWNER_USERID_ENV = "WECHAT_OWNER_USERID"

DEFAULT_SESSION_MAP_FILENAME = "wecom_session_map.json"


@dataclass
class WeComConfig:
    """企微桥配置（env 直读，对齐 feishu/config.py 既有 env 读取范式）."""

    bot_id: str
    secret: str
    session_map_path: str | None = None
    owner_userid: str = ""  # 跨端共享：owner 单聊与 Web 共享同一会话（空=不启用）
    # 企微协议 markdown.content 上限 20480 字节（utf-8，设计文档 §2.2），
    # 与飞书 chunk_limit（30000 字符）语义不同：此处是字节预算
    chunk_limit: int = 20480

    @property
    def has_credentials(self) -> bool:
        """凭证是否完整（bot_id + secret 均非空）."""
        return bool(self.bot_id and self.secret)


def load_wecom_config() -> WeComConfig:
    """读取企微配置（env）.

    Returns:
        WeComConfig。

    Raises:
        ValueError: 缺 WECHAT_BOT_ID / WECHAT_BOT_SECRET（错误信息含字段名，
            不提供静默默认值——与飞书"空串+不启用"语义不同，缺凭据即配置错误）。
    """
    bot_id = os.environ.get(BOT_ID_ENV, "").strip()
    secret = os.environ.get(SECRET_ENV, "").strip()
    missing = [name for name, value in ((BOT_ID_ENV, bot_id), (SECRET_ENV, secret)) if not value]
    if missing:
        raise ValueError(
            "企微桥配置缺失: " + "、".join(missing) + " 未设置"
            "（凭据仅从环境变量读取，不提供默认值；请在 .env 或进程环境中配置）"
        )
    session_map_path = (
        os.environ.get(SESSION_MAP_PATH_ENV, "").strip()
        or f"{os.environ.get('DATA_DIR', './data')}/{DEFAULT_SESSION_MAP_FILENAME}"
    )
    owner_userid = os.environ.get(OWNER_USERID_ENV, "").strip()
    return WeComConfig(
        bot_id=bot_id,
        secret=secret,
        session_map_path=session_map_path,
        owner_userid=owner_userid,
    )
