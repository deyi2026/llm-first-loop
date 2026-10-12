"""中断补偿兼容三态单元测试（T8，tasks 4.4；4.3 defect 回归）.

user_stop 待收口窗口内优雅退出 → 跳过补偿落盘；窗口外退出 → 补偿行为不变；
handler 为 stub 无查询方法 → 行为与现状一致（getattr fail-open）。
补偿记录存储采用 JSONL（CompensationStore，替代旧单文件）。
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from llm_loop.feishu.bridge import FeishuWsBridge, _WsConnector
from llm_loop.feishu.compensation import CompensationStore
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap


def _make(tmp_path, build_test_engine=None):
    handler: Any
    if build_test_engine is not None:
        engine, _fake = build_test_engine([{"content": "ok"}])
        session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
        handler = FeishuMessageHandler(
            engine,
            session_map,
            lambda rid, text, rtype: None,
            audit_dir=str(tmp_path / "audit"),
        )
    else:
        handler = SimpleNamespace()  # stub：无 is_user_stop_pending（旧实例/测试桩）
    bridge = FeishuWsBridge(FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), handler)
    bridge._compensation_store = CompensationStore(str(tmp_path / "feishu_compensation.jsonl"))
    connector = _WsConnector(bridge.config, bridge._on_ws_message, lambda: True)
    bridge._connector = connector
    connector._processing_msg_id = "om_busy"
    connector._processing_reply_id = "oc_busy"
    connector._processing_reply_type = "chat_id"
    connector._processing_chat_id = "oc_busy"
    return bridge, connector, handler


def _compensation_path(tmp_path) -> Path:
    return tmp_path / "feishu_compensation.jsonl"


def test_user_stop_window_skips_persist(build_test_engine, tmp_path, monkeypatch):
    bridge, connector, handler = _make(tmp_path, build_test_engine)
    msg = FeishuMessage(
        message_id="om_stop_1", sender_id="ou_u", chat_id="oc_busy", msg_type="text", text="/stop"
    )
    handler._user_stop_register("sid_busy", msg)  # /stop 受理（窗口内）

    bridge._persist_interrupted()

    assert not _compensation_path(tmp_path).exists()  # 跳过补偿落盘（无重复补偿）


def test_outside_window_persists_as_before(build_test_engine, tmp_path, monkeypatch):
    bridge, connector, handler = _make(tmp_path, build_test_engine)
    msg = FeishuMessage(
        message_id="om_stop_2", sender_id="ou_u", chat_id="oc_busy", msg_type="text", text="/stop"
    )
    handler._user_stop_register("sid_busy", msg)
    stale = next(iter(k for k in handler._user_stop_pending if k == "oc_busy"))
    handler._user_stop_pending[stale] = time.time() - 121.0  # 超时间窗（收口早应完成）

    bridge._persist_interrupted()

    assert _compensation_path(tmp_path).exists()  # 窗口外 → 既有补偿行为不变


def test_stub_handler_without_query_behaves_as_before(tmp_path, monkeypatch):
    bridge, connector, handler = _make(tmp_path)  # SimpleNamespace stub

    bridge._persist_interrupted()

    assert _compensation_path(tmp_path).exists()  # 无查询方法 → 现状行为（fail-open）


def test_no_processing_message_no_persist(build_test_engine, tmp_path, monkeypatch):
    bridge, connector, handler = _make(tmp_path, build_test_engine)
    connector._processing_msg_id = ""  # 无处理中消息 → 正常退出

    bridge._persist_interrupted()

    assert not _compensation_path(tmp_path).exists()


def test_user_stop_clear_after_close_reply(build_test_engine, tmp_path, monkeypatch):
    """收口回复后登记清除 → 后续退出补偿语义恢复."""
    bridge, connector, handler = _make(tmp_path, build_test_engine)
    msg = FeishuMessage(
        message_id="om_stop_3", sender_id="ou_u", chat_id="oc_busy", msg_type="text", text="/stop"
    )
    handler._user_stop_register("sid_busy", msg)
    handler._user_stop_clear("sid_busy", msg)  # 收口回复已发出

    bridge._persist_interrupted()

    assert _compensation_path(tmp_path).exists()  # 登记已清 → 补偿恢复现状
