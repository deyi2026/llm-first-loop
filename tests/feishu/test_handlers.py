"""飞书消息处理测试（M42，用例 6-15）.

消息处理（6-11）：文本→引擎→回复 / 类型分发 / 防循环 / 回复原会话 / 长回复分段 / 失败如实。
附件处理（12-15）：图片识别（复用 M39 vision）/ 校验拒绝 / 失败 fail-open / 注入上下文（复用 M39 upload_handlers）。
全部 FakeLLM 装配引擎 + Mock 下载/识别，零真实飞书 API、零真实网络。
"""

import json
import logging

import pytest

from llm_loop.feishu.bridge import FeishuWsBridge
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap


def _msg(
    msg_type: str = "text",
    sender_id: str = "ou_a",
    chat_id: str = "oc_a",
    text: str = "",
    sender_type: str = "user",
    file_key: str | None = None,
    file_name: str = "",
) -> FeishuMessage:
    return FeishuMessage(
        message_id=f"om_{msg_type}_{sender_id}",
        sender_id=sender_id,
        chat_id=chat_id,
        msg_type=msg_type,
        text=text,
        sender_type=sender_type,
        file_key=file_key,
        file_name=file_name,
    )


def _make_handler(build_test_engine, tmp_path, responses=None, chunk_limit: int = 3500):
    engine, fake = build_test_engine(responses or [{"content": "默认回答"}])
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_session_map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
        chunk_limit=chunk_limit,
    )
    return handler, engine, fake, session_map, replies


# ── 用例 6-11：消息处理 ──


def test_msg_text_to_engine(build_test_engine, tmp_path):
    """用例 6：文本→engine.run（session_id/文本正确）+ 回复如实透传 + 空文本跳过."""
    handler, engine, fake, session_map, replies = _make_handler(
        build_test_engine, tmp_path, [{"content": "最终回答"}]
    )
    handler.handle(_msg(text="你好，请介绍一下"))

    # a) engine.run 被调用（session_id 正确、文本正确）
    assert len(fake.calls) == 1
    msgs = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "你好，请介绍一下" in msgs
    assert session_map.get(SessionMap.p2p_key("ou_a"))  # 映射已创建

    # b) 回复内容 = LoopResult.final_answer 如实透传
    assert replies == [("oc_a", "最终回答", "chat_id")]

    # c) 空文本 → 不调用引擎 + 不回复
    before = len(fake.calls)
    handler.handle(_msg(text="   "))
    assert len(fake.calls) == before
    assert len(replies) == 1


def test_sdk_event_message_chat_id(build_test_engine, tmp_path):
    """新增（M44 真实结构校准）：SDK 事件 chat_id 在 event.message 内（无 event.chat）→ 正确解包回复原会话."""
    from llm_loop.feishu.bridge import FeishuWsBridge
    from llm_loop.feishu.config import FeishuConfig

    handler, engine, fake, session_map, replies = _make_handler(
        build_test_engine, tmp_path, [{"content": "SDK 结构回复"}]
    )
    # 真实 SDK marshal 结构：chat_id/chat_type 在 event.message 内，无 event.chat
    payload = {
        "schema": "2.0",
        "header": {"event_id": "evt_sdk", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_sdk"}, "sender_type": "user"},
            "message": {
                "message_id": "om_sdk_1",
                "message_type": "text",
                "chat_id": "oc_sdk_chat",
                "chat_type": "p2p",
                "content": json.dumps({"text": "真实结构消息"}),
            },
        },
    }
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), handler)
    bridge._on_ws_message(payload)
    assert replies[0][0] == "oc_sdk_chat"  # 回复到来源会话（真实 chat_id 非空）
    assert replies[0][1] == "SDK 结构回复"
    msgs = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "真实结构消息" in msgs


