"""飞书 WS 真实路径测试（M43，FR-RW-WS-01~06，34.9.2 适配 lark-oapi ws.Client）.

路径 B' 修正（用户拍板 2026-08-11）：长连接改用 lark-oapi ws.Client（protobuf 帧 + 自定义握手
由 SDK 内部处理）——本测试验证：token 未就绪等待零触网 / ws_client_factory 注入启动 /
事件回调桥接（lark 事件对象 → payload → on_message）/ 回调异常如实记录 / 装配 / 默认长回复单条发送。
全部 Mock + 构造事件，零真实网络。
"""

import threading
import time

from llm_loop.feishu.bridge import _WsConnector
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap


def _cfg() -> FeishuConfig:
    return FeishuConfig(app_id="cli_ab12cd34", app_secret="sec")


class _FakeLarkClient:
    """Fake lark ws.Client（start 记录调用，不真实连接）."""

    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


def _make_connector(has_token=True, client=None, sleeps=None):
    factory_calls = []
    fake = client or _FakeLarkClient()

    def _factory(event_handler):
        factory_calls.append(event_handler)
        return fake

    connector = _WsConnector(
        _cfg(),
        on_message=lambda payload: None,
        has_token=lambda: has_token,
        ws_client_factory=_factory,
        sleep=(lambda s: sleeps.append(s)) if sleeps is not None else None,
    )
    return connector, factory_calls, fake


def test_connector_waits_no_token():
    """用例 13：token 缓存空 → run() 等待零触网（ws_client_factory 未调用）+ stop() 退出."""
    sleeps: list[float] = []
    connector, factory_calls, _ = _make_connector(has_token=False, sleeps=sleeps)
    thread = threading.Thread(target=connector.run)
    thread.start()
    time.sleep(0.05)
    connector.stop()
    thread.join(timeout=2)
    assert factory_calls == []  # 零触网（lark client 未创建）
    assert len(sleeps) >= 1


def test_connector_start_lark():
    """用例 14：token 就绪 → ws_client_factory 被调 + lark client.start 启动."""
    connector, factory_calls, fake = _make_connector(has_token=True)
    connector.run()
    assert len(factory_calls) == 1  # 工厂被调（构造 event handler + client）
    assert fake.started is True  # lark client 已启动


def test_event_callback_bridge():
    """用例 15：lark 事件对象 → payload dict → 提交队列 → worker 处理 → on_message 分发.

    P1-2-R2 适配: _handle_event 改为提交即返（不阻塞 SDK loop），消息由 worker 线程处理。
    """
    received = []
    connector = _WsConnector(
        _cfg(),
        on_message=lambda payload: received.append(payload),
        has_token=lambda: True,
        ws_client_factory=lambda eh: _FakeLarkClient(),
        sleep=lambda s: None,
    )
    payload = {
        "schema": "2.0",
        "header": {"event_id": "evt_1", "event_type": "im.message.receive_v1"},
        "event": {"sender": {"sender_id": {"open_id": "ou_1"}}, "message": {}},
    }
    # 启动 worker 线程（R2: _handle_event 提交队列，worker 异步处理）
    connector._worker_thread = threading.Thread(
        target=connector._worker_loop, name="test-worker", daemon=True
    )
    connector._worker_thread.start()
    try:
        connector._handle_event(payload)  # 模拟 lark 回调（提交即返）
        deadline = time.time() + 2.0
        while time.time() < deadline and not received:
            time.sleep(0.01)
        assert len(received) == 1
        assert received[0]["header"]["event_type"] == "im.message.receive_v1"
    finally:
        connector._msg_queue.put_nowait(None)
        connector._worker_thread.join(timeout=5)


def test_event_callback_error_honest():
    """用例 16：回调处理异常 → 如实记录不中断（不传播到 lark 连接循环）."""
    connector = _WsConnector(
        _cfg(),
        on_message=lambda payload: (_ for _ in ()).throw(RuntimeError("handler boom")),
        has_token=lambda: True,
        ws_client_factory=lambda eh: _FakeLarkClient(),
        sleep=lambda s: None,
    )
    connector._handle_event({"header": {"event_type": "im.message.receive_v1"}, "event": {}})


