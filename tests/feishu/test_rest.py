"""飞书 REST 面与 token 探针测试（M44 SDK 化，FR-SDK-TKN/SND/DLD 系列）.

token 探针语义（置 _token_ready 不缓存值）/ 自实现面移除断言 /
发送 lark.im.v1.message.create Mock / 下载 message_resource.get Mock（BytesIO→bytes）/
SDK 401 重试 / 日志脱敏。全部 lark.Client Mock 注入，零真实网络（无 real_llm 标记）。
"""

import io
import json

import pytest

from llm_loop.feishu.bridge import _TOKEN_URL, FeishuWsBridge
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.rest import FeishuRestClient, FeishuRestError


class _FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


def _cfg() -> FeishuConfig:
    return FeishuConfig(app_id="cli_ab12cd34", app_secret="sec")


# ── SDK 响应 Mock ──
class _FakeCreateResp:
    def __init__(self, code=0, msg="", message_id="om_123", raw_status=200):
        self.code = code
        self.msg = msg
        self.data = type("D", (), {"message_id": message_id})() if code == 0 else None
        self.raw = type("R", (), {"status_code": raw_status})()


class _FakeGetResp:
    def __init__(self, code=0, msg="", file_bytes=b"data", raw_status=200):
        self.code = code
        self.msg = msg
        self.file = io.BytesIO(file_bytes) if code == 0 else None
        self.raw = type("R", (), {"status_code": raw_status})()


class _FakeMessageService:
    def __init__(self, results=None):
        self.create_calls: list = []
        self._results = list(results or [])

    def create(self, request):
        self.create_calls.append(request)
        if self._results:
            return self._results.pop(0)
        return _FakeCreateResp()


class _FakeMessageResourceService:
    def __init__(self, results=None):
        self.get_calls: list = []
        self._results = list(results or [])

    def get(self, request):
        self.get_calls.append(request)
        if self._results:
            return self._results.pop(0)
        return _FakeGetResp()


class _FakeLark:
    def __init__(self, create_results=None, get_results=None):
        self.im = type(
            "Im",
            (),
            {
                "v1": type(
                    "V1",
                    (),
                    {
                        "message": _FakeMessageService(create_results),
                        "message_resource": _FakeMessageResourceService(get_results),
                    },
                )()
            },
        )()


def _rest(fake_lark=None):
    return FeishuRestClient(_cfg(), fake_lark or _FakeLark())


def _bridge(monkeypatch, token_data=None):
    bridge = FeishuWsBridge(_cfg(), None)
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if token_data is None:
            return _FakeResp({"code": 0, "tenant_access_token": "t_abc", "expire": 7200})
        return _FakeResp(token_data)

    monkeypatch.setattr("llm_loop.feishu.bridge.httpx.post", fake_post)
    return bridge, calls


# ── token 探针语义（FR-SDK-TKN-01~04，归桥）──


def test_token_probe_success_flag(monkeypatch):
    """用例 1：探针成功 → 返回 None + _token_ready 置位 + 不缓存 token 值."""
    bridge, calls = _bridge(monkeypatch)
    assert bridge._token_probe() is None
    assert bridge._token_ready is True
    assert not hasattr(bridge, "_token")  # 自实现 token 缓存已移除（token 值零接触）
    url, kwargs = calls[0]
    assert url == _TOKEN_URL
    assert kwargs["json"] == {"app_id": "cli_ab12cd34", "app_secret": "sec"}


def test_token_probe_no_cache():
    """用例 2：探针不缓存 token 值（无 _token/_get_token/_invalidate_token 面）."""
    bridge = FeishuWsBridge(_cfg(), None)
    assert not hasattr(bridge, "_token")
    assert not hasattr(bridge, "_get_token")
    assert not hasattr(bridge, "_invalidate_token")
    assert not hasattr(bridge, "_token_expire_at")
    assert bridge._has_token() is False  # 初始未置位


def test_token_ready_stop_reset(monkeypatch):
    """用例 3：探针置位后 stop() → _token_ready 复位 False."""
    bridge, _ = _bridge(monkeypatch)
    bridge._token_probe()
    assert bridge._token_ready is True
    bridge.stop()
    assert bridge._token_ready is False


def test_token_probe_credential_fail(monkeypatch):
    """用例 4：凭证错误 → 返回含 code/msg 原因 + _token_ready 保持 False."""
    bridge, _ = _bridge(monkeypatch, token_data={"code": 99991663, "msg": "invalid secret"})
    reason = bridge._token_probe()
    assert reason is not None
    assert "99991663" in reason
    assert bridge._token_ready is False


