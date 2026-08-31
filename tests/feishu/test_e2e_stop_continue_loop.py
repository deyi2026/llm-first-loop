"""端到端闭环实测（组 6，T10 / tasks 6.1-6.3；spec 5.3）.

真实飞书 WS 环境不可得 → 进程内模拟全链闭环（局限如实标注）：
SDK 回调线程语义由 _submit_message 直驱承载，worker/快车道/拦截器/引擎/
取消检查点/审计/事件落盘均为真实生产代码路径，仅飞书服务端回执以
reply_fn 收集桩替代。覆盖：
- T10 主序列：任务 → /stop（受理即时+终止+收口指引）→ /continue（现场恢复）
  → 再 /stop → 再 /continue（可反复控制）
- 6.2 中断补偿：user_stop 窗口内"优雅退出+重启"无重复补偿；对照组不变
- 6.3 审计与可观测：kind 四类值域、字段结构、run.end cancel_reason、会话隔离
"""

from __future__ import annotations

import json
import threading
import time

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.event_log.store import EventStore
from llm_loop.feishu import bridge as bridge_module
from llm_loop.feishu.bridge import FeishuWsBridge, _WsConnector
from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap
from llm_loop.llm.client import LLMResponse

_CHAT = "oc_e2e"


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


def _wait_reply(replies: list[tuple[str, str, str]], needle: str, count: int = 1,
                timeout: float = 6.0, desc: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        n = sum(1 for r in list(replies) if needle in r[1])
        if n >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"等待回复超时: {desc or needle}×{count}（实得 "
                         f"{sum(1 for r in replies if needle in r[1])} 条）")


def _wait_true(fn, timeout: float = 6.0, desc: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.02)
    raise AssertionError(f"等待条件超时: {desc}")


def _await_cancel(runner: BackgroundRunner, sid: str) -> LLMResponse:
    deadline = time.monotonic() + 8.0
    while not runner.is_cancelled(sid):
        if time.monotonic() > deadline:
            raise AssertionError("/stop 未在期限内置位取消标记（快车道失效）")
        time.sleep(0.01)
    return LLMResponse(content="中途产出", tool_calls=[], provider="fake")


def _make(build_test_engine, tmp_path, monkeypatch):

    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    event_store = EventStore(tmp_path / "events")
    engine._event_store = event_store
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
    bridge._connector = connector
    monkeypatch.setattr(bridge_module, "_DEDUP_PATH", str(tmp_path / "feishu_dedup.json"))
    monkeypatch.setattr(
        bridge_module, "_INTERRUPTED_PATH", str(tmp_path / "feishu_interrupted.json")
    )
    return engine, fake, runner, event_store, session_map, replies, handler, bridge, connector


def _audit_records(tmp_path) -> list[dict]:
    p = tmp_path / "audit" / "feishu_audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ── T10 主序列（tasks 6.1，spec 5.3.1-1）──


