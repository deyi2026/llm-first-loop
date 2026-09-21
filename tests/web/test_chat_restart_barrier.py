"""Restart admission barrier on web endpoints (design v1.2 §8.2/§8.3; T31/T11).

The restart waiting window must gate NEW run creation at the web admission
boundary:
- sync /chat answers with a durable queued receipt carrying the operation id
  (and only that — no run is started, so the wait cannot be postponed by
  newly arriving messages),
- queue dispatch refuses claims during the window,
- a claimed item handed to /chat/stream is rolled back to queued (FIFO kept)
  with a session_busy-family receipt,
- after the owning operation releases the barrier, admission is fully
  restored (T11: 排空后新请求不得被残留屏障挡住).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.runtime.admission_barrier import AdmissionBarrierRegistry
from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue


def _make_client(engine) -> TestClient:
    if getattr(engine, "_event_store", None) is None:
        from llm_loop.event_log.store import EventStore

        engine._event_store = EventStore(Path(engine.settings.data_dir) / "event_logs")
    return TestClient(build_app(engine=engine))


def _setup_session(engine, client) -> str:
    r = client.post("/api/v1/chat", json={"message": "init"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _registry(engine) -> AdmissionBarrierRegistry:
    return AdmissionBarrierRegistry(Path(engine.settings.data_dir))


def _queue(engine) -> HumanTurnQueue:
    return HumanTurnQueue(Path(engine.settings.data_dir))


class TestBarrierWindowAdmission:
    def test_sync_chat_queued_receipt_only(self, build_test_engine):
        """T31: 屏障期请求者会话新消息只获带 operation_id 的排队回执，无新 run."""
        engine, _ = build_test_engine([{"content": "unused"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        reg = _registry(engine)
        reg.establish("web", operation_id="svc-t31a", reason="restart")

        r = client.post("/api/v1/chat", json={"session_id": sid, "message": "窗口内消息"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["queued"] is True
        assert body["restart_barrier"]["operation_id"] == "svc-t31a"

        # 消息持久化为 queued 项；不产生新的活跃 run（队列是唯一事实）
        active = _queue(engine).list_active(sid)
        assert [it["status"] for it in active] == ["queued"]
        assert active[0]["message"] == "窗口内消息"

    def test_dispatch_refused_during_barrier(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "unused"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        client.post("/api/v1/chat/queue", json={"session_id": sid, "message": "待派发"})
        reg = _registry(engine)
        reg.establish("web", operation_id="svc-t31b", reason="restart")

        r = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["claimed"] is None
        assert body["reason"] == "service_restart_barrier"
        assert body["restart_barrier"]["operation_id"] == "svc-t31b"
        # 队列保持 queued（无 claim 悬挂）
        assert [it["status"] for it in _queue(engine).list_active(sid)] == ["queued"]

    def test_stream_rolls_back_claim_to_queued(self, build_test_engine):
        """已领取项在屏障建立后发起 stream：服务端回滚 queued 并回执操作号."""
        engine, _ = build_test_engine([{"content": "unused"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        qid = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": "领取后遇屏障"}
        ).json()["queue_id"]
        claimed = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid}).json()[
            "claimed"
        ]
        assert claimed is not None
        reg = _registry(engine)
        reg.establish("web", operation_id="svc-t31c", reason="restart")

        r = client.post(
            "/api/v1/chat/stream",
            json={"session_id": sid, "message": claimed["message"], "queue_id": qid},
        )
        assert r.status_code == 503
        body = r.json()
        assert body["error"] == "session_busy"
        assert body["restart_barrier"]["operation_id"] == "svc-t31c"
        assert body["queue_id"] == qid
        # 回滚为 queued（FIFO 保持），无新增重复项
        active = _queue(engine).list_active(sid)
        assert [it["status"] for it in active] == ["queued"]
        assert len(active) == 1

    def test_direct_stream_send_is_enqueued_with_receipt(self, build_test_engine):
        engine, _ = build_test_engine([{"content": "unused"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        reg = _registry(engine)
        reg.establish("web", operation_id="svc-t31d", reason="restart")

        r = client.post(
            "/api/v1/chat/stream",
            json={"session_id": sid, "message": "直接发送"},
        )
        assert r.status_code == 503
        body = r.json()
        assert body["queued"] is True
        assert body["restart_barrier"]["operation_id"] == "svc-t31d"
        active = _queue(engine).list_active(sid)
        assert [it["status"] for it in active] == ["queued"]
        assert active[0]["message"] == "直接发送"


class TestBarrierReleaseRestoresAdmission:
    def test_admission_restored_after_release(self, build_test_engine):
        """T11: 屏障释放后准入完全恢复——派发可领取、同步 chat 正常."""
        engine, _ = build_test_engine([{"content": "恢复后回答"}])
        client = _make_client(engine)
        sid = _setup_session(engine, client)
        reg = _registry(engine)
        reg.establish("web", operation_id="svc-t11", reason="restart")
        client.post("/api/v1/chat", json={"session_id": sid, "message": "窗口内消息"})

        assert reg.release("web", operation_id="svc-t11") is True

        # 派发恢复：窗口内排队的消息可被领取
        r = client.post("/api/v1/chat/queue/dispatch", json={"session_id": sid})
        claimed = r.json()["claimed"]
        assert claimed is not None and claimed["message"] == "窗口内消息"

        # 同步 chat 恢复正常（不再 202 排队回执）
        r2 = client.post("/api/v1/chat", json={"session_id": sid, "message": "恢复后提问"})
        assert r2.status_code == 200, r2.text
        assert "restart_barrier" not in r2.json()
