"""企微帧解包与分发（M0-3，SDK 三缺口的仓库侧补齐点）.

SDK（wecom-aibot-python-sdk 1.0.2）只用作连接层（鉴权/心跳/重连/加解密/
文件下载）；消息分发与语义判断在本仓库侧完成。本模块监听 SDK 的原始
"message" / "event" 事件后自行按 body["msgtype"] / eventtype 分发，
不依赖 SDK 的 MessageType / EventType 枚举。

三处 SDK 缺口与本模块的对应（缺口定义见设计文档 §三）：
- 缺口 a（video）：SDK MessageType 枚举无 video、message_handler 无分发分支，
  video 帧只落 SDK debug 日志被静默吞掉 → 本侧 _extract_payload 对
  text/image/video/mixed/voice/file 全类型解包（含 video）。
- 缺口 b（disconnected_event）：SDK EventType 枚举无 disconnected_event →
  本侧 parse_event_frame 按帧内 body.event.eventtype 原样解析（不假设枚举）。
- 缺口 c（compat_info）：SDK 完全不解析 compat_info（非普通用户消息标识，
  如 ai_assistant/channel 来源）→ 本侧 parse_message_frame 开头检查，
  非空即跳过（避免智能助理/频道消息误触发机器人）。

帧结构（SDK types.py WsFrame + 官方协议 path/101463）：
{cmd, headers: {req_id, ...}, body: {msgtype, from: {userid}, chatid,
 chat_type, text/image/video/..., compat_info}, errcode, errmsg}
"""

import logging
from typing import Any

from .messages import WeComMessage

logger = logging.getLogger(__name__)

# 本侧解包覆盖的消息类型全集（含 SDK 枚举缺失的 video——缺口 a 补齐）
SUPPORTED_MESSAGE_TYPES = ("text", "image", "video", "mixed", "voice", "file")

# 官方协议描述的"被踢下线"事件类型（SDK EventType 枚举无此项——缺口 b 补齐；
# 实际触发时机未实测，见设计文档 §七.3；客户端层的 disconnected 事件由
# bridge 另行监听，两层互不混淆）
DISCONNECTED_EVENT_TYPE = "disconnected_event"

# 事件回调帧 cmd（SDK WsCmd.EVENT_CALLBACK，ws.py:228 分流依据）
EVENT_CALLBACK_CMD = "aibot_event_callback"


def frame_req_id(frame: dict[str, Any] | None) -> str:
    """提取帧 headers.req_id（回复必须透传同一 req_id——企微协议硬要求）."""
    if not isinstance(frame, dict):
        return ""
    headers = frame.get("headers") or {}
    return str(headers.get("req_id", "") or "")


def _extract_payload(body: dict[str, Any]) -> tuple[str, str | None, str | None, str]:
    """按 msgtype 提取 (text, file_url, file_aeskey, file_name).

    全类型分发（缺口 a）：video 与 image/file 同构取 url/aeskey
    （SDK client.py:311 注明 aeskey 取自 image.aeskey / file.aeskey；
    video 字段结构按同构协议解析，真实帧样例未实测，见设计文档 §七）。
    """
    msg_type = str(body.get("msgtype", "") or "")
    text = ""
    file_url: str | None = None
    file_aeskey: str | None = None
    file_name = ""
    if msg_type == "text":
        text = str((body.get("text") or {}).get("content", "") or "")
    elif msg_type in ("image", "video", "file"):
        payload = body.get(msg_type) or {}
        file_url = str(payload.get("url", "") or "") or None
        file_aeskey = str(payload.get("aeskey", "") or "") or None
        file_name = str(payload.get("filename", "") or "")
    elif msg_type == "mixed":
        # 图文混排：M0 仅提取全部 item 文本拼合（图片/附件留 M1-3）
        parts = [
            str(item.get("text", "") or "")
            for item in (body.get("mixed") or {}).get("item", [])
            if isinstance(item, dict)
        ]
        text = "\n".join(p for p in parts if p)
    elif msg_type == "voice":
        payload = body.get("voice") or {}
        file_url = str(payload.get("url", "") or "") or None
        file_aeskey = str(payload.get("aeskey", "") or "") or None
        # 语音转文字字段（协议文档有 chat_text；缺省空）
        text = str(payload.get("chat_text", "") or "")
    return text, file_url, file_aeskey, file_name


