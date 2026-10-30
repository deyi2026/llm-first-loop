"""防回灌测试（⑦）：协议键名修正（chattype/msgid）+ 回声抑制双向 + app 分支.

协议依据（官方 path/101463 原文）：aibot_msg_callback 的 body 含
msgid/aibotid/chatid/chattype（无下划线）/from.userid——from 结构无任何
来源标记（sender_type），防回灌靠内容回声抑制兜底。
"""

import time

from llm_loop.wecom.dispatcher import parse_message_frame
from llm_loop.wecom.handlers import WeComMessageHandler
from llm_loop.wecom.messages import WeComMessage


class FakeResult:
    def __init__(self, final_answer: str):
        self.final_answer = final_answer
        self.truncated = False
        self.verification_note = ""
        self.provider_output_truncated = False


class FakeEngine:
    def __init__(self, answer: str = "BOT_ANSWER_42"):
        self.answer = answer
        self.calls: list[str] = []

    def run(self, sid, text, ingress=None, user_metadata=None):  # noqa: ARG002
        self.calls.append(text)
        return FakeResult(self.answer)


class FakeSessionMap:
    def get_or_create(self, key: str) -> str:  # noqa: ARG002
        return "sid_fixed"


def _make(tmp_path, answer="BOT_ANSWER_42"):
    engine = FakeEngine(answer)
    replies: list[tuple[str, str, str, str]] = []
    handler = WeComMessageHandler(
        engine,
        FakeSessionMap(),
        lambda req_id, rid, text, rtype: replies.append((req_id, rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    return handler, engine, replies


def _msg(text: str, *, chat_id: str = "CHAT1", sender_id: str = "u1",
         req_id: str = "req_1", sender_type: str = "user") -> WeComMessage:
    return WeComMessage(
        message_id=f"m_{req_id}",
        sender_id=sender_id,
        chat_id=chat_id,
        chat_type="group" if chat_id else "single",
        msg_type="text",
        text=text,
        sender_type=sender_type,
        req_id=req_id,
    )


def _proto_frame(**body_overrides) -> dict:
    """官方协议原文形态的帧（chattype 无下划线 / from.userid / msgid）."""
    body = {
        "msgid": "MSGID_1",
        "aibotid": "AIBOTID",
        "chatid": "CHAT1",
        "chattype": "group",
        "from": {"userid": "USERID"},
        "msgtype": "text",
        "text": {"content": "@RobotA hello robot"},
    }
    body.update(body_overrides)
    return {"cmd": "aibot_msg_callback", "headers": {"req_id": "REQ1"}, "body": body}


# ── dispatcher 协议键名（P1 缺陷二：chattype 误读）──

def test_dispatcher_reads_protocol_chattype_key():
    """协议原文键 chattype（无下划线）必须被读到——此前误读 chat_type 恒空."""
    msg = parse_message_frame(_proto_frame())
    assert msg is not None and msg.chat_type == "group"


def test_dispatcher_chattype_fallback_and_msgid():
    """旧键 chat_type 兜底兼容；msgid 取协议字段（缺省回退 req_id）."""
    msg = parse_message_frame(_proto_frame(chattype="", chat_type="group"))
    assert msg is not None and msg.chat_type == "group"
    assert msg.message_id == "MSGID_1"
    msg2 = parse_message_frame(_proto_frame(chatid="", chattype="", msgid=""))
    assert msg2 is not None and msg2.message_id == "REQ1"  # req_id 兜底


def test_dispatcher_sender_type_is_honest_user():
    """协议无来源标记：真实帧恒 sender_type=user（诚实值，非判定结果）."""
    msg = parse_message_frame(_proto_frame())
    assert msg is not None and msg.sender_type == "user"


# ── 回声抑制（P1 缺陷一：防循环分支死代码的诚实兜底）──

def test_bot_echo_suppressed_no_engine_no_reply(tmp_path):
    """机器人回声被抑制：回复文本被回推 → 不调 engine.run、不产生新回复."""
    handler, engine, replies = _make(tmp_path)
    handler.handle(_msg("用户问题", req_id="req_q1"))  # 用户提问 → 回复 BOT_ANSWER_42
    assert engine.calls == ["用户问题"] and len(replies) == 1
    # 企微把机器人自己在群里的发言回推（文本=刚才的回复，同会话 chatid）
    handler.handle(_msg("BOT_ANSWER_42", req_id="req_echo"))
    assert engine.calls == ["用户问题"]  # 未进引擎
    assert len(replies) == 1  # 未产生新回复（回执也会被回推，必须静默）
    audit = (tmp_path / "audit" / "wecom_audit.jsonl").read_text(encoding="utf-8")
    assert "skip_echo_suppress" in audit


def test_user_repeat_question_not_suppressed(tmp_path):
    """用户重复提问不被抑制：问题文本 ≠ 机器人回复文本，正常二次进引擎."""
    handler, engine, replies = _make(tmp_path)
    handler.handle(_msg("同一个问题", req_id="req_q1"))
    handler.handle(_msg("同一个问题", req_id="req_q2"))
    assert engine.calls == ["同一个问题", "同一个问题"]  # 两次都进引擎
    assert len(replies) == 2


def test_echo_window_expiry(tmp_path, monkeypatch):
    """时间窗外不再抑制（窗口 env 可覆盖）——回声登记有时效."""
    monkeypatch.setenv("WECOM_ECHO_SUPPRESS_WINDOW_S", "0.05")
    handler, engine, replies = _make(tmp_path)
    handler.handle(_msg("q", req_id="req_q1"))
    assert len(replies) == 1
    time.sleep(0.1)
    handler.handle(_msg("BOT_ANSWER_42", req_id="req_echo"))
    assert engine.calls == ["q", "BOT_ANSWER_42"]  # 窗口外：正常处理


def test_echo_scoped_to_conversation(tmp_path):
    """抑制按会话隔离：A 群的回复文本出现在 B 群不受抑制（宁窄勿宽）."""
    handler, engine, replies = _make(tmp_path)
    handler.handle(_msg("q", chat_id="CHAT_A", req_id="req_a"))
    handler.handle(_msg("BOT_ANSWER_42", chat_id="CHAT_B", req_id="req_b"))
    assert engine.calls == ["q", "BOT_ANSWER_42"]  # B 群正常进引擎


def test_sender_type_app_branch_skips_engine(tmp_path):
    """显式 sender_type=app（测试构造/未来协议升级）时跳过——原死分支行为锁定."""
    handler, engine, replies = _make(tmp_path)
    handler.handle(_msg("x", sender_type="app", req_id="req_app"))
    assert engine.calls == [] and replies == []


# ---------------------------------------------------------------------------
# P1-2（2026-10-30 父代理 + 独立审查）：markdown 形态回声 → 无限刷屏循环
#
# 缺陷链（本仓库实测复现）：
#   1. 机器人回复形态是 markdown（bridge.py:502 → {"msgtype":"markdown",...}）
#   2. 服务端把机器人发言原样回推 → 帧 msgtype=markdown
#   3. dispatcher 此前不提取 markdown.content → msg.text 恒空
#   4. handler 的回声判定此前限定 msg_type=="text" → markdown 帧落到 unsupported 分支
#   5. unsupported 分支回执"暂不支持该消息类型。" → 该回执又是 markdown
#   6. → 再被回推 → 无限循环（独立审查实测：3 帧回声 → 3 条新回复，无自愈）
#
# 修复：dispatcher 提取 markdown.content；handler 对任何带文本的类型先判回声；
#       markdown 未命中回声也静默跳过（用户端无法发 markdown，markdown 必是机器人来源）。
# ---------------------------------------------------------------------------


def test_markdown_echo_does_not_trigger_reply_loop(tmp_path):
    """markdown 回声帧不得产生任何回复（否则无限刷屏循环）."""
    handler, engine, replies = _make(tmp_path)
    # 先产生一次真实回复（其形态即 markdown 内容 "BOT_ANSWER_42"）
    handler.handle(_msg("问题", req_id="req_q1"))
    assert len(replies) == 1 and replies[0][2] == "BOT_ANSWER_42"

    # 服务端把机器人这条 markdown 发言回推（msg_type=markdown，文本相同）
    echo = _msg("BOT_ANSWER_42", req_id="req_echo")
    echo.msg_type = "markdown"
    handler.handle(echo)

    # 关键断言：不得新增回复、不进引擎 —— 有回复就会被再次回推，形成循环
    assert len(replies) == 1, "markdown 回声产生了新回复 → 会形成无限刷屏循环"
    assert engine.calls == ["问题"], "markdown 回声不应进引擎"


def test_markdown_frame_never_auto_replies(tmp_path):
    """任何 markdown 帧（机器人来源）都不自动回执 —— 回执本身会被回推."""
    handler, engine, replies = _make(tmp_path)
    md = _msg("任意 markdown 内容", req_id="req_md")
    md.msg_type = "markdown"
    handler.handle(md)
    assert engine.calls == [] and replies == [], "markdown 帧不应触发引擎或回执"


def test_markdown_content_extracted_by_dispatcher():
    """dispatcher 必须提取 markdown.content（否则回声比对无文本可用）."""
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req_md"},
        "body": {
            "msgid": "MSGID_MD",
            "aibotid": "AIBOTID",
            "chatid": "CHAT1",
            "chattype": "group",
            "from": {"userid": "u1"},
            "msgtype": "markdown",
            "markdown": {"content": "机器人回声内容"},
        },
    }
    msg = parse_message_frame(frame)
    assert msg is not None
    assert msg.msg_type == "markdown"
    assert msg.text == "机器人回声内容"
