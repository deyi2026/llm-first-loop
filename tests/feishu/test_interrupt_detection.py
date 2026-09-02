"""中断检测与提示集成测试（tasks 6.2；FTR-DET-2/3/4、FTR-COMP-2、FTR-DFX-02/03）.

进程内直驱 connector 中断落点（不入队 worker，聚焦 DET/COMP 行为本身）：
- 队列满丢弃：可判定目标 → 「队列忙」提示 + queue_full 补偿；不可判定 → 不伪造目标。
- 处理超时：阈值点「疑似卡住」中间态提示（不打断、不落补偿、防重复）。
- 看门狗自杀前：watchdog_exit 补偿落盘 + 尽力提示（含 context_ref/msg_id）。
- drain 超时：积压消息逐条 drain_timeout 补偿。
- 重启补偿：补偿记录逐条送达 + 幂等（两次启动仅一次送达）。
"""

from __future__ import annotations

import json
import queue
import time
from types import SimpleNamespace

from llm_loop.feishu import bridge as bridge_module
from llm_loop.feishu.bridge import FeishuWsBridge, _WsConnector
from llm_loop.feishu.compensation import (
    CRASH,
    DRAIN_TIMEOUT,
    QUEUE_FULL,
    WATCHDOG_EXIT,
    CompensationStore,
    InterruptionCompensationRecord,
    InterruptionNotifier,
)
from llm_loop.feishu.config import FeishuConfig


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