def test_token_probe_network_fail(monkeypatch):
    """用例 5：网络不可达 → 返回 None（不阻断启动）+ _token_ready 保持 False."""
    bridge, _ = _bridge(monkeypatch)

    def _boom(url, **kwargs):
        raise OSError("no route")

    monkeypatch.setattr("llm_loop.feishu.bridge.httpx.post", _boom)
    assert bridge._token_probe() is None
    assert bridge._token_ready is False


# ── endpoint 移除裁决（FR-SDK-EP-01）──


def test_endpoint_removed():
    """用例 6-7：get_endpoint/_ENDPOINT_URL 已移除（lark ws.Client 内部处理）."""
    rest = _rest()
    assert not hasattr(rest, "get_endpoint")
    import llm_loop.feishu.rest as rest_module

    assert not hasattr(rest_module, "_ENDPOINT_URL")


# ── 发送 SDK 化（FR-SDK-SND-01/02/04）──


def test_send_text_sdk_payload():
    """用例 8：interactive 卡片发送 → msg_type="interactive" + content 为 Card 2.0 JSON 结构."""
    fake = _FakeLark(create_results=[_FakeCreateResp(message_id="om_sdk")])
    client = _rest(fake)
    message_id = client.send_text("oc_chat_1", "你好")
    assert message_id == "om_sdk"
    req = fake.im.v1.message.create_calls[0]
    assert req.receive_id_type == "chat_id"
    assert req.request_body.receive_id == "oc_chat_1"
    assert req.request_body.msg_type == "interactive"
    card = json.loads(req.request_body.content)
    assert card["schema"] == "2.0"
    assert card["config"]["width_mode"] == "fill"
    assert card["body"]["elements"][0]["tag"] == "markdown"
    assert card["body"]["elements"][0]["content"] == "你好"


def test_send_text_sdk_401_retry():
    """用例 9：发送 token 失效（code=99991663）→ 重试一次成功（create 调用数 = 2）."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=99991663, msg="token expired", raw_status=401),
            _FakeCreateResp(message_id="om_retry"),
        ]
    )
    client = _rest(fake)
    assert client.send_text("oc_1", "hi") == "om_retry"
    assert len(fake.im.v1.message.create_calls) == 2


def test_send_text_sdk_401_retry_fail_honest():
    """用例 9b：interactive token 失效重试仍失败 → 回退 text → text 也失败 → 如实抛（两段失败）."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=99991663, msg="expired", raw_status=401),
            _FakeCreateResp(code=99991663, msg="expired", raw_status=401),
            _FakeCreateResp(code=99991663, msg="expired", raw_status=401),
            _FakeCreateResp(code=99991663, msg="expired", raw_status=401),
        ]
    )
    client = _rest(fake)
    with pytest.raises(FeishuRestError) as exc:
        client.send_text("oc_1", "hi")
    assert "99991663" in str(exc.value)
    assert "text 回退失败" in str(exc.value)