def test_sdk_event_p2p_no_chat_id_reply_open_id(build_test_engine, tmp_path):
    """新增（M45 修复）：p2p 私聊事件无 chat_id → 回复目标用 open_id + receive_id_type=open_id（发送不再失败）."""
    from llm_loop.feishu.bridge import FeishuWsBridge
    from llm_loop.feishu.config import FeishuConfig

    handler, engine, fake, session_map, replies = _make_handler(
        build_test_engine, tmp_path, [{"content": "p2p 回复"}]
    )
    # 真实 p2p 场景：message 内 chat_id 为空（SDK marshal 后 p2p 无有效 chat_id）
    payload = {
        "schema": "2.0",
        "header": {"event_id": "evt_p2p", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_p2p_user"}, "sender_type": "user"},
            "message": {
                "message_id": "om_p2p_1",
                "message_type": "text",
                "chat_id": "",
                "chat_type": "p2p",
                "content": json.dumps({"text": "私聊消息"}),
            },
        },
    }
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), handler)
    bridge._on_ws_message(payload)
    # 修复断言：回复到 open_id（chat_id 缺失时不再用空 chat_id 发送）
    assert replies[0] == ("ou_p2p_user", "p2p 回复", "open_id")
    msgs = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "私聊消息" in msgs


def test_msg_type_dispatch(build_test_engine, tmp_path, monkeypatch):
    """用例 7：text/post 进引擎 + image/file 附件分支 + 不支持类型如实跳过."""
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)

    # a) text → 引擎
    handler.handle(_msg(text="文本消息"))
    assert len(fake.calls) == 1

    # a) post → 经桥解包提取富文本进引擎（复用 _extract_post_text）
    content = json.dumps(
        {
            "title": "富文本标题",
            "content": [
                [{"tag": "text", "text": "富文本段1"}, {"tag": "a", "text": "忽略链接"}],
                [{"tag": "text", "text": "富文本段2"}],
            ],
        }
    )
    post_payload = {
        "header": {"event_type": "im.message.receive_v1", "event_id": "evt_post"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_post"}, "sender_type": "user"},
            "message": {"message_id": "om_post", "message_type": "post", "content": content},
            "chat": {"chat_id": "oc_post", "chat_type": "p2p"},
        },
    }
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_test_app_0001", app_secret="sec"), handler)
    bridge._on_ws_message(post_payload)
    post_msgs = json.dumps(fake.calls[-1]["messages"], ensure_ascii=False)
    assert "富文本段1" in post_msgs
    assert "富文本段2" in post_msgs
    assert "忽略链接" not in post_msgs  # 非 text 标签不提取

    # b) image/file → 附件处理分支（Mock 下载被调用）
    downloaded: list[str] = []
    handler.register_attachment_download(
        lambda m: (downloaded.append(m.msg_type) or (b"data", f"{m.msg_type}.png"), "")
    )
    handler.handle(_msg(msg_type="image", file_key="fk_img"))
    handler.handle(_msg(msg_type="file", file_key="fk_file", file_name="a.txt"))
    assert "image" in downloaded
    assert "file" in downloaded

    # c) 不支持类型 → 如实跳过（提示）
    handler.handle(_msg(msg_type="audio"))
    assert replies[-1][1] == "暂不支持该消息类型。"


def test_msg_ignore_bot_self(build_test_engine, tmp_path):
    """用例 8：sender_type=app 跳过（引擎调用数=0）+ 用户消息正常处理."""
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)
    handler.handle(_msg(text="机器人自己消息", sender_type="app"))
    assert len(fake.calls) == 0
    assert replies == []

    handler.handle(_msg(text="用户消息", sender_type="user"))
    assert len(fake.calls) == 1


def test_msg_reply_original_chat(build_test_engine, tmp_path):
    """用例 9：回复发送到来源 chat_id + 内容如实透传."""
    handler, engine, fake, session_map, replies = _make_handler(
        build_test_engine, tmp_path, [{"content": "如实回答"}]
    )
    handler.handle(_msg(chat_id="oc_test", text="提问"))
    assert replies[0][0] == "oc_test"
    assert replies[0][1] == "如实回答"


