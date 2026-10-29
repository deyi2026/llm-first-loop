"""企微消息统一结构（M0-3，设计文档 §4.2 数据契约）.

WeComMessage 是桥解包后的统一消息结构；req_id 是企微协议新增必备字段
（飞书侧没有）：回复必须透传同一次回调的 req_id，服务端才认。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class WeComMessage:
    """企微消息（桥解包后的统一结构，字段对齐设计文档 §4.2 契约）."""

    message_id: str
    sender_id: str  # from.userid（非超管创建的机器人可能为加密 userid）
    chat_id: str  # 群聊 chatid；单聊为空
    chat_type: str  # "single" / "group"
    msg_type: str  # text / image / video / mixed / voice / file
    text: str = ""
    is_group: bool = False
    sender_type: str = ""  # user / app（防循环：app 跳过）
    file_url: str | None = None
    file_aeskey: str | None = None
    file_name: str = ""
    raw: dict[str, Any] | None = None
    reply_receive_id: str = ""  # 群聊 chatid / 单聊 userid
    reply_receive_id_type: str = ""  # "chatid" / "userid"
    req_id: str = ""  # 本次回调 req_id —— 回复必须绑定（企微协议硬要求）

    def __post_init__(self) -> None:
        """回复目标推导：群聊用 chatid；单聊 chatid 缺失用 sender userid."""
        if not self.reply_receive_id:
            if self.chat_id:
                self.reply_receive_id = self.chat_id
                self.reply_receive_id_type = "chatid"
            else:
                self.reply_receive_id = self.sender_id
                self.reply_receive_id_type = "userid"
        if not self.chat_type:
            self.chat_type = "group" if self.chat_id else "single"


# 回复回调签名（与飞书不同，企微回复必须绑定 req_id，故首参为 req_id）
WeComReplyFn = Callable[[str, str, str, str], None]  # (req_id, receive_id, text, receive_id_type)
