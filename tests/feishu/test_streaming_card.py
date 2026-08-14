"""飞书流式状态卡测试（M46，FR-CARD-01~05）.

StreamingCard 生命周期（create → bind → close）SDK Mock 注入，零真实网络。
覆盖：建卡成功/失败熔断 / bind 发 interactive / close 定稿（update+settings）/
token 失效重试 / 限流静默。全部 lark client Mock（_FakeCardkitService），无 real_llm 标记。
"""

import json

from llm_loop.feishu.streaming_card import StreamingCard, _card_json


class _FakeResp:
    def __init__(self, code=0, msg="", data=None, raw_status=200):
        self.code = code
        self.msg = msg
        self.data = data
        self.raw = type("R", (), {"status_code": raw_status})()


def _create_resp(code=0, card_id="om_card_1"):
    data = type("D", (), {"card_id": card_id})() if code == 0 else None
    return _FakeResp(code=code, data=data)


class _FakeCardService:
    def __init__(self, create_results=None, update_results=None, settings_results=None):
        self.create_calls: list = []
        self.update_calls: list = []
        self.settings_calls: list = []
        self._creates = list(create_results or [])
        self._updates = list(update_results or [])
        self._settings = list(settings_results or [])

    def create(self, request):
        self.create_calls.append(request)
        if self._creates:
            return self._creates.pop(0)
        return _create_resp()

    def update(self, request):
        self.update_calls.append(request)
        if self._updates:
            return self._updates.pop(0)
        return _FakeResp()

    def settings(self, request):
        self.settings_calls.append(request)
        if self._settings:
            return self._settings.pop(0)
        return _FakeResp()


class _FakeV1:
    def __init__(self, card):
        self.card = card


class _FakeCardkit:
    def __init__(self, card):
        self.v1 = _FakeV1(card)


class _FakeMessageService:
    def __init__(self, results=None):
        self.create_calls: list = []
        self._results = list(results or [])

    def create(self, request):
        self.create_calls.append(request)
        if self._results:
            return self._results.pop(0)
        return _FakeResp(data=type("D", (), {"message_id": "om_sent"})())


class _FakeLark:
    def __init__(self, card=None, msg_results=None):
        self.cardkit = _FakeCardkit(card or _FakeCardService())
        self.im = type(
            "Im",
            (),
            {
                "v1": type(
                    "V1", (), {"message": _FakeMessageService(msg_results)}  # type: ignore[arg-type]
                )()
            },
        )()


def _card(lark=None):
    return StreamingCard(lark or _FakeLark())


# ── _card_json 纯函数 ──


def test_card_json_streaming_structure():
    """用例 1a：streaming=True → schema 2.0 + streaming_mode + markdown placeholder."""
    data = _card_json("⏳ 处理中...", streaming=True, summary="[生成中...]")
    card = json.loads(data)
    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    assert card["config"]["summary"] == "[生成中...]"
    assert "streaming_config" in card["config"]
    assert card["body"]["elements"][0] == {"tag": "markdown", "content": "⏳ 处理中..."}


def test_card_json_final_structure():
    """用例 1b：streaming=False → 无 streaming_mode（定稿态）."""
    data = _card_json("✅ 处理完成", streaming=False, summary="[处理完成]")
    card = json.loads(data)
    assert "streaming_mode" not in card["config"]
    assert card["config"]["summary"] == "[处理完成]"
    assert card["body"]["elements"][0]["content"] == "✅ 处理完成"


# ── 生命周期 ──


def test_create_success():
    """用例 2：create 成功 → card_id 落位 + active=True."""
    card = _card()
    assert card.create() is True
    assert card.active is True
    assert card._card_id == "om_card_1"
    req = card._cardkit().create_calls[0]
    assert req.request_body.type == "card"
    assert "streaming_mode" in req.request_body.data