def test_msg_long_reply_chunk(build_test_engine, tmp_path):
    """用例 10：长回复（含代码 fence）分段发送 + fence 闭合重开 + 各段拼接=原文无丢失."""
    body = "\n".join(f"第{i}行正文内容abcdefghij" for i in range(30))
    code = "```python\n" + "\n".join(f"print({i})  # 代码行" for i in range(20)) + "\n```"
    long_text = body + "\n" + code
    assert len(long_text) > 500

    handler, engine, fake, session_map, replies = _make_handler(
        build_test_engine, tmp_path, [{"content": long_text}], chunk_limit=100
    )
    handler.handle(_msg(text="写长代码"))

    # a) 分段发送（Mock 发送调用数 > 1）
    assert len(replies) > 1
    # b) fence 感知：代码块 fence 行完整保留（闭合重开不破坏内容）
    joined = "".join(text for _, text, _ in replies)
    assert "```python" in joined
    # c) 各段拼接（剥离 fence 修复对）= 原回复内容（无丢失）
    assert joined.replace("```\n```\n", "") == long_text
    # d) 每段长度有界（chunk_limit + fence 修复余量）
    for _, part, _ in replies:
        assert len(part) <= 100 + 8


def test_msg_failure_honest(build_test_engine, tmp_path, caplog):
    """用例 11：FakeLLM 抛异常 → 如实回复错误信息（非伪造回答）；发送失败日志如实记录."""

    # a) 引擎异常 → 回复含如实错误信息
    def boom(_calls):
        raise RuntimeError("engine boom")

    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path, [boom])
    handler.handle(_msg(text="触发异常"))
    assert "[程序异常]" in replies[0][1]
    assert "engine boom" in replies[0][1]

    # b) 发送失败 → 日志如实记录错误（无静默丢弃，异常如实传播）
    engine2, _ = build_test_engine([{"content": "正常回答"}])
    smap2 = SessionMap(engine2.session)
    broken_replies: list[tuple[str, str, str]] = []

    def _broken_reply(rid, text, rtype):
        broken_replies.append((rid, text, rtype))
        raise RuntimeError("send api failed")

    handler2 = FeishuMessageHandler(
        engine2, smap2, _broken_reply, audit_dir=str(tmp_path / "audit2")
    )
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="send api failed"):
        handler2.handle(_msg(text="会发送失败"))
    assert "feishu message handle failed" in caplog.text  # 适配并行重构后的日志文本


# ── 用例 12-15：附件处理 ──


def test_att_image_vision(build_test_engine, tmp_path, monkeypatch):
    """用例 12：图片 → Mock 下载 → 复用 vision 识别 → 识别文本注入上下文."""
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)
    handler.register_attachment_download(lambda m: (b"\x89PNG\r\n\x1a\n\x00\x00\x00\r", "pic.png"))
    monkeypatch.setattr("llm_loop.web.vision.vision_enabled", lambda: True)
    monkeypatch.setattr(
        "llm_loop.web.vision.describe_image", lambda *a, **k: "识别出的图片文字：车牌号ABC"
    )

    handler.handle(_msg(msg_type="image", file_key="fk_img", file_name="pic.png"))

    # a) 识别文本注入上下文（含来源标注文件名）
    msgs = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "识别出的图片文字：车牌号ABC" in msgs
    assert "pic.png" in msgs
    assert replies[0][1] == "默认回答"


def test_att_validate_reject(build_test_engine, tmp_path):
    """用例 13：超大小/不支持类型 → 如实拒绝（不调用引擎）."""
    # 超大小（>10MB）→ 拒绝
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)
    handler.register_attachment_download(lambda m: (b"x" * (10 * 1024 * 1024 + 1), "big.txt"))
    handler.handle(_msg(msg_type="file", file_key="fk_big", file_name="big.txt"))
    assert "10MB" in replies[0][1]
    assert len(fake.calls) == 0  # 校验失败不触发引擎

    # 不支持扩展名 → 拒绝（含支持类型清单）
    handler2, engine2, fake2, smap2, replies2 = _make_handler(build_test_engine, tmp_path)
    handler2.register_attachment_download(lambda m: (b"data", "evil.bin"))
    handler2.handle(_msg(msg_type="file", file_key="fk_evil", file_name="evil.bin"))
    assert "不支持的文件类型" in replies2[0][1]
    assert len(fake2.calls) == 0