def test_send_text_sdk_error_honest():
    """用例 8b：interactive 失败（非失效 code）→ 回退 text → text 也失败 → 如实抛（两段失败）."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=230001, msg="invalid receive_id"),
            _FakeCreateResp(code=230001, msg="invalid receive_id"),
        ]
    )
    client = _rest(fake)
    with pytest.raises(FeishuRestError) as exc:
        client.send_text("oc_1", "hi")
    assert "230001" in str(exc.value)
    assert "invalid receive_id" in str(exc.value)
    assert "text 回退失败" in str(exc.value)


# ── 下载 SDK 化（FR-SDK-DLD-01/03）──


def test_download_sdk_bytes():
    """用例 10：message_resource.get Mock → GetMessageResourceRequest 参数 + BytesIO → bytes."""
    fake = _FakeLark(get_results=[_FakeGetResp(file_bytes=b"\x89PNG-data")])
    client = _rest(fake)
    data = client.download_resource("om_1", "fk_1", "image")
    assert data == b"\x89PNG-data"
    req = fake.im.v1.message_resource.get_calls[0]
    assert req.type == "image"
    assert req.message_id == "om_1"
    assert req.file_key == "fk_1"


def test_download_sdk_401_retry():
    """用例 11：下载 token 失效 → 重试一次成功（get 调用数 = 2）."""
    fake = _FakeLark(
        get_results=[
            _FakeGetResp(code=99991663, msg="expired", raw_status=401),
            _FakeGetResp(file_bytes=b"data"),
        ]
    )
    client = _rest(fake)
    assert client.download_resource("om_1", "fk_1", "file") == b"data"
    assert len(fake.im.v1.message_resource.get_calls) == 2


def test_download_sdk_fail_honest():
    """用例 11b：下载失败（非 token 失效码）→ 直接如实抛 FeishuRestError（含 code/msg）."""
    fake = _FakeLark(get_results=[_FakeGetResp(code=230001, msg="resource not found")])
    client = _rest(fake)
    with pytest.raises(FeishuRestError) as exc:
        client.download_resource("om_1", "fk_1", "file")
    assert "230001" in str(exc.value)
    assert "resource not found" in str(exc.value)


# ── 日志脱敏（FR-SDK-TKN-03）──


def test_sdk_no_token_leak_log(caplog):
    """用例 12：SDK 调用面日志不含 token/secret 值（token 值零接触）."""
    fake = _FakeLark(create_results=[_FakeCreateResp(code=230001, msg="invalid receive_id")])
    client = _rest(fake)
    from contextlib import suppress

    with suppress(FeishuRestError):
        client.send_text("oc_1", "hi")
    assert "t_abc" not in caplog.text
    assert "sec" not in caplog.text


# ── M45 新增：interactive 卡片 / 回退链 / 表格兜底 / 审计（FR-FMD-*）──


def test_interactive_card_content_truthful():
    """用例 ②：卡片内容如实（含"（回答被截断）"标注原文完整透传）."""
    fake = _FakeLark(create_results=[_FakeCreateResp(message_id="om_t")])
    client = _rest(fake)
    text = "回答内容（回答被截断）"
    client.send_text("oc_1", text)
    card = json.loads(fake.im.v1.message.create_calls[0].request_body.content)
    assert card["body"]["elements"][0]["content"] == text  # 原文完整透传不截断


def test_interactive_fail_fallback_text_success(caplog):
    """用例 ③：interactive 失败 → 如实回退 text 同一内容 → 成功返回 message_id."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=230001, msg="card not supported"),
            _FakeCreateResp(message_id="om_fb"),
        ]
    )
    client = _rest(fake)
    message_id = client.send_text("oc_1", "原文内容")
    assert message_id == "om_fb"
    calls = fake.im.v1.message.create_calls
    assert calls[0].request_body.msg_type == "interactive"
    assert calls[1].request_body.msg_type == "text"  # 回退 text
    assert json.loads(calls[1].request_body.content)["text"] == "原文内容"  # 降级不丢内容


def test_interactive_fail_fallback_text_fail():
    """用例 ④：interactive 失败 + text 回退失败 → 如实抛（含两段失败 code/msg）."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=230001, msg="card fail"),
            _FakeCreateResp(code=230002, msg="text fail"),
        ]
    )
    client = _rest(fake)
    with pytest.raises(FeishuRestError) as exc:
        client.send_text("oc_1", "hi")
    assert "card fail" in str(exc.value)
    assert "text fail" in str(exc.value)


def test_table_overflow_convert_retry():
    """用例 ⑤：表格超限（230099）→ 转 bullets 重发 interactive 成功."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=230099, msg="card table number over limit"),
            _FakeCreateResp(message_id="om_conv"),
        ]
    )
    client = _rest(fake)
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    message_id = client.send_text("oc_1", md)
    assert message_id == "om_conv"
    calls = fake.im.v1.message.create_calls
    assert calls[0].request_body.msg_type == "interactive"
    assert calls[1].request_body.msg_type == "interactive"  # 转换后仍 interactive
    converted_card = json.loads(calls[1].request_body.content)
    assert "- **A | B**" in converted_card["body"]["elements"][0]["content"]  # 表格已转 bullets（表头加粗）
    assert "  - A: 1；B: 2" in converted_card["body"]["elements"][0]["content"]  # 数据行列名映射