def test_create_fail_broken():
    """用例 3：create 失败（非限流）→ 返回 False + 熔断（active=False）."""
    fake = _FakeLark(card=_FakeCardService(create_results=[_FakeResp(code=230001, msg="bad")]))
    card = StreamingCard(fake)
    assert card.create() is False
    assert card.active is False
    assert card._broken is True


def test_create_token_invalid_retry():
    """用例 4：create token 失效（99991663）→ 重试一次成功（create 调用数 = 2）."""
    fake = _FakeLark(
        card=_FakeCardService(
            create_results=[
                _FakeResp(code=99991663, msg="expired", raw_status=401),
                _create_resp(),
            ]
        )
    )
    card = StreamingCard(fake)
    assert card.create() is True
    assert len(fake.cardkit.v1.card.create_calls) == 2


def test_create_rate_limit_silent():
    """用例 5：create 限流（429）→ 返回 False + 熔断（限流日志 info 不异常）."""
    fake = _FakeLark(card=_FakeCardService(create_results=[_FakeResp(code=429)]))
    card = StreamingCard(fake)
    assert card.create() is False
    assert card.active is False


def test_bind_success():
    """用例 6：bind → interactive 消息发到会话（receive_id/type 正确 + content 含 card_id）."""
    fake = _FakeLark()
    card = StreamingCard(fake)
    assert card.create() is True
    assert card.bind("oc_chat_1", "chat_id") is True
    req = fake.im.v1.message.create_calls[0]
    assert req.receive_id_type == "chat_id"
    assert req.request_body.receive_id == "oc_chat_1"
    assert req.request_body.msg_type == "interactive"
    content = json.loads(req.request_body.content)
    assert content == {"type": "card", "data": {"card_id": "om_card_1"}}


def test_bind_without_create_false():
    """用例 7：未 create 就 bind → False（active=False 守卫）."""
    card = _card()
    assert card.bind("oc_1", "chat_id") is False


def test_bind_fail_broken():
    """用例 8：bind 失败 → False + 熔断."""
    fake = _FakeLark(
        msg_results=[_FakeResp(code=230001, msg="invalid receive_id")],
        card=_FakeCardService(),
    )
    card = StreamingCard(fake)
    assert card.create() is True
    assert card.bind("oc_1", "chat_id") is False
    assert card.active is False


def test_close_finalizes():
    """用例 9：close → update 完成态 + settings 关 streaming_mode（定稿）."""
    fake = _FakeLark()
    card = StreamingCard(fake)
    assert card.create() is True
    assert card.bind("oc_1", "chat_id") is True
    assert card.close() is True
    # update 调用：内容为完成态 + 无 streaming_mode
    up = fake.cardkit.v1.card.update_calls[0]
    up_card = json.loads(up.request_body.card.data)
    assert up_card["body"]["elements"][0]["content"] == "✅ 处理完成"
    assert "streaming_mode" not in up_card["config"]
    # settings 调用：streaming_mode=False
    st = fake.cardkit.v1.card.settings_calls[0]
    settings = json.loads(st.request_body.settings)
    assert settings["config"]["streaming_mode"] is False
    assert settings["config"]["summary"] == "[处理完成]"
    # 生命周期结束 → 后续操作被拒
    assert card.active is False


def test_close_without_create_false():
    """用例 10：未 create 就 close → False."""
    card = _card()
    assert card.close() is False


def test_close_card_with_summary():
    """P2-2: close(content=摘要) 更新内容含摘要、summary 截断 ≤50 字符；无参 close 行为不变."""
    fake = _FakeLark()
    card = StreamingCard(fake)
    assert card.create() is True
    assert card.bind("oc_1", "chat_id") is True
    summary = "第一行摘要" + "长" * 60  # 首行超 50 字符，验证截断
    assert card.close(content=summary) is True
    up = fake.cardkit.v1.card.update_calls[0]
    up_card = json.loads(up.request_body.card.data)
    assert up_card["body"]["elements"][0]["content"] == summary
    assert len(up_card["config"]["summary"]) <= 50
    assert up_card["config"]["summary"].startswith("第一行摘要")
    # 无参 close（content=None）→ 内容回退 ✅ 处理完成（零回归）
    fake2 = _FakeLark()
    card2 = StreamingCard(fake2)
    assert card2.create() is True
    assert card2.bind("oc_1", "chat_id") is True
    assert card2.close() is True
    up2 = json.loads(fake2.cardkit.v1.card.update_calls[0].request_body.card.data)
    assert up2["body"]["elements"][0]["content"] == "✅ 处理完成"