def test_t10_stop_continue_full_closed_loop(build_test_engine, tmp_path, monkeypatch):
    engine, fake, runner, event_store, session_map, replies, handler, bridge, connector = _make(
        build_test_engine, tmp_path, monkeypatch
    )
    worker = threading.Thread(target=connector._worker_loop, name="t10-worker", daemon=True)
    worker.start()
    sid = session_map.get_or_create(SessionMap.group_key(_CHAT))
    llm1_started = threading.Event()
    llm2_started = threading.Event()

    def _slow1(calls):
        llm1_started.set()
        return _await_cancel(runner, sid)

    def _slow2(calls):
        llm2_started.set()
        return _await_cancel(runner, sid)

    fake._responses = [_slow1, _slow2, {"content": "恢复后继续完成任务：分析完成。"}]

    # ① 发起任务（普通消息 → worker 串行队列 → 引擎推理）
    assert connector._submit_message(_payload("任务 X：完成数据分析", _CHAT, "evt_t1", "om_t1"))
    assert llm1_started.wait(3.0), "任务推理应已启动（worker 被占用）"

    # ② 推理中 /stop（快车道旁路，不排队）
    assert connector._submit_message(_payload("/stop", _CHAT, "evt_s1", "om_s1"))
    _wait_reply(replies, "停止已受理", desc="/stop 受理回执应即时")


    # ③ 推理终止收口：含恢复指引（spec 5.1.1-7）
    _wait_reply(replies, "已停止", desc="取消收口回复")
    closing1 = [r for r in replies if "已停止" in r[1]][0]
    assert "/continue" in closing1[1], "收口应含恢复指引"
    # 受理即时性（spec 5.1.1-3a）：受理回执必须先于收口回复（/stop 未排队等待推理完成）
    idx_accept = next(i for i, r in enumerate(replies) if "停止已受理" in r[1])
    idx_close = next(i for i, r in enumerate(replies) if "已停止" in r[1])
    assert idx_accept < idx_close
    _wait_true(lambda: not handler.is_user_stop_pending(_CHAT), desc="收口后登记应清除")

    # ④ /continue → 恢复轮基于任务现场（上下文完整保留）
    assert connector._submit_message(_payload("/continue", _CHAT, "evt_c1", "om_c1"))
    assert llm2_started.wait(3.0), "恢复轮应启动"
    msgs1 = fake.calls[-1]["messages"]
    wire1 = json.dumps(msgs1, ensure_ascii=False)
    assert any(
        m.get("role") == "user" and m.get("content") == "/continue" for m in msgs1
    ), "恢复轮应保留用户真实 /continue 指令"
    assert "[程序恢复]" not in wire1, "恢复不得改写成程序自然语言注入"
    assert "任务 X：完成数据分析" in wire1, "任务现场应完整保留"

    # ⑤ 恢复轮再 /stop（可反复控制第一半）
    assert connector._submit_message(_payload("/stop", _CHAT, "evt_s2", "om_s2"))
    _wait_reply(replies, "停止已受理", count=2, desc="第二次 /stop 受理")
    _wait_reply(replies, "已停止", count=2, desc="恢复轮取消收口")

    # ⑥ 再 /continue → 第二次恢复轮正常产出
    assert connector._submit_message(_payload("/continue", _CHAT, "evt_c2", "om_c2"))
    _wait_reply(replies, "恢复后继续完成任务", desc="第二次恢复回答")
    msgs2 = json.dumps(fake.calls[-1]["messages"], ensure_ascii=False)
    assert "任务 X：完成数据分析" in msgs2, "二次恢复仍见原始任务现场"
    assert "[程序恢复]" not in msgs2
    # 最终 run 已完成并持久化后核验 user-control provenance：两次恢复均是用户原始
    # /continue turn，不存在程序伪造的 recovery user frame。
    sess_final = engine.session.load(sid)
    continue_msgs = [m for m in sess_final.messages if m.role == "user" and m.content == "/continue"]
    assert len(continue_msgs) == 2
    assert all(m.metadata.get("origin_layer") == "user_instruction" for m in continue_msgs)
    assert all(m.metadata.get("program_origin") is False for m in continue_msgs)

    # 全链核验：无重试轮/无自动续跑（伴生异常归因 + 取消即收口）
    assert len(fake.calls) == 3
    # 包装要素一致：全部回复经同一 reply 通道（群聊 chat_id 定向）
    assert replies and all(r[0] == _CHAT and r[2] == "chat_id" for r in replies)
    # 审计：停止与恢复全过程留痕（spec 5.1.1-5）
    kinds = [rec["kind"] for rec in _audit_records(tmp_path)]
    assert kinds.count("stop_accepted") == 2
    assert kinds.count("continue_accepted") == 2
    # run.end 事件：两次取消收口带 cancel_reason，恢复轮 completed（tasks 6.3 关联核验）
    run_ends = [e for e in event_store.read(sid) if e.type == "run.end"]
    assert len(run_ends) == 3
    assert run_ends[0].payload["reason"] == "cancelled"
    assert run_ends[0].payload["cancel_reason"] == "user_stop"
    assert run_ends[1].payload["reason"] == "cancelled"
    assert run_ends[1].payload["cancel_reason"] == "user_stop"
    assert run_ends[2].payload["reason"] == "completed"
    assert run_ends[2].payload["cancel_reason"] == ""

    connector.stop()  # 哨兵优雅退出 worker（daemon 兜底）


