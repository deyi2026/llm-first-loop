"""企微智能机器人桥配置读取（M0-2，平移 feishu/config.py 范式）.

凭据仅从进程 env 读取（键名对齐官方 README：WECHAT_BOT_ID / WECHAT_BOT_SECRET），
缺失时抛 ValueError（错误信息含字段名），不给静默默认值。
会话映射文件默认 {DATA_DIR}/wecom_session_map.json——与飞书
feishu_session_map.json 分离，避免跨通道污染（M0-6 硬约束）。
"""

import os
from collections.abc import Iterable
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


def ensure_proxy_bypass(hosts: Iterable[str]) -> str:
    """把给定主机加入 no_proxy 绕过列表（强制直连，不经系统/环境代理）。

    背景（实测证据，非推断）：websockets>=15 在 connect() 时用
    urllib.request.getproxies() 自动取代理。macOS 系统代理通常带 socks 项
    （优先级高于 https，见 websockets/uri.py:213-223），websockets 会把 wss
    改写为 socks5h:// 并要求安装 python-socks，否则连接直接失败：
    "Failed to create WebSocket connection: python-socks is required to use
    a SOCKS proxy"。实测同一端点加 no_proxy 后握手成功、服务端返回 853000
    凭据错误（即网络层已通），未加则连接层即失败。

    企微端点是国内腾讯域名，设计前提为「本机直连、无需隧道」（设计文档 §二
    选型结论），故把该主机加入绕过列表，而不是让桥依赖本机代理软件是否在跑。

    副作用（已知且可接受）：设置 no_proxy 会使 urllib.request.getproxies()
    切到 env 模式，不再读 macOS 系统代理。本进程内 urllib 系网络访问只有
    websockets → 企微端点（正是要直连的目标）；LLM 客户端走 httpx 读
    HTTP(S)_PROXY 环境变量，未设置即直连，行为不变。

    Args:
        hosts: 要绕过代理的主机名（可多个，空值忽略）。

    Returns:
        实际写入的 no_proxy 值。幂等：重复调用结果相同。
    """
    entries: list[str] = []
    seen: set[str] = set()
    existing = os.environ.get("no_proxy", "") + "," + os.environ.get("NO_PROXY", "")
    for raw in existing.split(","):
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            entries.append(item)
    for raw in hosts:
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            entries.append(item)
    value = ",".join(entries)
    os.environ["no_proxy"] = value
    os.environ["NO_PROXY"] = value
    return value