def test_att_failure_failopen(build_test_engine, tmp_path, monkeypatch):
    """用例 14：下载失败/识别未配置/识别失败/提取失败 → 如实提示 + 不阻断主消息链路."""
    # a) 下载抛异常 → 如实提示
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)

    def _dl_boom(m):
        raise RuntimeError("dl boom")

    handler.register_attachment_download(_dl_boom)
    handler.handle(_msg(msg_type="image", file_key="fk1"))
    assert "下载失败" in replies[-1][1]

    # b) vision 无 key（未配置）→ 如实降级标注（无伪造描述）
    handler.register_attachment_download(lambda m: (b"\x89PNG", "pic.png"))
    monkeypatch.setattr("llm_loop.web.vision.vision_enabled", lambda: False)
    handler.handle(_msg(msg_type="image", file_key="fk2"))
    assert "视觉识别未配置" in replies[-1][1]

    # c) 识别失败（describe_image 抛 RuntimeError）→ 如实提示（无伪造文本）
    monkeypatch.setattr("llm_loop.web.vision.vision_enabled", lambda: True)
    monkeypatch.setattr(
        "llm_loop.web.vision.describe_image",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no key")),
    )
    handler.handle(_msg(msg_type="image", file_key="fk3"))
    assert "识别失败" in replies[-1][1]

    # d) 文档提取失败（process_upload 返回 error）→ 如实提示（无伪造文本）
    from llm_loop.web.upload_handlers import ExtractResult

    monkeypatch.setattr(
        "llm_loop.web.upload_handlers.process_upload",
        lambda f, d: ExtractResult(
            source_filename=f, content_type="docx", status="error", detail="docx 解析失败"
        ),
    )
    handler.register_attachment_download(lambda m: (b"bad", "broken.docx"))
    handler.handle(_msg(msg_type="file", file_key="fk4", file_name="broken.docx"))
    assert "附件处理失败" in replies[-1][1]
    assert "docx 解析失败" in replies[-1][1]

    # e) fail-open：附件失败不阻断主消息链路（后续 text 消息仍正常处理）
    before = len(fake.calls)
    handler.handle(_msg(text="附件失败后仍要对话"))
    assert len(fake.calls) == before + 1


def test_att_inject_context(build_test_engine, tmp_path):
    """用例 15：文件 → Mock 下载 → 复用 upload_handlers 提取 → 注入上下文（来源可追溯）."""
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)
    handler.register_attachment_download(lambda m: (b"hello attachment world", "notes.txt"))

    handler.handle(_msg(msg_type="file", file_key="fk_txt", file_name="notes.txt"))

    # a) 附件注入含提取文本 + 来源标注（文件名/类型）
    msgs = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "hello attachment world" in msgs
    assert "notes.txt" in msgs
    assert "text" in msgs  # 来源标注含内容类型
    assert replies[0][1] == "默认回答"


# ── M46：处理中动作显示挂钩（FR-TYP-05~08 + FR-CARD-06~09）──


class _FakeReactionSvc:
    """Mock rest_client reaction 面（add_typing_reaction / remove_reaction）.

    接收 message_id 字符串（与 FeishuRestClient 同签名），记录调用供断言。
    """

    def __init__(self, add_result="re_1"):
        self.add_calls: list[str] = []
        self.remove_calls: list[tuple[str, str]] = []
        self._add_result = add_result

    def add_typing_reaction(self, message_id: str) -> str:
        self.add_calls.append(message_id)
        return self._add_result

    def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        self.remove_calls.append((message_id, reaction_id))


