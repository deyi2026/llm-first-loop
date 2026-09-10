"""Human Turn Queue（生成中排队发送）测试 — feature/webui-human-turn-queue-20260910.

覆盖：
1. 队列 API 全流程：入队（冻结事实）→ 查看 → 取消
2. durable 落盘：新实例（模拟 8903 重启）重载后队列不丢
3. FIFO 派发 + 原子领取：并发 dispatch 只有一个成功；顺序按 created_at
4. claimed 悬挂 reaper：超时回滚 queued
5. chat_stream 带 queue_id：run 终态回写 completed
6. release 回滚：领取方无法发起时保持 FIFO
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.web.routes import _queue_claim_state


def _make_client(engine):
    # The queue contract is explicitly durable/replay-sensitive. The generic test engine
    # fixture omits EventStore for unrelated unit speed, so queue Web tests attach the
    # same enabled EventStore production uses rather than weakening queue durability.
    if getattr(engine, "_event_store", None) is None:
        from llm_loop.event_log.store import EventStore

        engine._event_store = EventStore(Path(engine.settings.data_dir) / "event_logs")
    return TestClient(build_app(engine=engine))


def _setup_session(engine, client) -> str:
    r = client.post("/api/v1/chat", json={"message": "init"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


# ---------------------------------------------------------------- 队列数据面

def test_queue_id_metadata_is_provider_invisible():
    """Queue provenance is durable metadata only; it must not alter model-visible input."""
    from llm_loop.core.message import Message, MessageSource

    base_md = {"origin_layer": "user_instruction", "program_origin": False}
    plain = Message(role="user", content="same human text", source=MessageSource.USER, metadata=base_md)
    queued = Message(
        role="user",
        content="same human text",
        source=MessageSource.USER,
        metadata={**base_md, "human_turn_queue_id": "q-private-provenance"},
    )
    assert queued.to_llm_dict() == plain.to_llm_dict() == {
        "role": "user",
        "content": "same human text",
    }


class TestHumanTurnQueueUnit:
    def test_fifo_and_atomic_claim(self, tmp_path):
        hq = HumanTurnQueue(tmp_path)
        a = hq.enqueue("s1", "first")
        b = hq.enqueue("s1", "second")
        c = hq.enqueue("s1", "third")
        # FIFO：按入队顺序领取
        got1 = hq.dispatch_claim("s1")
        got2 = hq.dispatch_claim("s1")
        assert got1["queue_id"] == a["queue_id"]
        assert got2["queue_id"] == b["queue_id"]
        # 领取 c 后无更多可派发
        got3 = hq.dispatch_claim("s1")
        assert got3["queue_id"] == c["queue_id"]
        assert hq.dispatch_claim("s1") is None

    def test_persist_across_reload(self, tmp_path):
        """durable：新实例（模拟 8903 重启）重载同一文件，队列不丢."""
        hq1 = HumanTurnQueue(tmp_path)
        item = hq1.enqueue("s1", "queued-across-restart", model="test-model")
        hq2 = HumanTurnQueue(tmp_path)  # 模拟进程重启后重读
        items = hq2.list_active("s1")
        assert len(items) == 1
        assert items[0]["queue_id"] == item["queue_id"]
        assert items[0]["message"] == "queued-across-restart"
        assert items[0]["model"] == "test-model"

    def test_claimed_timeout_reap(self, tmp_path):
        """只有机械证明 run 尚未开始，超时 claim 才可回滚 queued."""
        hq = HumanTurnQueue(
            tmp_path,
            claim_timeout_s=0.05,
            claim_state_probe=lambda _sid, _qid: "not_started",
        )
        item = hq.enqueue("s1", "will-hang")
        hq.dispatch_claim("s1")
        time.sleep(0.08)
        items = hq.list_active("s1")  # 触发 reaper
        assert items and items[0]["status"] == "queued"
        # 回滚后可再次领取
        got = hq.dispatch_claim("s1")
        assert got is not None and got["queue_id"] == item["queue_id"]

    def test_stale_claim_is_not_reaped_while_run_is_active(self, tmp_path):
        """>timeout 不是死亡证明：active run 的 claim 不得重新派发。"""
        hq = HumanTurnQueue(
            tmp_path,
            claim_timeout_s=0.0,
            claim_state_probe=lambda _sid, _qid: "active",
        )
        item = hq.enqueue("s1", "long-running")
        hq.dispatch_claim("s1")
        items = hq.list_active("s1")
        assert items == [{**items[0], "status": "claimed"}]
        assert items[0]["queue_id"] == item["queue_id"]
        assert hq.dispatch_claim("s1") is None

    def test_stale_claim_with_durable_ingress_never_auto_redispatches(self, tmp_path):
        """human ingress 已落盘但无 run.end => outcome unknown，禁止整轮自动重执行。"""
        hq = HumanTurnQueue(
            tmp_path,
            claim_timeout_s=0.0,
            claim_state_probe=lambda _sid, _qid: "ingress_open",
        )
        hq.enqueue("s1", "side-effect-risk")
        hq.dispatch_claim("s1")
        items = hq.list_active("s1")
        assert items[0]["status"] == "claimed"
        assert items[0]["recovery_state"] == "ingress_open"
        assert items[0]["recovery_required"] is True
        assert hq.dispatch_claim("s1") is None

    def test_stale_claim_unknown_fails_closed_instead_of_redispatch(self, tmp_path):
        """无法证明 not_started 时默认保护 claim，不能用 timeout 猜测重发。"""
        hq = HumanTurnQueue(tmp_path, claim_timeout_s=0.0)
        hq.enqueue("s1", "unknown-state")
        hq.dispatch_claim("s1")
        items = hq.list_active("s1")
        assert items[0]["status"] == "claimed"
        assert items[0]["recovery_state"] == "unknown"
        assert hq.dispatch_claim("s1") is None

    def test_stale_claim_reconciles_durable_completed_terminal(self, tmp_path):
        """run.end 已证明终态时只收敛 queue 状态，不重新执行。"""
        hq = HumanTurnQueue(
            tmp_path,
            claim_timeout_s=0.0,
            claim_state_probe=lambda _sid, _qid: "completed",
        )
        hq.enqueue("s1", "already-finished")
        hq.dispatch_claim("s1")
        assert hq.list_active("s1") == []
        raw = json.loads((tmp_path / "human_turn_queue.json").read_text(encoding="utf-8"))
        assert raw["items"][0]["status"] == "completed"
        assert raw["items"][0]["reconciled_from"] == "durable_run_end"

    def test_cancel_and_terminal_transitions(self, tmp_path):
        hq = HumanTurnQueue(tmp_path)
        a = hq.enqueue("s1", "cancel-me")
        assert hq.cancel("s1", a["queue_id"]) is True
        # 取消后不可再领取，也不可重复取消
        assert hq.dispatch_claim("s1") is None
        assert hq.cancel("s1", a["queue_id"]) is False
        b = hq.enqueue("s1", "complete-me")
        claimed = hq.dispatch_claim("s1")
        assert claimed["queue_id"] == b["queue_id"]
        assert hq.mark_terminal("s1", b["queue_id"], "completed") is True
        # 终态后 list_active 不再显示
        assert hq.list_active("s1") == []

    def test_release_keeps_fifo(self, tmp_path):
        """领取方无法发起（session_busy 竞态）→ release 回滚，FIFO 位置保留."""
        hq = HumanTurnQueue(tmp_path)
        a = hq.enqueue("s1", "first")
        b = hq.enqueue("s1", "second")
        got = hq.dispatch_claim("s1")
        assert got["queue_id"] == a["queue_id"]
        assert hq.release("s1", a["queue_id"]) is True
        # 回滚后 first 仍排在前
        again = hq.dispatch_claim("s1")
        assert again["queue_id"] == a["queue_id"]
        nxt = hq.dispatch_claim("s1")
        assert nxt["queue_id"] == b["queue_id"]

    def test_concurrent_dispatch_only_one_wins(self, tmp_path):
        """多标签并发领取：同一项只被领取一次（原子性）."""
        hq = HumanTurnQueue(tmp_path)
        hq.enqueue("s1", "only-one")
        winners: list = []
        barrier = threading.Barrier(8)

        def claim():
            barrier.wait()
            winners.append(hq.dispatch_claim("s1"))

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        got = [w for w in winners if w is not None]
        assert len(got) == 1

    def test_session_isolation(self, tmp_path):
        """队列按会话隔离：s2 的派发不受 s1 影响."""
        hq = HumanTurnQueue(tmp_path)
        s1a = hq.enqueue("s1", "s1-msg")
        s2a = hq.enqueue("s2", "s2-msg")
        got = hq.dispatch_claim("s2")
        assert got["queue_id"] == s2a["queue_id"]
        assert hq.list_active("s1")[0]["queue_id"] == s1a["queue_id"]


class TestQueueClaimRecoveryFacts:
    def test_formal_run_lease_blocks_stale_requeue(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "unused"}])
        sid = engine.session.create()
        with engine.session.run_lease(sid) as acquired:
            assert acquired is True
            assert _queue_claim_state(engine, sid, "q-probe") == "active"
        # No matching durable ingress exists after the formal run lease is gone.
        from llm_loop.event_log.store import EventStore

        engine._event_store = EventStore(Path(engine.settings.data_dir) / "event_logs")
        assert _queue_claim_state(engine, sid, "q-probe") == "not_started"

    def test_restart_reconciliation_uses_exact_eventstore_sequence(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "unused"}])
        sid = engine.session.create()
        from llm_loop.event_log.store import EventStore

        store = EventStore(Path(engine.settings.data_dir) / "event_logs")
        engine._event_store = store
        qid = "q_restart_exact"
        assert _queue_claim_state(engine, sid, qid) == "not_started"
        store.append(
            sid,
            "message.appended",
            {
                "role": "user",
                "content": "queued",
                "metadata": {
                    "origin_layer": "user_instruction",
                    "program_origin": False,
                    "human_turn_queue_id": qid,
                },
            },
        )
        assert _queue_claim_state(engine, sid, qid) == "ingress_open"
        store.append(sid, "run.end", {"reason": "completed"})
        assert _queue_claim_state(engine, sid, qid) == "completed"

    def test_ambiguous_second_human_ingress_fails_closed(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "unused"}])
        sid = engine.session.create()
        from llm_loop.event_log.store import EventStore

        store = EventStore(Path(engine.settings.data_dir) / "event_logs")
        engine._event_store = store
        qid = "q_ambiguous"
        store.append(
            sid,
            "message.appended",
            {
                "role": "user",
                "content": "queued",
                "metadata": {
                    "origin_layer": "user_instruction",
                    "program_origin": False,
                    "human_turn_queue_id": qid,
                },
            },
        )
        store.append(
            sid,
            "message.appended",
            {
                "role": "user",
                "content": "later human",
                "metadata": {"origin_layer": "user_instruction", "program_origin": False},
            },
        )
        store.append(sid, "run.end", {"reason": "completed"})
        assert _queue_claim_state(engine, sid, qid) == "unknown"


# ---------------------------------------------------------------- Web API 层

class TestQueueAPI:
    def test_api_full_flow(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "一"}, {"content": "二"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)

        # 入队：冻结事实
        r1 = client.post(
            "/api/v1/chat/queue",
            json={
                "session_id": sid,
                "message": "排队消息A",
                "model": "m1",
                "reasoning_effort": "high",
                "reasoning_mode": "off",
            },
        )
        assert r1.status_code == 202, r1.text
        body1 = r1.json()
        assert body1["queue_id"]
        assert body1["position"] == 1

        r2 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": "排队消息B"},
        )
        assert r2.status_code == 202
        assert r2.json()["position"] == 2

        # 查看：FIFO 序 + count
        r = client.get(f"/api/v1/chat/queue?session_id={sid}")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2 and data["queued"] == 2
        assert data["items"][0]["message"] == "排队消息A"
        assert data["items"][0]["reasoning_effort"] == "high"
        assert data["items"][0]["reasoning_mode"] == "off"
        assert data["items"][1]["message"] == "排队消息B"
        assert data["items"][1]["reasoning_mode"] == "auto"

        # 取消第二条
        qid2 = data["items"][1]["queue_id"]
        rd = client.request("DELETE", "/api/v1/chat/queue", json={"session_id": sid, "queue_id": qid2})
        assert rd.status_code == 200 and rd.json()["ok"] is True

        # 再取取消项 → 409
        rd2 = client.request("DELETE", "/api/v1/chat/queue", json={"session_id": sid, "queue_id": qid2})
        assert rd2.status_code == 409

        r = client.get(f"/api/v1/chat/queue?session_id={sid}")
        assert r.json()["count"] == 1

    def test_enqueue_unknown_session_404(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "x"}])
        client = _make_client(engine)
        r = client.post(
            "/api/v1/chat/queue", json={"session_id": "no-such", "message": "hi"}
        )
        assert r.status_code == 404
        assert r.json()["error"] == "session_not_found"

    def test_enqueue_requires_payload(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "x"}])
        client = _make_client(engine)
        r = client.post("/api/v1/chat/queue", json={"session_id": "any"})
        assert r.status_code == 422  # validator: message/attachments 至少一项

    def test_api_dispatch_fifo(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "一"}, {"content": "二"}, {"content": "三"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        for msg in ("A", "B"):
            client.post("/api/v1/chat/queue", json={"session_id": sid, "message": msg})

        r = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        assert r.status_code == 200
        assert r.json()["claimed"]["message"] == "A"
        r = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        assert r.json()["claimed"]["message"] == "B"
        r = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        assert r.json()["claimed"] is None  # 队列已空

    def test_api_release(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "x"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        client.post("/api/v1/chat/queue", json={"session_id": sid, "message": "A"})
        claimed = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": sid}
        ).json()["claimed"]
        r = client.post(
            "/api/v1/chat/queue/release",
            json={"session_id": sid, "queue_id": claimed["queue_id"]},
        )
        assert r.status_code == 200 and r.json()["ok"] is True
        # 回滚后可再次领取（仍 FIFO 第一）
        again = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": sid}
        ).json()["claimed"]
        assert again["message"] == "A"

    def test_api_release_refuses_claim_after_durable_ingress(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "unused"}])
        client = _make_client(engine)
        sid = engine.session.create()
        qid = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": "already-started"}
        ).json()["queue_id"]
        client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        engine._event_store.append(
            sid,
            "message.appended",
            {
                "role": "user",
                "content": "already-started",
                "metadata": {
                    "origin_layer": "user_instruction",
                    "program_origin": False,
                    "human_turn_queue_id": qid,
                },
            },
        )
        resp = client.post(
            "/api/v1/chat/queue/release",
            json={"session_id": sid, "queue_id": qid},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "queue_release_not_safe"
        active = client.get(f"/api/v1/chat/queue?session_id={sid}").json()["items"]
        assert active[0]["status"] == "claimed"
        assert active[0]["queue_id"] == qid

    def test_queue_file_persisted_under_data_dir(self, build_test_engine):
        """API 层入队 → data/human_turn_queue.json 落盘（durable 事实）."""
        engine, _ = build_test_engine([{"content": "x"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        client.post("/api/v1/chat/queue", json={"session_id": sid, "message": "durable"})

        data_dir = engine.settings.data_dir
        raw = json.loads((Path(data_dir) / "human_turn_queue.json").read_text(encoding="utf-8"))
        assert any(it["message"] == "durable" for it in raw["items"])


# ------------------------------------------------------- 派发承接（queue_id）

class TestDispatchHandoff:
    def test_chat_stream_with_queue_id_marks_completed(self, build_test_engine):
        """chat_stream 带 queue_id：run 终态后队列项回写 completed."""
        engine, _ = build_test_engine([{"content": "答案一"}, {"content": "排队回答"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)

        # 模拟生成中入队
        enq = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": "排队消息"}
        )
        qid = enq.json()["queue_id"]

        # 领取后用冻结 message + queue_id 走正式流式请求
        claimed = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": sid}
        ).json()["claimed"]
        assert claimed["message"] == "排队消息"

        events = []
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"session_id": sid, "message": claimed["message"], "queue_id": qid},
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        types = [e["type"] for e in events]
        assert "done" in types, f"expected done, got {types}"

        # run 终态 → 队列项 completed，list_active 清空
        r = client.get(f"/api/v1/chat/queue?session_id={sid}")
        data = r.json()
        assert data["count"] == 0, f"queue should be empty after done: {data}"

    def test_queue_id_cannot_authorize_different_frozen_request(self, build_test_engine):
        """queue_id 只授权领取时冻结的 exact request facts，不能被伪造/串用。"""
        engine, fake = build_test_engine([{"content": "init"}, {"content": "should-not-run"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        qid = client.post(
            "/api/v1/chat/queue",
            json={
                "session_id": sid,
                "message": "frozen",
                "reasoning_mode": "off",
            },
        ).json()["queue_id"]
        client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        before_events = len(engine._event_store.read(sid))
        before_messages = len(engine.session.load(sid).messages)
        resp = client.post(
            "/api/v1/chat/stream",
            json={
                "session_id": sid,
                "message": "tampered",
                "queue_id": qid,
                "reasoning_mode": "off",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "queue_claim_mismatch"
        assert len(engine._event_store.read(sid)) == before_events
        assert len(engine.session.load(sid).messages) == before_messages
        active = client.get(f"/api/v1/chat/queue?session_id={sid}").json()["items"]
        assert active[0]["status"] == "claimed"

    def test_queue_handoff_persists_queue_id_on_human_ingress_event(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "init"}, {"content": "queued-answer"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        enq = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": "queued", "reasoning_mode": "on"},
        ).json()
        qid = enq["queue_id"]
        claimed = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": sid}
        ).json()["claimed"]
        assert claimed["reasoning_mode"] == "on"
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={
                "session_id": sid,
                "message": claimed["message"],
                "queue_id": qid,
                "reasoning_mode": "on",
            },
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())
        matching = []
        for event in engine._event_store.read(sid):
            if event.type != "message.appended":
                continue
            md = event.payload.get("metadata") or {}
            if md.get("human_turn_queue_id") == qid:
                matching.append(event)
        assert len(matching) == 1
        assert matching[0].payload["role"] == "user"
        assert matching[0].payload["content"] == "queued"

    def test_queue_run_without_eventstore_does_not_execute_and_requeues(self, build_test_engine):
        """Durable ingress unavailable => no LLM/tool side effect, no phantom user row, safe retry."""
        engine, fake = build_test_engine([{"content": "init"}, {"content": "must-not-run"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        enq = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": "queued-no-store"}
        ).json()
        qid = enq["queue_id"]
        claimed = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": sid}
        ).json()["claimed"]
        before_calls = len(fake.calls)
        before_messages = len(engine.session.load(sid).messages)
        engine._event_store._enabled = False

        events = []
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"session_id": sid, "message": claimed["message"], "queue_id": qid},
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert [e["type"] for e in events] == ["error"]
        assert events[0]["data"]["error"] == "queue_ingress_durability_unavailable"
        assert len(fake.calls) == before_calls
        assert len(engine.session.load(sid).messages) == before_messages
        active = client.get(f"/api/v1/chat/queue?session_id={sid}").json()["items"]
        assert len(active) == 1
        assert active[0]["queue_id"] == qid
        assert active[0]["status"] == "queued"

    def test_queue_handoff_two_turns_fifo(self, build_test_engine):
        """两条排队消息：第一条 run 终态后，第二条仍可领取（FIFO 接力）."""
        engine, _ = build_test_engine(
            [{"content": "r1"}, {"content": "r2"}, {"content": "r3"}]
        )
        client = _make_client(engine)
        sid = _setup_session(engine, client)

        q1 = client.post("/api/v1/chat/queue", json={"session_id": sid, "message": "M1"}).json()["queue_id"]
        q2 = client.post("/api/v1/chat/queue", json={"session_id": sid, "message": "M2"}).json()["queue_id"]

        # 派发第一条并完成
        c1 = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid}).json()["claimed"]
        assert c1["queue_id"] == q1
        with client.stream(
            "POST", "/api/v1/chat/stream",
            json={"session_id": sid, "message": c1["message"], "queue_id": q1},
        ) as resp:
            list(resp.iter_lines())
        assert client.get(f"/api/v1/chat/queue?session_id={sid}").json()["count"] == 1

        # 派发第二条
        c2 = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid}).json()["claimed"]
        assert c2["queue_id"] == q2
        with client.stream(
            "POST", "/api/v1/chat/stream",
            json={"session_id": sid, "message": c2["message"], "queue_id": q2},
        ) as resp:
            list(resp.iter_lines())
        assert client.get(f"/api/v1/chat/queue?session_id={sid}").json()["count"] == 0