def parse_message_frame(frame: dict[str, Any]) -> WeComMessage | None:
    """消息回调帧 → WeComMessage（SDK "message" 原始事件的仓库侧分发）.

    Returns:
        WeComMessage：解包成功；
        None：跳过该帧（compat_info 非空=非普通用户消息【缺口 c 补齐】，
        或 body 结构无效）。跳过原因记日志，不静默。
    """
    if not isinstance(frame, dict):
        logger.warning("企微消息帧类型异常（非 dict），跳过: %r", type(frame))
        return None
    body = frame.get("body")
    if not isinstance(body, dict) or not body.get("msgtype"):
        logger.warning("企微消息帧 body 缺失或无 msgtype，跳过: %s", str(frame)[:200])
        return None
    # 缺口 c 补齐：compat_info 非空 ⇒ 非普通用户消息（ai_assistant/channel 来源），
    # 跳过以避免智能助理/频道消息误触发机器人（SDK 不解析该字段）
    if body.get("compat_info"):
        logger.info(
            "企微消息带 compat_info（非普通用户消息），跳过: msgtype=%s", body.get("msgtype")
        )
        return None
    msg_type = str(body.get("msgtype", "") or "")
    sender = body.get("from") or {}
    sender_id = str(sender.get("userid", "") or "")
    chat_id = str(body.get("chatid", "") or "")
    chat_type = str(body.get("chat_type", "") or "")
    text, file_url, file_aeskey, file_name = _extract_payload(body)
    # 消息标识：协议回调的 msgid 字段名未在 SDK 源码中出现（未核实），
    # 用 req_id 兜底（每次回调唯一，可满足去重/审计需要）
    message_id = str(body.get("msgid", "") or "") or frame_req_id(frame)
    return WeComMessage(
        message_id=message_id,
        sender_id=sender_id,
        chat_id=chat_id,
        chat_type=chat_type,
        msg_type=msg_type,
        text=text,
        is_group=bool(chat_id),
        sender_type="user",
        file_url=file_url,
        file_aeskey=file_aeskey,
        file_name=file_name,
        raw=frame,
        req_id=frame_req_id(frame),
    )


def parse_event_frame(frame: dict[str, Any]) -> str:
    """事件回调帧 → eventtype 字符串（SDK "event" 原始事件的仓库侧解析）.

    SDK EventType 枚举仅 enter_chat/template_card_event/feedback_event；
    本函数按帧内 body.event.eventtype 原样返回（不依赖枚举、不假设取值——
    disconnected_event 等未入枚举的事件类型由此补齐，缺口 b）。
    非事件帧/无 eventtype 返回空串。
    """
    if not isinstance(frame, dict) or frame.get("cmd") != EVENT_CALLBACK_CMD:
        return ""
    body = frame.get("body") or {}
    event = body.get("event")
    if not isinstance(event, dict):
        return ""
    return str(event.get("eventtype", "") or "")


def is_disconnected_event(frame: dict[str, Any]) -> bool:
    """是否为 disconnected_event 事件帧（官方协议：被踢下线时推送）.

    注意与 SDK 客户端层 "disconnected" 事件（连接层 ConnectionClosed，
    ws.py:205-206）区分：本函数只识别事件帧内的 eventtype；
    连接层断开由 bridge 监听 SDK "disconnected" 客户端事件另行处理。
    """
    return parse_event_frame(frame) == DISCONNECTED_EVENT_TYPE