class _FakeCardSvc:
    """Mock cardkit.v1.card（create/bind/close 调用记录）."""

    def __init__(self, ok=True):
        self.create_calls: list = []
        self.update_calls: list = []
        self.settings_calls: list = []
        self._ok = ok

    def create(self, request):
        self.create_calls.append(request)
        if not self._ok:
            return type("R", (), {"code": 230001, "msg": "fail", "data": None})()
        return type(
            "R", (), {"code": 0, "data": type("D", (), {"card_id": "om_card"})()}
        )()

    def update(self, request):
        self.update_calls.append(request)
        return type("R", (), {"code": 0})()

    def settings(self, request):
        self.settings_calls.append(request)
        return type("R", (), {"code": 0})()


def _processing_handler(
    build_test_engine,
    tmp_path,
    *,
    typing_ack=True,
    streaming=True,
    card_ok=True,
):
    """构造挂 M46 动作的 handler（rest_client + lark_client Mock 注入）."""
    engine, fake = build_test_engine([{"content": "处理中回复"}, {"content": "处理中回复"}])
    session_map = SessionMap(engine.session, path=str(tmp_path / "fsm_m46.json"))
    replies: list[tuple[str, str, str]] = []
    reaction = _FakeReactionSvc()
    card = _FakeCardSvc(ok=card_ok)
    fake_im = type(
        "Im",
        (),
        {
            "v1": type(
                "V1",
                (),
                {
                    "message_reaction": reaction,
                    "message": type(
                        "M",
                        (),
                        {
                            "create": lambda *a, **k: type(
                                "R",
                                (),
                                {"code": 0, "data": type("D", (), {"message_id": "om_sent"})()},
                            )()
                        },
                    )(),
                },
            )()
        },
    )()
    lark = type(
        "Lark",
        (),
        {
            "im": fake_im,
            "cardkit": type(
                "Ck",
                (),
                {
                    "v1": type(
                        "V1",
                        (),
                        {
                            "card": card,
                        },
                    )()
                },
            )(),
        },
    )()
    rest_client = type(
        "Rest",
        (),
        {
            "add_typing_reaction": reaction.add_typing_reaction,
            "remove_reaction": reaction.remove_reaction,
        },
    )()
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit_m46"),
        rest_client=rest_client,
        lark_client=lark,
        typing_ack=typing_ack,
        streaming=streaming,
    )
    return handler, fake, reaction, card, replies


def test_typing_ack_add_then_remove(build_test_engine, tmp_path):
    """用例 M46-⑥：收到消息 → 加 Typing reaction（顺序在回复前）→ 回复后删除."""
    handler, fake, reaction, card, replies = _processing_handler(build_test_engine, tmp_path)
    handler.handle(_msg(text="处理一下"))
    # a) add 一次（message_id 正确）+ remove 一次
    assert len(reaction.add_calls) == 1
    assert reaction.add_calls[0] == "om_text_ou_a"
    assert len(reaction.remove_calls) == 1
    assert reaction.remove_calls[0] == ("om_text_ou_a", "re_1")
    # b) 引擎执行 + 回复正常（动作不阻断主链路）
    assert replies[0][1] == "处理中回复"


def test_typing_ack_exception_still_removes(build_test_engine, tmp_path):
    """用例 M46-⑦：引擎异常 → finally 仍删除 reaction（best-effort 清理保证）."""
    engine, fake = build_test_engine([{"content": "x"}])

    def _boom_run(sid, text):
        raise RuntimeError("engine boom")

    engine.run = _boom_run  # type: ignore[method-assign]
    session_map = SessionMap(engine.session, path=str(tmp_path / "fsm_m46b.json"))
    replies: list[tuple[str, str, str]] = []
    reaction = _FakeReactionSvc()
    lark = type("Lark", (), {"im": None, "cardkit": None})()
    rest_client = type(
        "Rest",
        (),
        {"add_typing_reaction": reaction.add_typing_reaction, "remove_reaction": reaction.remove_reaction},
    )()
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit_m46b"),
        rest_client=rest_client,
        lark_client=lark,
        streaming=False,  # 聚焦 typing 路径
    )
    handler.handle(_msg(text="会失败"))
    assert len(reaction.add_calls) == 1
    assert len(reaction.remove_calls) == 1  # finally 保证删除
    assert "程序异常" in replies[-1][1]  # 如实反馈


