from __future__ import annotations

import json
import queue
from types import SimpleNamespace
from unittest.mock import Mock

from llm_loop.feishu.bridge import _WsConnector
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler


def _cfg() -> FeishuConfig:
    return FeishuConfig(app_id="cli_ab12cd34", app_secret="sec", ws_enabled=True)


def _receive(message_id: str) -> dict:
    return {
        "header": {"event_type": "im.message.receive_v1", "event_id": f"evt-{message_id}"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}, "sender_type": "user"},
            "message": {
                "message_id": message_id,
                "chat_id": "oc_chat",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": f"text-{message_id}"}),
            },
        },
    }


def _recall(message_id: str) -> dict:
    return {
        "header": {"event_type": "im.message.recalled_v1", "event_id": f"recall-{message_id}"},
        "event": {
            "message_id": message_id,
            "chat_id": "oc_chat",
            "recall_time": "1789178400000",
            "recall_type": "1",
        },
    }


def test_feishu_recall_physically_removes_not_yet_started_queue_item():
    recalls: list[dict] = []
    connector = _WsConnector(
        config=_cfg(),
        on_message=Mock(),
        has_token=lambda: True,
        on_recall=lambda fact: recalls.append(fact),
    )
    connector._msg_queue = queue.Queue(maxsize=8)
    connector._msg_queue.put_nowait(_receive("om_keep"))
    connector._msg_queue.put_nowait(_receive("om_drop"))

    connector._handle_recall_event(_recall("om_drop"))

    left = list(connector._msg_queue.queue)
    assert [it["event"]["message"]["message_id"] for it in left] == ["om_keep"]
    assert recalls[-1]["message_id"] == "om_drop"
    assert recalls[-1]["queue_removed"] is True
    assert recalls[-1]["session_id_hint"] == ""


def test_feishu_recall_after_worker_claim_becomes_declarative_retraction():
    recalls: list[dict] = []
    connector = _WsConnector(
        config=_cfg(),
        on_message=Mock(),
        has_token=lambda: True,
        on_recall=lambda fact: recalls.append(fact),
        current_sid_fn=lambda: "sid-active",
    )
    connector._processing_msg_id = "om_active"

    connector._handle_recall_event(_recall("om_active"))

    assert recalls[-1]["queue_removed"] is False
    assert recalls[-1]["session_id_hint"] == "sid-active"
    assert recalls[-1]["recall_type"] == "1"


def test_feishu_ingress_persists_source_message_id_as_mechanical_metadata(tmp_path):
    engine = Mock()
    engine.settings = SimpleNamespace(data_dir=str(tmp_path))
    engine.run.return_value = SimpleNamespace(
        final_answer="ok",
        truncated=False,
        verification_note="",
        cancel_reason="",
        fallback_receipt=None,
        model_used="",
        tokens_in=0,
        tokens_out=0,
        tool_calls=[],
    )
    session_map = Mock()
    session_map.get_or_create.return_value = "sid-1"
    replies: list[str] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        reply_fn=lambda _rid, text, _rtype: replies.append(text),
        audit_dir=str(tmp_path / "audit"),
        typing_ack=False,
        streaming=False,
    )
    msg = FeishuMessage(
        message_id="om_ingress",
        sender_id="ou_user",
        chat_id="oc_chat",
        msg_type="text",
        text="hello",
    )

    handler._run_text(msg, "hello")

    metadata = engine.run.call_args.kwargs["user_metadata"]
    assert metadata == {"human_turn_source_id": "feishu:om_ingress"}


def test_handler_recall_delegates_exact_source_id_without_cancelling_run(tmp_path):
    session_store = Mock()
    session_store.retract_message_by_source_id.return_value = {
        "status": "retracted",
        "session_id": "sid-1",
    }
    engine = Mock()
    engine.settings = SimpleNamespace(data_dir=str(tmp_path))
    engine.session = session_store
    engine.runner = Mock()
    handler = FeishuMessageHandler(
        engine,
        Mock(),
        reply_fn=Mock(),
        audit_dir=str(tmp_path / "audit"),
        typing_ack=False,
        streaming=False,
    )

    result = handler.handle_recall(
        {
            "message_id": "om_recalled",
            "chat_id": "oc_chat",
            "recall_time": "1789178400000",
            "recall_type": "1",
            "queue_removed": False,
            "session_id_hint": "sid-1",
        }
    )

    assert result["status"] == "retracted"
    session_store.retract_message_by_source_id.assert_called_once()
    call = session_store.retract_message_by_source_id.call_args
    assert call.args[0] == "feishu:om_recalled"
    assert call.kwargs["session_id_hint"] == "sid-1"
    engine.runner.cancel.assert_not_called()
