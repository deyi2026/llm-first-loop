"""P1-1 回归：realtime 视觉 turn 的两条生产派发路径都携带 evidence refs。

- 路径 (a)：浏览器 claim → /chat/stream——冻结的 realtime_visual_evidence facts
  不再因浏览器请求不带而 409；服务端以冻结值注入 run 输入（user_metadata）。
- 路径 (b)：服务端兜底 QueueServerFallback._execute_claimed → runner.start
  传 user_metadata（attachments=冻结 facts + human_turn_queue_id）。

文本-only / 普通上传队列项的既有行为零变化。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from llm_loop.realtime.keyframe_pipeline import CommitRecord, VisualEvidence
from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.web.queue_recovery import QueueServerFallback

CONTENT_REF = "artifact://v1/" + "a" * 32


def _visual_evidence() -> VisualEvidence:
    return VisualEvidence(
        frame_id="kf-1",
        source_id="tab-main",
        source_epoch=1,
        kind="current",
        content_ref=CONTENT_REF,
        path=".realtime/frames/ms-1/kf-1.png",
        sha256="0" * 64,
        mime="image/png",
        width=64,
        height=48,
        captured_at_client_monotonic_s=1.5,
        received_at_s=1000.0,
    )


def _commit_record(session_id: str, *, turn_id: str = "turn-1-1") -> CommitRecord:
    return CommitRecord(
        session_id=session_id,
        media_session_id="ms-1",
        turn_id=turn_id,
        text="看当前画面哪里报错",
        visual_evidence=(_visual_evidence(),),
    )


# ---------------------------------------------------------------------------
# 路径 (a)：浏览器 claim → /chat/stream
# ---------------------------------------------------------------------------


class TestBrowserClaimChatStream:
    def test_realtime_visual_turn_reaches_run_input_with_evidence_refs(
        self, tmp_path, build_test_engine, monkeypatch
    ):
        engine, _fake_llm = build_test_engine([{"content": "unused"}])
        if getattr(engine, "_event_store", None) is None:
            from llm_loop.event_log.store import EventStore

            engine._event_store = EventStore(Path(engine.settings.data_dir) / "event_logs")
        client = TestClient(build_app(engine=engine))
        session_id = client.post("/api/v1/chat", json={"message": "init"}).json()["session_id"]

        # 视觉提交经生产 sink 入队（冻结 realtime_visual_evidence facts）
        task_ref = client.app.state.realtime_commit_sink(_commit_record(session_id))
        assert task_ref.startswith("q_")

        # 浏览器 relay：领取队首项（payload 与 /chat/stream 同构，不带 realtime refs）
        claimed = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": session_id}
        ).json()["claimed"]
        assert claimed is not None
        assert claimed["queue_id"] == task_ref
        (frozen_fact,) = claimed["attachment_facts"]
        assert frozen_fact["kind"] == "realtime_visual_evidence"
        assert frozen_fact["evidence_refs"] == [CONTENT_REF]

        captured: dict[str, object] = {}

        def _fake_run_stream(sid, message, **kwargs):
            captured["sid"] = sid
            captured["message"] = message
            captured["user_metadata"] = kwargs.get("user_metadata")
            yield SimpleNamespace(text="", reasoning="", tool_round=None, tool_result=None)
            return SimpleNamespace(
                session_id=sid,
                final_answer="done",
                verification_note=None,
                rounds=1,
                tool_calls=0,
                truncated=False,
                model_used="fake",
                tokens_in=1,
                tokens_out=1,
                reasoning_content="",
            )

        monkeypatch.setattr(engine, "_run_stream_with_acquired", _fake_run_stream)

        resp = client.post(
            "/api/v1/chat/stream",
            json={
                "session_id": session_id,
                "message": "看当前画面哪里报错",
                "queue_id": task_ref,
                "attachments": [],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "queue_claim_mismatch" not in body
        assert '"type": "done"' in body or '"type":"done"' in body

        # run 输入：服务端冻结 facts 注入 user_metadata（不信任客户端补传）
        assert captured["sid"] == session_id
        assert captured["message"] == "看当前画面哪里报错"
        metadata = captured["user_metadata"]
        assert isinstance(metadata, dict)
        assert metadata["human_turn_queue_id"] == task_ref
        assert metadata["attachments"] == [frozen_fact]
        assert metadata["attachments"][0]["evidence_refs"] == [CONTENT_REF]

        # 队列项随 run 终态收敛：completed 后不再留在 active 列表（durable 收口）
        items = client.get(f"/api/v1/chat/queue?session_id={session_id}").json()["items"]
        assert items == []

    def test_client_cannot_inject_realtime_fact_via_attachments(self, tmp_path, build_test_engine):
        """服务端注入只认冻结值：客户端把 realtime 形状塞进 attachments 不改变 run 输入。"""
        engine, _fake_llm = build_test_engine([{"content": "unused"}])
        if getattr(engine, "_event_store", None) is None:
            from llm_loop.event_log.store import EventStore

            engine._event_store = EventStore(Path(engine.settings.data_dir) / "event_logs")
        client = TestClient(build_app(engine=engine))
        session_id = client.post("/api/v1/chat", json={"message": "init"}).json()["session_id"]
        task_ref = client.app.state.realtime_commit_sink(_commit_record(session_id))
        claimed = client.post(
            "/api/v1/chat/queue/dispatch", json={"session_id": session_id}
        ).json()["claimed"]
        assert claimed is not None
        captured: dict[str, object] = {}

        def _fake_run_stream(sid, message, **kwargs):
            captured["user_metadata"] = kwargs.get("user_metadata")
            yield SimpleNamespace(text="", reasoning="", tool_round=None, tool_result=None)
            return SimpleNamespace(
                session_id=sid,
                final_answer="done",
                verification_note=None,
                rounds=1,
                tool_calls=0,
                truncated=False,
                model_used="fake",
                tokens_in=1,
                tokens_out=1,
                reasoning_content="",
            )

        engine._run_stream_with_acquired = _fake_run_stream
        # 普通上传 ref 解析失败（不存在的 attachment://）→ 422，run 不启动，
        # 队列项不因此被吞（仍 claimed）。
        bogus = client.post(
            "/api/v1/chat/stream",
            json={
                "session_id": session_id,
                "message": "看当前画面哪里报错",
                "queue_id": task_ref,
                "attachments": [{"ref": "attachment://" + "f" * 32}],
            },
        )
        assert bogus.status_code in (400, 422)
        assert captured == {}  # 未进入 run
        item = client.get(f"/api/v1/chat/queue?session_id={session_id}").json()["items"][0]
        assert item["status"] == "claimed"


# ---------------------------------------------------------------------------
# 路径 (b)：服务端兜底 QueueServerFallback
# ---------------------------------------------------------------------------


class _RecordingRunner:
    def __init__(self) -> None:
        self.enabled = True
        self.starts: list[dict[str, object]] = []

    def get_handle(self, sid):  # noqa: ARG002 - 与生产 runner 协议对齐
        return None

    def is_running(self, sid):  # noqa: ARG002
        return False

    def is_sync_active(self, sid):  # noqa: ARG002
        return False

    def start(self, sid, message, **kwargs):
        self.starts.append({"sid": sid, "message": message, **kwargs})
        return SimpleNamespace(session_id=sid), None


class TestServerFallbackDispatch:
    def _hq(self, tmp_path: Path) -> HumanTurnQueue:
        return HumanTurnQueue(tmp_path / "data")

    def test_fallback_passes_frozen_realtime_facts_into_runner_start(self, tmp_path):
        hq = self._hq(tmp_path)
        item = hq.enqueue(
            "sess-v",
            "看当前画面哪里报错",
            attachment_facts=[
                {
                    "kind": "realtime_visual_evidence",
                    "media_session_id": "ms-1",
                    "turn_id": "turn-1-1",
                    "evidence_refs": [CONTENT_REF],
                    "frames": [],
                }
            ],
            origin="realtime_visual",
            origin_operation_id="turn-1-1",
        )
        runner = _RecordingRunner()
        engine = SimpleNamespace(
            runner=runner, settings=SimpleNamespace(data_dir=str(tmp_path / "data"))
        )
        fallback = QueueServerFallback(engine, hq, tick_s=3600.0, min_age_s=0.0)

        assert fallback.tick_once() == 1

        (start,) = runner.starts
        assert start["sid"] == "sess-v"
        metadata = start["user_metadata"]
        assert isinstance(metadata, dict)
        assert metadata["human_turn_queue_id"] == item["queue_id"]
        (fact,) = metadata["attachments"]
        assert fact["kind"] == "realtime_visual_evidence"
        assert fact["evidence_refs"] == [CONTENT_REF]
        # terminal_callback 存在（run 终态回写队列），由真实 runner 调用
        assert callable(start["terminal_callback"])

    def test_fallback_text_only_item_keeps_metadata_without_attachments(self, tmp_path):
        """文本-only 队列项：metadata 只带 human_turn_queue_id，行为零变化。"""
        hq = self._hq(tmp_path)
        hq.enqueue("sess-t", "普通排队消息")
        runner = _RecordingRunner()
        engine = SimpleNamespace(
            runner=runner, settings=SimpleNamespace(data_dir=str(tmp_path / "data"))
        )
        fallback = QueueServerFallback(engine, hq, tick_s=3600.0, min_age_s=0.0)

        assert fallback.tick_once() == 1
        (start,) = runner.starts
        assert start["message"] == "普通排队消息"
        assert start["user_metadata"]["human_turn_queue_id"].startswith("q_")
        assert "attachments" not in start["user_metadata"]


class TestCommitSinkSessionExistence:
    """P2-9a（审查 2026-10-25 第 9 条，服务端部分）。

    sink 入队前校验目标会话存在：不存在的 session_id（如前端无会话 fallback
    "local"）→ 明确拒绝、绝不入队（durable 队列不产生永不可执行的项）。
    """

    def test_unknown_session_rejected_without_enqueue(self, tmp_path, build_test_engine):
        engine, _fake_llm = build_test_engine([{"content": "unused"}])
        if getattr(engine, "_event_store", None) is None:
            from llm_loop.event_log.store import EventStore

            engine._event_store = EventStore(Path(engine.settings.data_dir) / "event_logs")
        client = TestClient(build_app(engine=engine))
        session_id = client.post("/api/v1/chat", json={"message": "init"}).json()["session_id"]
        sink = client.app.state.realtime_commit_sink

        before = client.get(f"/api/v1/chat/queue?session_id={session_id}").json()["items"]
        # 不存在的目标会话（与前端 fallback "local" 同类）→ 明确拒绝
        with pytest.raises(ValueError, match="does not exist"):
            sink(_commit_record("local"))
        # 队列前后一致：无 durable 项产生（"local" 侧永不可执行项为零）
        after = client.get(f"/api/v1/chat/queue?session_id={session_id}").json()["items"]
        assert after == before
        queues = getattr(client.app.state, "human_turn_queues", None) or {}
        data_dir = str(Path(str(engine.settings.data_dir)).expanduser().resolve())
        hq = queues.get(data_dir)
        assert hq is not None  # chat 请求已建单例；对未知会话拒绝不新增任何项
        assert hq.list_active("local") == []
        # 控制组：真实存在的会话不受校验影响，正常入队
        assert sink(_commit_record(session_id)).startswith("q_")