def test_table_overflow_convert_fail_fallback():
    """用例 ⑥：转换后重试失败 → 回退 text（转换后内容）."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=230099, msg="table overflow"),
            _FakeCreateResp(code=230001, msg="still fail"),
            _FakeCreateResp(message_id="om_final"),
        ]
    )
    client = _rest(fake)
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    assert client.send_text("oc_1", md) == "om_final"
    calls = fake.im.v1.message.create_calls
    assert calls[2].request_body.msg_type == "text"  # 转换后 interactive 失败 → 回退 text
    assert "**A | B**" in json.loads(calls[2].request_body.content)["text"]  # 回退转换后内容


def test_token_invalid_retry_interactive():
    """用例 ⑦：interactive 层 token 失效 → 重试一次成功（create 调用数 = 2）."""
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=99991663, msg="expired", raw_status=401),
            _FakeCreateResp(message_id="om_ok"),
        ]
    )
    client = _rest(fake)
    assert client.send_text("oc_1", "hi") == "om_ok"
    assert len(fake.im.v1.message.create_calls) == 2


def test_audit_fallback_written(tmp_path):
    """用例 ⑩：回退路径发送审计落盘（feishu_audit.jsonl 追加 send_type/fallback/code/脱敏 id）."""
    audit_path = tmp_path / "audit" / "feishu_audit.jsonl"
    fake = _FakeLark(
        create_results=[
            _FakeCreateResp(code=230001, msg="card fail"),
            _FakeCreateResp(message_id="om_fb"),
        ]
    )
    client = _rest(fake)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    client._audit_path = audit_path
    client.send_text("oc_secret_id", "hi")
    content = audit_path.read_text(encoding="utf-8")
    assert '"kind": "send_fallback"' in content
    assert '"send_type": "text"' in content
    assert '"fallback": true' in content
    assert "oc_secre" in content  # 脱敏 id 前 8 字符
    assert "oc_secret_id" not in content  # 完整 id 不外泄


def test_audit_fallback_fail_open(tmp_path, monkeypatch):
    """用例 ⑩b：审计写失败不阻断发送（fail-open）."""
    fake = _FakeLark(create_results=[_FakeCreateResp(message_id="om_ok")])
    client = _rest(fake)
    client._audit_path = tmp_path / "no_dir" / "audit.jsonl"  # 目录不存在 → 写失败
    assert client.send_text("oc_1", "hi") == "om_ok"  # 发送不阻断


def test_chunked_card_per_segment(build_test_engine, tmp_path):
    """用例 ⑫：分段经卡片逐段发送（各段 msg_type="interactive"）."""
    from llm_loop.feishu.bridge import FeishuWsBridge
    from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
    from llm_loop.feishu.session_map import SessionMap

    engine, _ = build_test_engine([{"content": "段1内容\n段2内容\n段3内容"}])
    fake = _FakeLark()
    bridge = FeishuWsBridge(_cfg(), None, lark_client=fake)
    smap = SessionMap(engine.session, path=str(tmp_path / "sm.json"))
    handler = FeishuMessageHandler(
        engine,
        smap,
        reply_fn=bridge.send_text,
        chunk_limit=10,  # 强制分段
    )
    handler.handle(
        FeishuMessage(
            message_id="om_c", sender_id="ou_c", chat_id="oc_c", msg_type="text", text="hi"
        )
    )
    calls = fake.im.v1.message.create_calls
    assert len(calls) >= 2  # 分段逐段发送
    for c in calls:
        assert c.request_body.msg_type == "interactive"  # 各段 interactive 卡片


# ── M46：Typing reaction 回执（FR-TYP-01~04，对齐 本地既有实现 ws_bridge）──


class _FakeReactionService:
    def __init__(self, create_results=None, delete_results=None):
        self.create_calls: list = []
        self.delete_calls: list = []
        self._creates = list(create_results or [])
        self._deletes = list(delete_results or [])

    def create(self, request):
        self.create_calls.append(request)
        if self._creates:
            return self._creates.pop(0)
        return _FakeCreateResp(message_id="")  # reaction 响应字段不同，用专用 resp

    def delete(self, request):
        self.delete_calls.append(request)
        if self._deletes:
            return self._deletes.pop(0)
        return _FakeCreateResp()


class _FakeReactionResp:
    def __init__(self, code=0, msg="", reaction_id="re_123", raw_status=200):
        self.code = code
        self.msg = msg
        self.data = type("D", (), {"reaction_id": reaction_id})() if code == 0 else None
        self.raw = type("R", (), {"status_code": raw_status})()


def _reaction_rest(create_results=None, delete_results=None):
    """构造带 message_reaction mock 的 rest client."""
    reaction = _FakeReactionService(create_results, delete_results)
    fake = type(
        "Im",
        (),
        {
            "v1": type(
                "V1",
                (),
                {
                    "message": _FakeMessageService(),
                    "message_reaction": reaction,
                },
            )()
        },
    )()
    return FeishuRestClient(_cfg(), type("Lark", (), {"im": fake})()), reaction


def test_typing_reaction_add_success():
    """用例 ①：add_typing_reaction → SDK create（emoji_type=Typing）+ 返回 reaction_id."""
    client, reaction = _reaction_rest(
        create_results=[_FakeReactionResp(reaction_id="re_abc")]
    )
    rid = client.add_typing_reaction("om_1")
    assert rid == "re_abc"
    req = reaction.create_calls[0]
    assert req.message_id == "om_1"
    assert req.request_body.reaction_type.emoji_type == "Typing"


def test_typing_reaction_rate_limit_skip():
    """用例 ②：限流码（429）→ 返回空串（静默跳过，不抛异常）."""
    client, _ = _reaction_rest(create_results=[_FakeReactionResp(code=429)])
    assert client.add_typing_reaction("om_1") == ""


def test_typing_reaction_token_invalid_retry():
    """用例 ③：token 失效（99991663）→ 重试一次成功（create 调用数 = 2）."""
    client, reaction = _reaction_rest(
        create_results=[
            _FakeReactionResp(code=99991663, msg="expired", raw_status=401),
            _FakeReactionResp(reaction_id="re_retry"),
        ]
    )
    assert client.add_typing_reaction("om_1") == "re_retry"
    assert len(reaction.create_calls) == 2


def test_typing_reaction_fail_empty():
    """用例 ④：非限流失败 → 返回空串（fail-open 不阻断主流程）."""
    client, _ = _reaction_rest(create_results=[_FakeReactionResp(code=230001, msg="bad")])
    assert client.add_typing_reaction("om_1") == ""


def test_remove_reaction_success():
    """用例 ⑤：remove_reaction → SDK delete（message_id/reaction_id 正确）."""
    client, reaction = _reaction_rest()
    client.remove_reaction("om_1", "re_abc")
    req = reaction.delete_calls[0]
    assert req.message_id == "om_1"
    assert req.reaction_id == "re_abc"


def test_remove_reaction_empty_noop():
    """用例 ⑥：reaction_id 空 → 不调用 SDK（no-op）."""
    client, reaction = _reaction_rest()
    client.remove_reaction("om_1", "")
    assert reaction.delete_calls == []


def test_remove_reaction_fail_silent():
    """用例 ⑦：删除失败（非限流码）→ 不抛异常（best-effort 静默）."""
    client, _ = _reaction_rest(delete_results=[_FakeReactionResp(code=230001, msg="fail")])
    client.remove_reaction("om_1", "re_x")  # 不抛即通过


# ── G3 错误醒目化 ──

def test_send_text_error_highlight():
    """G3: 错误回执发送内容前插 `⚠️ ` + 首行加粗；正常内容零改动."""
    fake = _FakeLark(create_results=[_FakeCreateResp(message_id="om_err")])
    client = _rest(fake)
    client.send_text("oc_1", "[状态: error] 执行失败\n详细信息")
    sent = json.loads(fake.im.v1.message.create_calls[0].request_body.content)
    content = sent["body"]["elements"][0]["content"]
    assert content.startswith("⚠️ **[状态: error] 执行失败**")
    assert "详细信息" in content

    fake2 = _FakeLark(create_results=[_FakeCreateResp(message_id="om_ok")])
    client2 = _rest(fake2)
    client2.send_text("oc_1", "正常内容\n第二行")
    sent2 = json.loads(fake2.im.v1.message.create_calls[0].request_body.content)
    assert sent2["body"]["elements"][0]["content"] == "正常内容\n第二行"  # 正常内容零改动


# ── F8: 发送最小间隔（多段防频率限制）──


def test_send_throttle_waits_min_interval(monkeypatch):
    """连续发送间隔不足 → sleep 补齐最小间隔（0.3s）."""
    from unittest import mock

    from lark_oapi import Client as _LarkClient

    import llm_loop.feishu.rest as rest_mod
    from llm_loop.feishu.rest import FeishuRestClient

    cfg = _cfg()
    client = _LarkClient.builder().build()
    rest_client = FeishuRestClient(cfg, client)
    sleeps: list[float] = []

    def _fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    fake_now = iter([10.0, 10.0, 10.5])  # 第1次发送→立即; 第2次 0.0s 后→sleep 0.3; 第3次 0.5s 后→不 sleep

    import itertools

    def _fake_monotonic() -> float:
        return next(fake_now)

    fake_now = itertools.repeat(10.0)  # 时钟静止：每次调用间隔恒 < 0.3s
    with mock.patch.object(rest_mod.time, "monotonic", _fake_monotonic), mock.patch.object(
        rest_mod.time, "sleep", _fake_sleep
    ):
        rest_client._throttle_send()  # 首次：无上次记录，不 sleep
        rest_client._throttle_send()  # 间隔 0 → sleep 0.3
        rest_client._throttle_send()  # 间隔仍 0 → sleep 0.3
    assert sleeps == [0.3, 0.3]
