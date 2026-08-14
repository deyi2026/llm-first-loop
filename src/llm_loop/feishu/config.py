"""飞书桥配置读取（M42，薄壳适配器）.

FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_WS_ENABLED env 读取（借鉴 本地既有实现 配置面）。
M46：新增 FEISHU_TYPING_ACK / FEISHU_STREAMING 开关（对齐 本地既有实现 命名）。
密钥仅 env 读取，前端/日志零字面量；缺失如实报错。
"""

import os
from dataclasses import dataclass

FEISHU_WS_ENABLED_DEFAULT = "1"


@dataclass
class FeishuConfig:
    """飞书桥配置（env 直读，对齐 config.py 既有 env 读取范式）."""

    app_id: str
    app_secret: str
    ws_enabled: bool = True
    session_map_path: str | None = None
    chunk_limit: int = 30000  # F3(2026-08-14): 50000 字符≈150KB 触物理上限，降 30000（≈90KB）留余量
    typing_ack: bool = True  # M46：Typing reaction 回执（对齐 FEISHU_TYPING_ACK）
    streaming: bool = True  # M46：流式状态卡（对齐 FEISHU_STREAMING）
    owner_open_id: str = ""  # 跨端共享：owner 私聊与 Web 共享同一会话（空=不启用，各私聊独立）

    @property
    def enabled(self) -> bool:
        """飞书桥启用条件：凭证已配置 且 WS 未关闭（FEISHU_WS_ENABLED != '0'）."""
        return bool(self.app_id and self.app_secret) and self.ws_enabled

    @property
    def has_credentials(self) -> bool:
        """凭证是否完整（app_id + app_secret 均非空）."""
        return bool(self.app_id and self.app_secret)


def load_feishu_config() -> FeishuConfig:
    """读取飞书配置（env）.

    Returns:
        FeishuConfig（app_id/app_secret 未配置时为空串，enabled=False）。
    """
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    ws_enabled = os.environ.get(
        "FEISHU_WS_ENABLED", FEISHU_WS_ENABLED_DEFAULT
    ).strip().lower() not in ("0", "false", "off", "no")
    session_map_path = (
        os.environ.get("FEISHU_SESSION_MAP_PATH", "").strip()
        or f"{os.environ.get('DATA_DIR', './data')}/feishu_session_map.json"
    )
    chunk_limit = _env_int("FEISHU_CHUNK_LIMIT", 30000)  # F3: 字节预算语义（见 handlers._chunk_markdown）
    typing_ack = _env_flag("FEISHU_TYPING_ACK", True)
    streaming = _env_flag("FEISHU_STREAMING", True)
    owner_open_id = os.environ.get("FEISHU_OWNER_OPEN_ID", "").strip()
    return FeishuConfig(
        app_id=app_id,
        app_secret=app_secret,
        ws_enabled=ws_enabled,
        session_map_path=session_map_path,
        chunk_limit=max(chunk_limit, 200),
        typing_ack=typing_ack,
        streaming=streaming,
        owner_open_id=owner_open_id,
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    """env 布尔读取：显式 0/false/off/no 关闭，其余默认."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "off", "no")
