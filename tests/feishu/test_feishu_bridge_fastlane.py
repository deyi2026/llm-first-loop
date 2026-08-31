"""控制指令快车道单元测试（T7，tasks 4.4）：长 run 占用 worker 期间 /stop 即时受理."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.feishu.bridge import FeishuWsBridge, _WsConnector
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap
from llm_loop.llm.client import LLMResponse


def _payload(text: str, chat_id: str, event_id: str, message_id: str) -> dict:
    return {
        "schema": "2.0",
        "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_u"}, "sender_type": "user"},
            "message": {
                "message_id": message_id,
                "message_type": "text",
                "chat_id": chat_id,
                "chat_type": "group",
                "content": json.dumps({"text": text}),
            },
        },
    }


def test_stop_fastlane_bypasses_busy_worker(build_test_engine, tmp_path):
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), handler)
    connector = _WsConnector(bridge.config, bridge._on_ws_message, lambda: True)
    sid = session_map.get_or_create(SessionMap.group_key("oc_busy"))

    llm_started = threading.Event()
    run_result: dict[str, Any] = {}

    def _slow_llm(calls):
        llm_started.set()
        deadline = time.monotonic() + 5.0
        while not runner.is_cancelled(sid):
            if time.monotonic() > deadline:
                raise AssertionError("快车道 /stop 未在期限内置位取消标记")
            time.sleep(0.01)
        return LLMResponse(content="收口中", tool_calls=[], provider="fake")

    fake._responses = [_slow_llm]

    def _long_run():
        run_result["result"] = engine.run(sid, "长任务")

    worker_t = threading.Thread(target=_long_run, daemon=True)
    worker_t.start()
    assert llm_started.wait(3.0), "长任务 LLM 应已启动（worker 线程被占用）"

    # worker 未启动消费 → 队列消息滞留（模拟 worker 忙）；预塞一条普通消息占位
    connector._submit_message(_payload("排队中的普通消息", "oc_busy", "evt_q0", "om_q0"))
    queue_before = connector._msg_queue.qsize()

    ok = connector._submit_message(_payload("/stop", "oc_busy", "evt_stop", "om_stop"))
    assert ok is True
    time.sleep(0.2)
    assert connector._msg_queue.qsize() == queue_before  # /stop 未入队（旁路接管）
    assert any("停止已受理" in r[1] for r in replies)  # 受理回执即时发出

    worker_t.join(timeout=5.0)
    assert not worker_t.is_alive()
    result = run_result["result"]
    assert result.final_answer.startswith("（已停止")
    assert result.cancel_reason == "user_stop"

    # 普通消息仍照常入队（零回归）
    assert connector._submit_message(_payload("普通消息", "oc_busy", "evt_n1", "om_n1")) is True
    assert connector._msg_queue.qsize() == queue_before + 1


def test_post_type_control_text_not_fastlaned(build_test_engine, tmp_path):
    """非 text 类型零开销直通（快车道仅预判 msg_type==text）."""
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), handler)
    connector = _WsConnector(bridge.config, bridge._on_ws_message, lambda: True)

    payload = _payload("/stop", "oc_busy", "evt_p1", "om_p1")
    payload["event"]["message"]["message_type"] = "post"
    ok = connector._submit_message(payload)
    assert ok is True
    assert connector._msg_queue.qsize() == 1  # post 类型照常入队（不走快车道）


def test_continue_is_not_fastlaned(build_test_engine, tmp_path):
    """/continue 是新的 user turn：必须进单 worker 队列，旁路线程不得直接跑 engine.run。"""
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), handler)
    connector = _WsConnector(bridge.config, bridge._on_ws_message, lambda: True)

    assert connector._submit_message(_payload("/continue", "oc_busy", "evt_c1", "om_c1")) is True
    assert connector._msg_queue.qsize() == 1
    assert replies == []  # worker 未启动，证明没有 fast-lane 旁路处理
    assert len(fake.calls) == 0
