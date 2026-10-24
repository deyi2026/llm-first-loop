"""M3 收尾：生产 app 工厂装配测试（registry / commit_sink / 文本-only 零变化）。

对应验收：build_app 后 app.state 上有 KeyframeServiceRegistry 与 commit_sink；
visual commit 经 sink 携带 evidence refs；无视觉字段不触发 sink。
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

from llm_loop.realtime.keyframe_pipeline import (
    CommitRecord,
    KeyframeServiceRegistry,
    VisualEvidence,
)
from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime
from llm_loop.web import build_app

ASR_URL = "http://127.0.0.1:8000/v1/audio/transcriptions"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"m3-assembly-frame" + b"\x00" * 8
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


class FakeTransport:
    def __init__(self, *, text: str = "看当前画面哪里报错") -> None:
        self.text = text

    def append(self, frame: bytes) -> None:
        pass

    def transcribe(self, url: str, segment: bytes) -> str:
        return self.text

    def synthesize(self, text: str) -> bytes:
        return b"PCM"

    def close(self) -> None:
        pass


def _app(tmp_path):
    engine = SimpleNamespace(
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        workspace_root=str(tmp_path / "ws"),
        # P2-9a：生产 sink 入队前校验 engine.session.exists；本替身声明
        # "sess-1" 存在（与下方测试固定的 session_id 一致，存在性语义外其余不变）。
        session=SimpleNamespace(exists=lambda sid: sid == "sess-1"),
    )
    (tmp_path / "ws").mkdir(exist_ok=True)
    return build_app(engine=engine)


def _runtime(app, media_session_id="ms-1", session_id="sess-1", transport=None):
    text_out: list[str] = []

    async def send_text(payload: str) -> None:
        text_out.append(payload)

    pipeline = app.state.realtime_keyframes.pipeline_for(
        media_session_id=media_session_id, session_id=session_id
    )
    runtime = RealtimeSessionRuntime(
        media_session_id=media_session_id,
        session_id=session_id,
        transport=transport or FakeTransport(),
        transcription_url=ASR_URL,
        send_text=send_text,
        send_binary=lambda payload: None,
        keyframes=pipeline,
        commit_sink=app.state.realtime_commit_sink,
    )
    return pipeline, runtime, text_out


def _msg(msg_type: str, seq: int, **fields) -> str:
    payload = {
        "version": 1,
        "type": msg_type,
        "event_id": f"e-{seq}",
        "seq": seq,
        "connection_epoch": 1,
        "session_id": "sess-1",
        "media_session_id": "ms-1",
    }
    payload.update(fields)
    return json.dumps(payload)


def _events(text_out) -> list[dict]:
    return [json.loads(payload) for payload in text_out]


class TestAppFactoryAssembly:
    def test_state_has_registry_and_sink(self, tmp_path):
        app = _app(tmp_path)
        assert isinstance(app.state.realtime_keyframes, KeyframeServiceRegistry)
        assert callable(app.state.realtime_commit_sink)

    def test_visual_commit_reaches_sink_once_with_evidence_refs(self, tmp_path):
        app = _app(tmp_path)
        calls: list[CommitRecord] = []
        app.state.realtime_commit_sink = lambda record: (calls.append(record), "task-asm-1")[1]
        pipeline, runtime, text_out = _runtime(app)
        pipeline.share_start("tab-main", 1)
        asyncio.run(
            runtime.handle_text(
                _msg(
                    "visual.frame",
                    1,
                    frame_id="kf-1",
                    source_id="tab-main",
                    source_epoch=1,
                    captured_at_ms=1500,
                    width=64,
                    height=48,
                    mime="image/png",
                    data_b64=PNG_B64,
                )
            )
        )
        content_ref = _events(text_out)[-1]["content_ref"]
        assert content_ref.startswith("artifact://v1/")

        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "input.final", "turn.committed"]
        assert events[1]["visual"] is True
        assert events[-1]["task_ref"] == "task-asm-1"
        # fake sink 恰被调用一次，且携带视觉证据 refs 与原文
        (record,) = calls
        assert record.text == "看当前画面哪里报错"
        assert [e.content_ref for e in record.visual_evidence] == [content_ref]

    def test_text_only_commit_never_touches_sink(self, tmp_path):
        app = _app(tmp_path)
        calls: list[CommitRecord] = []
        app.state.realtime_commit_sink = lambda record: (calls.append(record), "task-x")[1]
        _, runtime, text_out = _runtime(app)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        events = _events(text_out)
        # 旧路径零变化：input.final（无 visual 字段）+ turn.committed；不触发 sink
        assert [e["type"] for e in events] == ["input.final", "turn.committed"]
        assert "visual" not in events[0]
        assert calls == []

    def test_production_sink_enqueues_into_existing_human_turn_queue(self, tmp_path):
        # 真实 sink：走既有 Web 任务提交入口（HumanTurnQueue durable 单例），
        # 文本原样 + 视觉证据 refs 落独立结构化字段 attachment_facts。
        app = _app(tmp_path)
        sink = app.state.realtime_commit_sink
        evidence = VisualEvidence(
            frame_id="kf-1",
            source_id="tab-main",
            source_epoch=1,
            kind="current",
            content_ref="artifact://v1/" + "a" * 32,
            path=".realtime/frames/ms-1/kf-1.png",
            sha256="0" * 64,
            mime="image/png",
            width=64,
            height=48,
            captured_at_client_monotonic_s=1.5,
            received_at_s=1000.0,
        )
        record = CommitRecord(
            session_id="sess-1",
            media_session_id="ms-1",
            turn_id="turn-1-1",
            text="看当前画面哪里报错",
            visual_evidence=(evidence,),
        )
        task_ref = sink(record)
        assert task_ref.startswith("q_")
        key = str(Path(str(app.state.engine.settings.data_dir)).expanduser().resolve())
        hq = app.state.human_turn_queues[key]
        active = hq.list_active("sess-1")
        assert len(active) == 1
        item = active[0]
        assert item["message"] == "看当前画面哪里报错"  # 原文不被视觉字段污染
        assert item["origin"] == "realtime_visual"
        assert item["origin_operation_id"] == "turn-1-1"
        (facts,) = item["attachment_facts"]
        assert facts["kind"] == "realtime_visual_evidence"
        assert facts["evidence_refs"] == [evidence.content_ref]
