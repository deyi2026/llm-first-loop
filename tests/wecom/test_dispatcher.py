"""企微帧解包与分发测试（M0-3）：text/image/video 解包 + compat_info 跳过
+ disconnected_event 识别（SDK 三缺口的仓库侧补齐验证）.

全部用构造帧（零真实连接）。帧结构对齐 SDK WsFrame（types.py）与官方协议。
"""

from llm_loop.wecom.dispatcher import (
    DISCONNECTED_EVENT_TYPE,
    EVENT_CALLBACK_CMD,
    is_disconnected_event,
    parse_event_frame,
    parse_message_frame,
)


def _frame(msgtype: str, body_extra: dict | None = None, req_id: str = "req_t1") -> dict:
    body: dict = {
        "msgtype": msgtype,
        "from": {"userid": "u_test"},
        "chatid": "",
        "chat_type": "single",
    }
    body.update(body_extra or {})
    return {"cmd": "aibot_msg_callback", "headers": {"req_id": req_id}, "body": body}


def test_dispatch_text_frame():
    """text 帧解包：text/req_id/回复目标推导（单聊 → userid）."""
    frame = _frame("text", {"text": {"content": "你好企微"}}, req_id="req_text_1")
    msg = parse_message_frame(frame)
    assert msg is not None
    assert msg.msg_type == "text"
    assert msg.text == "你好企微"
    assert msg.req_id == "req_text_1"
    assert msg.sender_id == "u_test"
    assert msg.chat_id == ""
    assert msg.reply_receive_id == "u_test"
    assert msg.reply_receive_id_type == "userid"
    assert msg.is_group is False


def test_dispatch_image_frame():
    """image 帧解包：url/aeskey 提取（附件下载凭据，M1-3 用）."""
    frame = _frame(
        "image",
        {"image": {"url": "https://example.work.weixin.qq.com/img", "aeskey": "aes_img"}},
        req_id="req_img_1",
    )
    msg = parse_message_frame(frame)
    assert msg is not None
    assert msg.msg_type == "image"
    assert msg.file_url == "https://example.work.weixin.qq.com/img"
    assert msg.file_aeskey == "aes_img"
    assert msg.req_id == "req_img_1"


def test_dispatch_video_frame():
    """video 帧解包：SDK 枚举无 video（会被静默吞）——本仓库侧必须解出（缺口 a）."""
    frame = _frame(
        "video",
        {"video": {"url": "https://example.work.weixin.qq.com/v", "aeskey": "aes_v"}},
        req_id="req_video_1",
    )
    msg = parse_message_frame(frame)
    assert msg is not None  # 不被静默丢弃
    assert msg.msg_type == "video"
    assert msg.file_url == "https://example.work.weixin.qq.com/v"
    assert msg.file_aeskey == "aes_v"
    assert msg.req_id == "req_video_1"


def test_dispatch_group_chat_routing():
    """群聊帧：chatid 非空 → is_group=True、回复目标 chatid."""
    frame = _frame(
        "text",
        {"chatid": "g_chat_1", "chat_type": "group", "text": {"content": "群里的话"}},
        req_id="req_group_1",
    )
    msg = parse_message_frame(frame)
    assert msg is not None
    assert msg.is_group is True
    assert msg.chat_id == "g_chat_1"
    assert msg.reply_receive_id == "g_chat_1"
    assert msg.reply_receive_id_type == "chatid"


def test_dispatch_compat_info_skipped():
    """compat_info 非空（非普通用户消息）→ 跳过该消息（缺口 c：SDK 不解析该字段）."""
    frame = _frame(
        "text",
        {"compat_info": {"source": "ai_assistant"}, "text": {"content": "系统消息"}},
        req_id="req_compat_1",
    )
    assert parse_message_frame(frame) is None


def test_dispatch_invalid_body_skipped():
    """body 缺失/无 msgtype → None（如实跳过，不抛异常）."""
    assert parse_message_frame({"headers": {"req_id": "r"}}) is None
    assert parse_message_frame({"body": {"msgtype": ""}, "headers": {}}) is None
    assert parse_message_frame("not-a-dict") is None  # type: ignore[arg-type]


def test_dispatch_disconnected_event_recognized():
    """disconnected_event 事件帧被识别（缺口 b：SDK EventType 枚举无此项）."""
    frame = {
        "cmd": EVENT_CALLBACK_CMD,
        "headers": {"req_id": "req_evt_1"},
        "body": {"event": {"eventtype": DISCONNECTED_EVENT_TYPE}},
    }
    assert parse_event_frame(frame) == DISCONNECTED_EVENT_TYPE
    assert is_disconnected_event(frame) is True


def test_dispatch_event_frame_other_types():
    """已知事件类型原样解析（enter_chat）；非事件帧/无 eventtype → 空串."""
    enter = {
        "cmd": EVENT_CALLBACK_CMD,
        "headers": {"req_id": "req_evt_2"},
        "body": {"event": {"eventtype": "enter_chat"}},
    }
    assert parse_event_frame(enter) == "enter_chat"
    assert is_disconnected_event(enter) is False
    # 非事件帧（消息回调 cmd）→ 空串
    msg_frame = _frame("text")
    assert parse_event_frame(msg_frame) == ""
    # 无 eventtype → 空串
    assert parse_event_frame({"cmd": EVENT_CALLBACK_CMD, "body": {}}) == ""
