"""企微消息处理测试（M0-5）：fake engine 验证回复内容正确且绑定 req_id.

零真实引擎/零真实连接（FakeEngine + 回复收集 list）。
"""

from llm_loop.wecom.handlers import WeComMessageHandler
from llm_loop.wecom.messages import WeComMessage


class FakeResult:
    def __init__(
        self,
        final_answer: str,
        truncated: bool = False,
        verification_note: str = "",
        provider_output_truncated: bool = False,
    ):
        self.final_answer = final_answer
        self.truncated = truncated
        self.verification_note = verification_note
        self.provider_output_truncated = provider_output_truncated


class FakeEngine:
    def __init__(self, answer: str = "测试答案"):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def run(self, sid: str, text: str, user_metadata=None):  # noqa: ARG002
        self.calls.append((sid, text))
        return FakeResult(self.answer)


class FakeSessionMap:
    def __init__(self):
        self.keys: list[str] = []

    def get_or_create(self, key: str) -> str:
        self.keys.append(key)
        return "sid_fixed"


def _text_msg(req_id: str = "req_h1", text: str = "你好", chat_id: str = "") -> WeComMessage:
    return WeComMessage(
        message_id=f"m_{req_id}",
        sender_id="u_handler",
        chat_id=chat_id,
        chat_type="group" if chat_id else "single",
        msg_type="text",
        text=text,
        sender_type="user",
        req_id=req_id,
    )


def _make(answer: str = "测试答案", chunk_limit: int = 20480, tmp_path=None):
    engine = FakeEngine(answer)
    smap = FakeSessionMap()
    replies: list[tuple[str, str, str, str]] = []
    handler = WeComMessageHandler(
        engine,
        smap,
        lambda req_id, rid, text, rtype: replies.append((req_id, rid, text, rtype)),
        audit_dir=str(tmp_path / "audit") if tmp_path else None,
        chunk_limit=chunk_limit,
    )
    return handler, engine, smap, replies


def test_handlers_reply_binds_req_id(tmp_path):
    """核心契约：回复元组首参 = 消息 req_id（企微协议硬要求）."""
    handler, engine, _, replies = _make(tmp_path=tmp_path)
    msg = _text_msg(req_id="req_bind_1")
    handler.handle(msg)
    assert replies == [("req_bind_1", "u_handler", "测试答案", "userid")]
    assert engine.calls == [("sid_fixed", "你好")]


def test_handlers_group_reply_target(tmp_path):
    """群聊消息：回复目标 chatid（receive_id_type=chatid），映射键 g:*."""
    handler, engine, smap, replies = _make(tmp_path=tmp_path)
    handler.handle(_text_msg(req_id="req_g1", chat_id="g_chat_9"))
    assert replies[0][1] == "g_chat_9"
    assert replies[0][3] == "chatid"
    assert smap.keys == ["g:g_chat_9"]


def test_handlers_empty_answer(tmp_path):
    """空回答 → 如实回执"(空回答)"（不静默吞）."""
    handler, _, _, replies = _make(answer="", tmp_path=tmp_path)
    handler.handle(_text_msg())
    assert replies[0][2] == "(空回答)"


def test_handlers_truncated_annotation(tmp_path):
    """引擎截断标注透传到回复."""
    handler = WeComMessageHandler(
        FakeEngine(),
        FakeSessionMap(),
        lambda *a: None,
        audit_dir=str(tmp_path / "audit"),
    )
    # 构造 truncated 结果
    class TruncEngine(FakeEngine):
        def run(self, sid, text, user_metadata=None):  # noqa: ARG002
            self.calls.append((sid, text))
            return FakeResult("长答案", provider_output_truncated=True)

    handler._engine = TruncEngine()  # noqa: SLF001 — 注入截断引擎
    replies: list = []
    handler._reply_fn = lambda req_id, rid, text, rtype: replies.append(text)  # noqa: SLF001
    handler.handle(_text_msg())
    assert any("（回答被截断）" in r for r in replies)


def test_handlers_chunk_limit_bytes(tmp_path):
    """超协议字节预算（20480 utf-8）→ 截断并如实标注（不切断多字节字符）."""
    handler, _, _, replies = _make(answer="你" * 30000, tmp_path=tmp_path)
    handler.handle(_text_msg())
    text = replies[0][2]
    assert text.endswith("（超长截断）")
    assert len(text.encode("utf-8")) <= 20480 + len("\n（超长截断）".encode()) + 3


def test_handlers_skip_bot_self(tmp_path):
    """防循环：机器人自身消息（sender_type=app）不进引擎不回复."""
    handler, engine, _, replies = _make(tmp_path=tmp_path)
    msg = _text_msg()
    msg.sender_type = "app"
    handler.handle(msg)
    assert engine.calls == []
    assert replies == []


def test_handlers_video_visible_not_silent(tmp_path):
    """video/image 类型：显式回执"暂不支持"（SDK 侧会静默吞 video，本侧必须可见）."""
    handler, engine, _, replies = _make(tmp_path=tmp_path)
    for mtype in ("video", "image"):
        msg = WeComMessage(
            message_id="m_av",
            sender_id="u_handler",
            chat_id="",
            chat_type="single",
            msg_type=mtype,
            sender_type="user",
            req_id=f"req_{mtype}",
        )
        handler.handle(msg)
    assert engine.calls == []  # 不进引擎
    assert len(replies) == 2  # 但有可见回执（不静默丢弃）
    assert all("暂不支持" in r[2] for r in replies)