# ── 6.2 中断补偿兼容实测（tasks 6.2，spec 5.3.1-2）──


def test_6_2_restart_no_duplicate_compensation(build_test_engine, tmp_path, monkeypatch):
    engine, fake, runner, event_store, session_map, replies, handler, bridge, connector = _make(
        build_test_engine, tmp_path, monkeypatch
    )
    sid = session_map.get_or_create(SessionMap.group_key(_CHAT))
    engine._sync_active.add(sid)  # 推理进行中（worker 正在处理 om_t1）
    connector._processing_msg_id = "om_t1"
    connector._processing_chat_id = _CHAT
    connector._processing_reply_id = _CHAT
    connector._processing_reply_type = "chat_id"
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        bridge, "send_text", lambda rid, text, rtype="chat_id": sent.append((rid, text)) or True
    )

    # /stop 经快车道受理 → user_stop 待收口窗口开启
    assert connector._submit_message(_payload("/stop", _CHAT, "evt_s", "om_s"))
    _wait_reply(replies, "停止已受理", desc="/stop 受理")

    # 窗口内优雅退出（bridge.stop 内路径）+ 重启恢复：无补偿性重复消息
    bridge._persist_interrupted()
    bridge._recover_interrupted()
    assert not (tmp_path / "feishu_interrupted.json").exists(), "窗口内不应落盘补偿"
    assert sent == [], "重启后不应有补偿性重复消息"

    # 对照组：非 /stop 的真实中断（收口窗口已关闭）→ 既有补偿行为不变
    handler._user_stop_clear(
        sid,
        FeishuMessage(
            message_id="om_s", sender_id="ou_u", chat_id=_CHAT, msg_type="text", text="/stop"
        ),
    )
    bridge._persist_interrupted()
    assert (tmp_path / "feishu_interrupted.json").exists(), "真实中断应落盘补偿（零回归）"
    bridge._recover_interrupted()
    assert sent and "服务重启被中断" in sent[0][1], "对照组补偿回复应发出"
    assert not (tmp_path / "feishu_interrupted.json").exists(), "补偿后记录应清理"


# ── 6.3 审计与可观测核验（tasks 6.3，spec 4.4.2/6.1.3）──


def test_6_3_audit_schema_and_cross_session_isolation(build_test_engine, tmp_path, monkeypatch):
    engine, fake, runner, event_store, session_map, replies, handler, bridge, connector = _make(
        build_test_engine, tmp_path, monkeypatch
    )
    sid_a = session_map.get_or_create(SessionMap.group_key("oc_a"))
    engine._sync_active.add(sid_a)  # 会话 A 推理进行中

    # 会话 B（无映射）发 /stop → 空操作，不影响 A（spec 4.3.1 隔离）
    assert connector._submit_message(_payload("/stop", "oc_b", "evt_b", "om_b"))
    _wait_reply(replies, "当前没有进行中的推理", desc="B 会话 stop_noop 回执")
    assert runner.is_cancelled(sid_a) is False

    # 会话 A 发 /stop → 受理
    assert connector._submit_message(_payload("/stop", "oc_a", "evt_a", "om_a"))
    _wait_reply(replies, "停止已受理", desc="A 会话受理回执")

    # 处理通道异常 → stop_error fail-open（指令文本不漏入引擎）
    def _boom(session_id, reason="user_stop"):
        raise RuntimeError("cancel 通道故障")

    monkeypatch.setattr(runner, "cancel", _boom)
    assert connector._submit_message(_payload("/stop", "oc_a", "evt_e", "om_e"))
    _wait_reply(replies, "指令处理异常", desc="stop_error 回执")
    assert len(fake.calls) == 0

    # 审计字段结构不变（ts/message_id/kind/chat_id/sender_id/detail）
    records = _audit_records(tmp_path)
    assert records, "审计应落盘"
    for rec in records:
        assert {"ts", "message_id", "kind", "chat_id", "sender_id", "detail"} <= set(rec)
    kinds = {rec["kind"] for rec in records}
    assert {"stop_noop", "stop_accepted", "stop_error"} <= kinds