def _make(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_DEDUP_PATH", str(tmp_path / "feishu_dedup.json"))
    store = CompensationStore(
        tmp_path / "feishu_compensation.jsonl",
        legacy_path=tmp_path / "feishu_interrupted.json",
    )
    sent: list[tuple[str, str, str]] = []

    def _send(rid, text, rtype):
        sent.append((rid, text, rtype))
        return True

    notifier = InterruptionNotifier(_send, store)
    bridge = FeishuWsBridge(
        FeishuConfig(app_id="cli_ab12cd34", app_secret="sec"), SimpleNamespace()
    )
    bridge._compensation_store = store
    bridge._notifier = notifier
    connector = _WsConnector(bridge.config, bridge._on_ws_message, lambda: True)
    bridge._connector = connector
    connector._notifier = notifier
    connector._store = store
    connector._current_sid_fn = lambda: "sid_det"
    return bridge, connector, store, sent


# ── 队列满丢弃（FTR-DET-3、RC-2）──


def test_queue_full_prompts_and_compensates(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    connector._msg_queue = queue.Queue(maxsize=1)
    connector._msg_queue.put({"占位": True})  # 满

    ok = connector._submit_message(_payload("任务 A", "oc_full", "evt_q1", "om_q1"))

    assert ok is False, "队列满应如实返回 False（fail-open 不抛）"
    assert any("队列忙" in t[1] for t in sent), "应回执「消息未进入处理（队列忙）」"
    recs = store.read_all()
    assert len(recs) == 1
    assert recs[0].interrupt_cause == QUEUE_FULL
    assert recs[0].receive_id == "oc_full"
    assert recs[0].msg_id == "om_q1", "补偿记录应携带原始消息 id（可审计）"
    assert recs[0].context_ref == "sid_det", "补偿记录应携带 context_ref"


def test_queue_full_unresolvable_target_no_fake_compensation(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    connector._msg_queue = queue.Queue(maxsize=1)
    connector._msg_queue.put({"占位": True})
    payload = _payload("任务 A", "", "evt_q2", "om_q2")
    payload["event"]["sender"]["sender_id"]["open_id"] = ""  # 双目标皆空 → 不可判定

    ok = connector._submit_message(payload)

    assert ok is False
    assert sent == [] and store.read_all() == [], "目标不可判定 → 不伪造目标会话（FTR-DFX-03）"


# ── 处理超时中间态提示（FTR-DET-4、RC-4：不打断）──


def test_process_timeout_midstate_prompt_only_no_compensation(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    connector._processing_msg_id = "om_slow"
    connector._processing_reply_id = "oc_slow"
    connector._processing_reply_type = "chat_id"
    connector._processing_since = time.time() - (bridge_module._MSG_PROCESS_TIMEOUT_S + 1)

    connector._watchdog_check_process_timeout()

    assert any("疑似卡住" in t[1] for t in sent), "阈值点应发送中间态提示"
    assert any("/continue" in t[1] for t in sent), "提示应含恢复指引"
    assert store.read_all() == [], "中间态不得落补偿（任务未真中断）"
    # 防重复：再次探测不得重发
    connector._watchdog_check_process_timeout()
    assert sum(1 for t in sent if "疑似卡住" in t[1]) == 1
    assert connector._processing_timeout_reported is True


def test_process_timeout_below_threshold_silent(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    connector._processing_msg_id = "om_fast"
    connector._processing_reply_id = "oc_fast"
    connector._processing_since = time.time() - 1.0

    connector._watchdog_check_process_timeout()

    assert sent == [] and store.read_all() == []


# ── 看门狗假死自杀前（FTR-DET-2 / FTR-COMP-2、RC-1）──


def test_watchdog_exit_persists_and_notifies(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    connector._processing_msg_id = "om_w"
    connector._processing_reply_id = "oc_w"
    connector._processing_reply_type = "chat_id"

    connector._interrupt_watchdog_exit()  # 模拟 os._exit(42) 前的最后动作

    assert any("服务将因异常退出" in t[1] and "/continue" in t[1] for t in sent)
    recs = store.read_all()
    assert len(recs) == 1
    assert recs[0].interrupt_cause == WATCHDOG_EXIT
    assert recs[0].msg_id == "om_w"
    assert recs[0].context_ref == "sid_det"


def test_watchdog_exit_no_processing_target_noop(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)

    connector._interrupt_watchdog_exit()

    assert sent == [] and store.read_all() == [], "无处理中消息 → 不落不提示"


# ── drain 超时丢积压（FTR-COMP-2、RC-3）──


def test_drain_backlog_compensates_each_message(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    connector._msg_queue.put(_payload("任务 B", "oc_d1", "evt_d1", "om_d1"))
    connector._msg_queue.put(_payload("任务 C", "oc_d2", "evt_d2", "om_d2"))

    result = connector._drain_backlog_compensate()

    assert result["count"] == 2
    recs = store.read_all()
    assert [r.msg_id for r in recs] == ["om_d1", "om_d2"]
    assert all(r.interrupt_cause == DRAIN_TIMEOUT for r in recs)
    assert connector._msg_queue.empty(), "积压应清空"
    assert all("重新发送" in t[1] for t in sent)


# ── 重启补偿送达 + 幂等（FTR-COMP-3/4）──


def test_restart_recovery_delivers_once_idempotent(tmp_path, monkeypatch):
    bridge, connector, store, sent = _make(tmp_path, monkeypatch)
    store.append(
        InterruptionCompensationRecord(
            receive_id="oc_r1", reply_type="chat_id", interrupt_cause=CRASH, msg_id="om_r1"
        )
    )
    store.append(
        InterruptionCompensationRecord(
            receive_id="oc_r2",
            reply_type="chat_id",
            interrupt_cause=DRAIN_TIMEOUT,
            msg_id="om_r2",
        )
    )
    delivered: list[tuple[str, str]] = []
    monkeypatch.setattr(
        bridge,
        "send_text",
        lambda rid, text, rtype="chat_id": delivered.append((rid, text)) or True,
    )

    bridge._recover_interrupted()  # 第一次启动

    assert len(delivered) == 2, "补偿记录应逐条送达"
    r1_text = next(t[1] for t in delivered if t[0] == "oc_r1")
    r2_text = next(t[1] for t in delivered if t[0] == "oc_r2")
    assert "（程序提示）" in r1_text and "未完成" in r1_text and "/continue" in r1_text
    assert "（程序提示）" in r2_text and "重新发送" in r2_text
    assert store.read_all() == [], "送达后记录应剔除"

    bridge._recover_interrupted()  # 第二次启动（重启幂等）

    assert len(delivered) == 2, "幂等：已补偿记录不得重复送达"