def test_close_settings_fail_still_returns():
    """用例 11：close 中 settings 失败 → 返回 False（不抛异常，回退分段）."""
    fake = _FakeLark(
        card=_FakeCardService(settings_results=[_FakeResp(code=230001, msg="settings fail")])
    )
    card = StreamingCard(fake)
    assert card.create() is True
    assert card.bind("oc_1", "chat_id") is True
    assert card.close() is False  # update 成功 + settings 失败 → False


def test_close_update_fail_false():
    """用例 12：close 中 update 失败 → False."""
    fake = _FakeLark(
        card=_FakeCardService(update_results=[_FakeResp(code=230001, msg="update fail")])
    )
    card = StreamingCard(fake)
    assert card.create() is True
    assert card.bind("oc_1", "chat_id") is True
    assert card.close() is False


def test_cardkit_none_fail_open():
    """用例 13：lark client 无 cardkit 服务 → create False（熔断不抛异常）."""
    fake = _FakeLark(card=None)
    fake.cardkit = None
    card = StreamingCard(fake)
    assert card.create() is False
    assert card.active is False


def test_placeholder_custom():
    """用例 14：自定义 placeholder/done_text 生效."""
    fake = _FakeLark()
    card = StreamingCard(fake, placeholder="🤖 思考中...", done_text="🎉 完成")
    assert card.create() is True
    assert "🤖 思考中..." in fake.cardkit.v1.card.create_calls[0].request_body.data
    assert card.bind("oc_1", "chat_id") is True
    assert card.close() is True
    up_card = json.loads(fake.cardkit.v1.card.update_calls[0].request_body.card.data)
    assert up_card["body"]["elements"][0]["content"] == "🎉 完成"


# ── H-UI: update 实时更新（动作状态条）──


def _mk_card(fake_service):
    from lark_oapi import Client

    client = Client.builder().build()
    client.cardkit = type("C", (), {"v1": type("V", (), {"card": fake_service})()})()
    card = StreamingCard(client)
    assert card.create() is True
    return card, fake_service


def test_update_live_content():
    """update 实时更新内容（思考/工具动作状态条）."""
    svc = _FakeCardService()
    card, svc = _mk_card(svc)
    assert card.update("🔧 正在调用 read_file（a.txt）") is True
    assert len(svc.update_calls) == 1
    body = svc.update_calls[0].request_body
    assert "🔧 正在调用 read_file" in body.card.data
    assert card.update("💭 思考中…") is True
    assert len(svc.update_calls) == 2


def test_update_before_create_returns_false():
    """未建卡 update → False（fail-open）."""
    from lark_oapi import Client

    client = Client.builder().build()
    card = StreamingCard(client)
    assert card.update("x") is False


def test_update_after_close_returns_false():
    """定稿后 update → False（生命周期结束）."""
    svc = _FakeCardService()
    card, svc = _mk_card(svc)
    assert card.close() is True
    assert card.update("再更新") is False


def test_update_rate_limited_silent():
    """429 限流 → update 返回 False 静默（不抛）."""
    from llm_loop.feishu.streaming_card import _RATE_LIMIT_CODES

    rate_code = next(iter(_RATE_LIMIT_CODES)) if _RATE_LIMIT_CODES else 429
    svc = _FakeCardService(update_results=[_FakeResp(code=rate_code, msg="rate limited")])
    card, svc = _mk_card(svc)
    assert card.update("🔧 工具调用") is False
    assert not card._broken  # 限流不熔断