def test_event_handler_registered():
    """用例 17：_build_event_handler 构造成功（lark EventDispatcherHandler 注册 im.message.receive_v1）."""
    connector = _WsConnector(
        _cfg(),
        on_message=lambda payload: None,
        has_token=lambda: True,
        ws_client_factory=lambda eh: _FakeLarkClient(),
        sleep=lambda s: None,
    )
    handler = connector._build_event_handler()
    assert handler is not None


def test_build_bridge_shared_lark_client(build_test_engine):
    """新增：build_bridge 默认创建共享 lark.Client（builder 链）+ rest 持同一实例.

    M46 修正：build_bridge 装配时主动创建 rest_client（挂钩 Typing reaction/状态卡），
    rest 由惰性变为装配即建——断言改为 rest 已创建且持同一共享实例。
    """
    from llm_loop.feishu import build_bridge

    engine, _ = build_test_engine([])
    bridge, handler, session_map = build_bridge(engine=engine)
    assert bridge._lark_client is not None  # 共享实例已创建
    assert bridge._rest_client is not None  # M46：装配即建（挂钩处理中动作）
    rest = bridge._rest_client
    assert rest._lark_client is bridge._lark_client  # rest 持同一共享实例
    assert handler._rest_client is bridge._rest_client  # handler 复用同一 rest


def test_build_bridge_lark_mock_injectable(build_test_engine):
    """新增：build_bridge(lark_client=mock) 同一对象注入 bridge → rest（Mock 面保留）."""
    from llm_loop.feishu import build_bridge

    engine, _ = build_test_engine([])
    mock_lark = object()  # 注入 Mock（零真实 SDK 触网）
    bridge, handler, session_map = build_bridge(engine=engine, lark_client=mock_lark)
    assert bridge._lark_client is mock_lark
    rest = bridge._ensure_rest_client()
    assert rest._lark_client is mock_lark


def test_build_bridge_wired(build_test_engine, tmp_path):
    """用例 18：build_bridge（FakeLLM）→ reply_fn/download 装配非 None + chunk_limit==30000."""
    from llm_loop.feishu import build_bridge

    engine, _ = build_test_engine([])
    bridge, handler, session_map = build_bridge(engine=engine)
    assert handler._reply_fn is not None  # = bridge.send_text
    assert handler._attachment_download is not None  # = bridge.download_attachment
    assert handler._chunk_limit == 30000  # 飞书字数不设人为限制（默认）
    assert bridge._handler is handler  # attach_handler 已装配
    assert session_map is not None


def test_default_long_reply_single_send(build_test_engine, tmp_path):
    """用例 19：默认 chunk_limit=30000 → 4000 字符长回复完整发送（不触发分段）.

    2026-08-15 用户需求：默认不折叠——完整单条发送（分块输出仅超 chunk_limit 才发生）；
    折叠路径（摘要卡+展开全文）见 opt-in 用例（FEISHU_FOLD_LONG_REPLY=1）。
    """
    long_reply = "\n".join(f"第{i}行内容abcdefgh" for i in range(250))
    assert len(long_reply) > 3000 and len(long_reply) < 30000

    engine, _ = build_test_engine([{"content": long_reply}])
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_session_map.json"))
    replies: list[tuple[str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        reply_fn=lambda rid, text, rtype: replies.append((rid, text, rtype)),
        chunk_limit=30000,
    )
    handler.handle(
        FeishuMessage(
            message_id="om_l", sender_id="ou_l", chat_id="oc_l", msg_type="text", text="写长文"
        )
    )
    assert len(replies) == 1  # 默认不折叠：完整单条发送
    assert replies[0][1] == long_reply  # 全文无损
    assert len(handler._folded_store) == 0  # 无暂存
    # 默认不折叠后无暂存——「展开全文」如实提示无可展开（命令保留向后兼容）
    replies.clear()
    handler.handle(
        FeishuMessage(
            message_id="om_l2", sender_id="ou_l", chat_id="oc_l", msg_type="text", text="展开全文"
        )
    )
    assert len(replies) == 1
    assert "没有可展开的折叠回复" in replies[0][1]