def test_typing_ack_switch_off(build_test_engine, tmp_path):
    """用例 M46-⑧：本地既有实现_FEISHU_TYPING_ACK=0 → 零 reaction 调用（行为与 M45 一致）."""
    handler, fake, reaction, card, replies = _processing_handler(
        build_test_engine, tmp_path, typing_ack=False
    )
    handler.handle(_msg(text="处理一下"))
    assert reaction.add_calls == []
    assert reaction.remove_calls == []
    assert replies[0][1] == "处理中回复"  # 回复正常


def test_status_card_start_and_close(build_test_engine, tmp_path):
    """用例 M46-⑨：状态卡建卡（create+bind）→ 处理完成定稿（update+settings）."""
    handler, fake, reaction, card, replies = _processing_handler(build_test_engine, tmp_path)
    handler.handle(_msg(text="处理一下"))
    # a) 建卡：cardkit create 一次 + interactive 发卡（bind 走 message.create）
    assert len(card.create_calls) == 1
    # b) 定稿：update + settings 各一次
    assert len(card.update_calls) == 1
    assert len(card.settings_calls) == 1
    # c) 正式回复仍发出（状态卡不承载最终内容）
    assert replies[0][1] == "处理中回复"


def test_status_card_fail_fallback(build_test_engine, tmp_path):
    """用例 M46-⑩：状态卡建卡失败 → 回退普通分段路径（回复不丢）."""
    handler, fake, reaction, card, replies = _processing_handler(
        build_test_engine, tmp_path, card_ok=False
    )
    handler.handle(_msg(text="处理一下"))
    assert len(card.create_calls) == 1  # 尝试建卡
    assert card.update_calls == []  # 未建成功 → 无定稿
    assert card.settings_calls == []
    assert replies[0][1] == "处理中回复"  # 回复不丢失


def test_streaming_switch_off(build_test_engine, tmp_path):
    """用例 M46-⑩b：本地既有实现_FEISHU_STREAMING=0 → 零状态卡调用（行为与 M45 一致）."""
    handler, fake, reaction, card, replies = _processing_handler(
        build_test_engine, tmp_path, streaming=False
    )
    handler.handle(_msg(text="处理一下"))
    assert card.create_calls == []
    assert card.update_calls == []
    assert card.settings_calls == []
    assert replies[0][1] == "处理中回复"


def test_attachment_inject_processing_actions(build_test_engine, tmp_path):
    """用例 M46-⑩c：附件路径（_inject_and_reply）同样挂 Typing + 状态卡 + 回复正常."""
    handler, fake, reaction, card, replies = _processing_handler(build_test_engine, tmp_path)
    handler.register_attachment_download(lambda m: (b"content", "a.txt"))
    handler.handle(_msg(msg_type="file", file_key="fk_m46", file_name="a.txt"))
    assert len(reaction.add_calls) == 1  # 附件也加 reaction
    assert len(card.create_calls) == 1  # 附件也建状态卡
    assert len(reaction.remove_calls) == 1
    assert replies[0][1] == "处理中回复"


def test_audit_record_has_ts(build_test_engine, tmp_path):
    """P1-2-R1: 审计记录含 ts 时间戳字段（断线时刻时间对齐回归分析数据源）."""
    handler, engine, fake, session_map, replies = _make_handler(build_test_engine, tmp_path)
    m = _msg()
    m.message_id = "om_ts_1"
    handler._audit(m, kind="receive", detail="测试审计")
    audit_file = tmp_path / "audit" / "feishu_audit.jsonl"
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(lines[-1])
    assert isinstance(last.get("ts"), float)
    # 既有字段完整保留
    assert last["message_id"] == "om_ts_1"
    assert last["kind"] == "receive"
    assert last["detail"] == "测试审计"
    # 旧记录（无 ts）读取不报错
    audit_file.write_text('{"message_id": "old", "kind": "receive", "detail": "x"}\n', encoding="utf-8")
    assert json.loads(audit_file.read_text(encoding="utf-8").splitlines()[0])["message_id"] == "old"
