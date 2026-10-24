"""M3 服务端视觉证据链端到端测试（T-M3-1/2/3/4，路由/WS 级）。

覆盖 RTM：VIS-01..09、RET-01/02/04/05、SES-04、IDN-02、OBS-02。
对应契约：docs/M3-KEYFRAME-WIRE-CONTRACT.md。

关键断言组：
- 摄取：合法帧 → WorkspaceArtifactStore（唯一证据库）+ KeyframeStore 元数据；
  非法帧有界拒绝（epoch/归属/大小/mime/来源/频控），不产生副作用；
- 绑定：input.commit{visual} → committed turn 与任务输入（commit sink）可见
  artifact ref，用户原文不被篡改；歧义 → visual.clarify 且不派发；
- 失效：share.stop/epoch 变化/会话清理 → 当前失效、历史可读、回读明确报错；
  RET-04 容量/时长上限在 store 层生效；
- 隐私：下行事件与日志不含媒体体（data_b64/解码字节）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from llm_loop.realtime.keyframe import (
    CurrentValidity,
    KeyframeReadbackError,
    RetentionState,
)
from llm_loop.realtime.keyframe_pipeline import (
    KeyframeLimits,
    KeyframePipeline,
    KeyframeServiceRegistry,
)
from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime
from llm_loop.web.auth import SESSION_COOKIE_NAME, WebSessionStore
from llm_loop.web.realtime_routes import router as realtime_router
from llm_loop.web.realtime_ws import REALTIME_WS_PATH, register_realtime_ws
from llm_loop.workspace.artifacts import WorkspaceArtifactStore

ASR_URL = "http://127.0.0.1:8000/v1/audio/transcriptions"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"m3-e2e-frame-payload" + b"\x00" * 8
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


class FakeTransport:
    def __init__(self, *, text: str = "看当前画面哪里报错") -> None:
        self.text = text
        self.transcribed: list[tuple[str, bytes]] = []
        self.appended: list[bytes] = []

    def append(self, frame: bytes) -> None:
        self.appended.append(frame)

    def transcribe(self, url: str, segment: bytes) -> str:
        self.transcribed.append((url, segment))
        return self.text

    def synthesize(self, text: str) -> bytes:
        return b"PCM"

    def close(self) -> None:
        pass


def _pipeline(tmp_path, *, limits: KeyframeLimits | None = None, clock=None):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    artifacts = WorkspaceArtifactStore(tmp_path / "art")
    if clock is None:
        holder = [1000.0]
        clock = lambda: holder[0]  # noqa: E731
        holder_attr = holder
    else:
        holder_attr = None
    pipeline = KeyframePipeline(
        media_session_id="ms-1",
        session_id="sess-1",
        artifact_store=artifacts,
        workspace_root=ws_root,
        limits=limits,
        now_fn=clock,
    )
    return pipeline, artifacts, ws_root, clock if holder_attr is None else holder_attr


def _runtime(pipeline, sink=None, transport=None, session_probe=None):
    text_out: list[str] = []
    binary_out: list[bytes] = []
    sinks: list[object] = []

    async def send_text(payload: str) -> None:
        text_out.append(payload)

    async def send_binary(payload: bytes) -> None:
        binary_out.append(payload)

    def commit_sink(record) -> str:
        sinks.append(record)
        return "task-1"

    transport = transport or FakeTransport()
    runtime = RealtimeSessionRuntime(
        media_session_id="ms-1",
        session_id="sess-1",
        transport=transport,
        transcription_url=ASR_URL,
        send_text=send_text,
        send_binary=send_binary,
        connection_epoch=5,
        keyframes=pipeline,
        commit_sink=sink if sink is not None else commit_sink,
        session_probe=session_probe,
    )
    return runtime, text_out, binary_out, sinks


def _msg(msg_type: str, seq: int, **fields) -> str:
    payload = {
        "version": 1,
        "type": msg_type,
        "event_id": f"e-{seq}",
        "seq": seq,
        "connection_epoch": 5,
        "session_id": "sess-1",
        "media_session_id": "ms-1",
    }
    payload.update(fields)
    return json.dumps(payload)


def _events(text_out) -> list[dict]:
    return [json.loads(payload) for payload in text_out]


def _share(pipeline, *, source_id="tab-main", epoch=1, label=None):
    return pipeline.share_start(source_id, epoch, label)


def _frame_msg(frame_id="kf-1", *, source_id="tab-main", epoch=1, data=PNG_B64, **extra):
    payload = {
        "frame_id": frame_id,
        "source_id": source_id,
        "source_epoch": epoch,
        "captured_at_ms": 1500,
        "width": 1280,
        "height": 720,
        "mime": "image/png",
        "data_b64": data,
    }
    payload.update(extra)
    return payload


class TestIngestAndBinding:
    def test_register_bind_and_task_input_sees_ref(self, tmp_path):
        pipeline, artifacts, ws_root, _ = _pipeline(tmp_path)
        runtime, text_out, _, sinks = _runtime(pipeline)
        assert _share(pipeline)[0] == "started"
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        events = _events(text_out)
        registered = events[-1]
        assert registered["type"] == "visual.frame.registered"
        assert registered["frame_id"] == "kf-1"
        content_ref = registered["content_ref"]
        assert content_ref.startswith("artifact://v1/")

        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "input.final", "turn.committed"]
        committed = events[-1]
        assert committed["evidence_refs"] == [content_ref]
        assert committed["visual"][0]["frame_id"] == "kf-1"
        assert committed["visual"][0]["content_ref"] == content_ref
        assert committed["task_ref"] == "task-1"

        # 任务输入（commit sink）可见 ref；用户原文原样、未被视觉字段污染
        (record,) = sinks
        assert record.text == "看当前画面哪里报错"
        assert record.visual_evidence[0].content_ref == content_ref
        # 字节可经 artifact store 回读且与上送一致；帧文件在工作区为回读入口
        assert artifacts.read_bytes(content_ref, workspace_scope=str(ws_root)) == PNG_BYTES
        frame_file = ws_root / ".realtime" / "frames" / "ms-1" / "kf-1.png"
        assert frame_file.read_bytes() == PNG_BYTES

    def test_frame_metadata_in_keyframe_store(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline, epoch=2)
        result = pipeline.ingest(_frame_msg(source_id="tab-main", epoch=2))
        frame = pipeline._store.get("kf-1")  # noqa: SLF001 - 断言元数据落库
        assert frame is not None
        assert frame.source_epoch == 2
        assert frame.retention_state is RetentionState.RETAINED
        assert frame.content_ref == result.content_ref
        assert frame.captured_at_client_monotonic_s == 1.5  # ms → s

    def test_idempotent_resend_and_duplicate_conflict(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        first = pipeline.ingest(_frame_msg())
        again = pipeline.ingest(_frame_msg())
        assert first.content_ref == again.content_ref
        other = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"different").decode()
        rejected = pipeline.ingest(_frame_msg(data=other))
        assert rejected.reason == "duplicate_frame_id"

    def test_text_only_commit_unchanged(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, sinks = _runtime(pipeline)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["input.final", "turn.committed"]
        assert "evidence_refs" not in events[-1] or events[-1].get("evidence_refs") is None
        assert sinks == []  # 文本-only 不触发视觉提交 sink

    def test_jpeg_and_webp_magic_validation(self, tmp_path):
        holder = [1000.0]
        pipeline, _, _, _ = _pipeline(tmp_path, clock=lambda: holder[0])
        _share(pipeline)
        jpeg = base64.b64encode(b"\xff\xd8\xff" + b"j").decode()
        webp = base64.b64encode(b"RIFF\x00\x00\x00\x00WEBP" + b"w").decode()
        holder[0] += 1.0
        reg_j = pipeline.ingest(_frame_msg("kf-j", mime="image/jpeg", data=jpeg))
        assert hasattr(reg_j, "content_ref")
        holder[0] += 1.0
        reg_w = pipeline.ingest(_frame_msg("kf-w", mime="image/webp", data=webp))
        assert hasattr(reg_w, "content_ref")
        holder[0] += 1.0
        # 魔数不符：png 字节声明 jpeg → 拒绝
        bad = pipeline.ingest(_frame_msg("kf-bad", mime="image/jpeg", data=PNG_B64))
        assert bad.reason == "mime_unsupported"


class TestRejections:
    def test_envelope_epoch_mismatch(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        stale = _msg("visual.share.start", 1, source_id="tab-main", source_epoch=1)
        payload = json.loads(stale)
        payload["connection_epoch"] = 4
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        events = _events(text_out)
        assert events[-1]["type"] == "error"
        assert events[-1]["reason"] == "stale_epoch"
        assert pipeline.known_sources() == ()  # 无副作用

    def test_envelope_wrong_session(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.frame", 1, **_frame_msg()))
        payload["media_session_id"] = "ms-other"
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        assert _events(text_out)[-1]["reason"] == "wrong_session"

    def test_envelope_unsupported_version(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
        payload["version"] = 2
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        assert _events(text_out)[-1]["reason"] == "unsupported_version"

    def test_unknown_source_rejected_without_fallback(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        events = _events(text_out)
        assert events[-1]["type"] == "visual.frame.rejected"
        assert events[-1]["reason"] == "unknown_source"
        assert pipeline.observe()["counters"]["rejected"]["unknown_source"] == 1

    def test_source_epoch_mismatch_in_frame(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline, epoch=1)
        runtime, text_out, _, _ = _runtime(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg(epoch=9))))
        assert _events(text_out)[-1]["reason"] == "source_epoch_mismatch"

    def test_oversize_frame_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x01" * (513 * 1024)).decode()
        rejected = pipeline.ingest(_frame_msg(data=big))
        assert rejected.reason == "frame_too_large"

    def test_malformed_fields_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        assert pipeline.ingest(_frame_msg(width=0)).reason == "malformed"
        assert hasattr(pipeline.ingest(_frame_msg()), "content_ref")  # 完整重发幂等，不视为畸形
        assert pipeline.ingest(_frame_msg(selection={"x": 1, "y": 2, "width": 0, "height": 3})).reason == "malformed"

    def test_rate_limit_two_frames_too_close(self, tmp_path):
        holder = [1000.0]
        pipeline, _, _, _ = _pipeline(tmp_path, clock=lambda: holder[0])
        _share(pipeline)
        assert hasattr(pipeline.ingest(_frame_msg("kf-a")), "content_ref")
        holder[0] += 0.05  # < min_interval 0.2s
        assert pipeline.ingest(_frame_msg("kf-b")).reason == "rate_limited"


class TestClarify:
    def test_no_current_frame_clarifies_without_dispatch(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, sinks = _runtime(pipeline)
        _share(pipeline)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(_msg("input.commit", 1, visual={"source_id": "tab-main", "kind": "current"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["input.final", "visual.clarify"]
        assert events[-1]["question"]
        assert sinks == []  # 不派发任务

    def test_unknown_source_in_commit_rejected_no_side_effect(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 1, visual={"source_id": "tab-ghost", "kind": "current"}))
        )
        events = _events(text_out)
        assert events[-1]["type"] == "error"
        assert events[-1]["reason"] == "unknown_source"
        assert runtime.buffered_bytes == 640  # 音频保留：客户端修正后可重提交

    def test_malformed_visual_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("input.commit", 1, visual={"source_id": "tab-main", "kind": "whatever"})))
        assert _events(text_out)[-1]["reason"] == "malformed"


class TestCommitSinkProtocol:
    def test_visual_commit_marks_input_final_visual_true(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "input.final", "turn.committed"]
        assert events[1]["visual"] is True  # 客户端据此不本地重复提交

    def test_text_only_input_final_has_no_visual_flag(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["input.final", "turn.committed"]
        assert "visual" not in events[0]  # 文本-only 零变化

    def test_visual_commit_without_sink_503_no_fake_committed(self, tmp_path):
        # keyframes 已装配但 commit_sink 未装配（测试/显式禁用路径）：
        # fail-safe 503，不消费音频、不伪造 turn.committed。
        pipeline, _, _, _ = _pipeline(tmp_path)
        text_out: list[str] = []

        async def send_text(payload: str) -> None:
            text_out.append(payload)

        runtime = RealtimeSessionRuntime(
            media_session_id="ms-1",
            session_id="sess-1",
            transport=FakeTransport(),
            transcription_url=ASR_URL,
            send_text=send_text,
            send_binary=lambda payload: None,
            connection_epoch=5,
            keyframes=pipeline,
            commit_sink=None,
        )
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "error"]
        assert events[-1]["code"] == 503
        assert events[-1]["reason"] == "task_submit_unavailable"
        assert runtime.buffered_bytes == 640  # 音频保留：装配修复后可重提交

    def test_history_reference_in_final_text_overrides_kind(self, tmp_path):
        # kind=current 提示，但终稿「刚才那页」→ 绑历史帧（share.stop 后仍可答）。
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, sinks = _runtime(pipeline, transport=FakeTransport(text="看刚才那页的报错"))
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        pipeline.share_stop("tab-main", 1)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"})))
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "input.final", "turn.committed"]
        committed = events[-1]
        assert committed["visual"][0]["kind"] == "history"  # 生效 kind 如实注记
        assert sinks[0].visual_evidence[0].content_ref == committed["evidence_refs"][0]


class TestStopShareAndExpiry:
    def test_stop_share_current_rejected_history_readable(self, tmp_path):
        holder = [1000.0]
        pipeline, artifacts, ws_root, _ = _pipeline(tmp_path, clock=lambda: holder[0])
        runtime, text_out, _, sinks = _runtime(pipeline)
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        holder[0] += 1.0
        outcome, detail = pipeline.share_stop("tab-main", 1)
        assert outcome == "stopped"
        holder[0] += 1.0

        # current 拒绝（当前有效性已失效）→ 澄清不派发
        asyncio.run(runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"})))
        assert _events(text_out)[-1]["type"] == "visual.clarify"

        # history 可读：从未绑定的历史帧可绑定并回读
        asyncio.run(runtime.handle_text(_msg("input.commit", 3, visual={"source_id": "tab-main", "kind": "history"})))
        committed = _events(text_out)[-1]
        assert committed["type"] == "turn.committed"
        ref = committed["evidence_refs"][0]
        assert artifacts.read_bytes(ref, workspace_scope=str(ws_root)) == PNG_BYTES

    def test_frame_after_stop_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        assert pipeline.share_stop("tab-main", 1)[0] == "stopped"
        assert pipeline.ingest(_frame_msg("kf-after")).reason == "source_not_active"

    def test_source_epoch_bump_stales_current_keeps_history(self, tmp_path):
        holder = [1000.0]
        pipeline, _, _, _ = _pipeline(tmp_path, clock=lambda: holder[0])
        _share(pipeline, epoch=1)
        pipeline.ingest(_frame_msg("kf-1"))
        holder[0] += 1.0
        _share(pipeline, epoch=2)  # 换新代次：旧帧当前失效
        holder[0] += 1.0
        assert pipeline._store.current_frame("tab-main") is None  # noqa: SLF001 - 当前有效性失效
        frame = pipeline._store.get("kf-1")  # noqa: SLF001
        assert frame.retention_state is RetentionState.RETAINED
        assert frame.current_validity is CurrentValidity.STALE  # 当前失效，证据保留
        # 旧 epoch 帧上送被拒；历史指代仍可绑定
        assert pipeline.ingest(_frame_msg("kf-2", epoch=1)).reason == "source_epoch_mismatch"
        outcome, _ = pipeline.bind_commit(turn_id="t-9", visual={"source_id": "tab-main", "kind": "history"})
        assert outcome == "bound"

    def test_frame_already_bound_conflict(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        pipeline.ingest(_frame_msg("kf-1"))
        assert pipeline.bind_commit(turn_id="t-1", visual={"source_id": "tab-main", "kind": "current"})[0] == "bound"
        assert pipeline.bind_commit(turn_id="t-2", visual={"source_id": "tab-main", "kind": "current"}) == (
            "rejected",
            "frame_already_bound",
        )

    def test_close_session_expires_and_readback_fails(self, tmp_path):
        pipeline, artifacts, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        registered = pipeline.ingest(_frame_msg("kf-1"))
        assert pipeline.close_session() == 1
        with pytest.raises(KeyframeReadbackError):
            pipeline.readback("kf-1")
        # 已到期：artifact 记录仍在（不可变精确源），但视觉链拒绝回读
        assert pipeline.ingest(_frame_msg("kf-2")).reason == "session_closed"
        assert registered.content_ref  # 引用保持可解析（供审计），语义失效在 store 层

    def test_retention_capacity_evicts_oldest_unbound(self, tmp_path):
        holder = [1000.0]
        limits = KeyframeLimits(min_interval_s=0.0, max_unbound_frames=2, max_frame_age_s=10_000.0)
        pipeline, _, _, _ = _pipeline(tmp_path, limits=limits, clock=lambda: holder[0])
        _share(pipeline)
        for index in range(4):
            holder[0] += 1.0
            pipeline.ingest(_frame_msg(f"kf-{index}"))
        stats = pipeline.observe()
        assert stats["store"]["unbound_retained"] == 2
        assert stats["counters"]["evicted"] == 2
        assert pipeline._store.get("kf-0").retention_state is RetentionState.EXPIRED  # noqa: SLF001
        assert pipeline._store.get("kf-3").retention_state is RetentionState.RETAINED  # noqa: SLF001

    def test_cache_full_when_all_bound(self, tmp_path):
        holder = [1000.0]
        limits = KeyframeLimits(min_interval_s=0.0, max_unbound_frames=1, max_frame_age_s=10_000.0)
        pipeline, _, _, _ = _pipeline(tmp_path, limits=limits, clock=lambda: holder[0])
        _share(pipeline)
        pipeline.ingest(_frame_msg("kf-1"))
        assert pipeline.bind_commit(turn_id="t-1", visual={"source_id": "tab-main", "kind": "current"})[0] == "bound"
        pipeline.ingest(_frame_msg("kf-2"))
        assert pipeline.bind_commit(turn_id="t-2", visual={"source_id": "tab-main", "kind": "current"})[0] == "bound"
        holder[0] += 1.0
        # RET-04（真实策略）：缓存满时淘汰最旧未绑定帧；已绑定帧永不淘汰
        result = pipeline.ingest(_frame_msg("kf-3"))
        assert hasattr(result, "content_ref")
        assert pipeline._store.get("kf-1").retention_state is RetentionState.RETAINED  # noqa: SLF001
        assert pipeline._store.get("kf-2").retention_state is RetentionState.RETAINED  # noqa: SLF001
        stats = pipeline.observe()
        assert stats["store"]["unbound_retained"] == 1

    def test_frame_age_expires_after_limit(self, tmp_path):
        holder = [1000.0]
        limits = KeyframeLimits(min_interval_s=0.0, max_frame_age_s=30.0)
        pipeline, _, _, _ = _pipeline(tmp_path, limits=limits, clock=lambda: holder[0])
        _share(pipeline)
        pipeline.ingest(_frame_msg("kf-1"))
        holder[0] += 31.0
        assert pipeline.observe()["store"]["retained"] == 0
        with pytest.raises(KeyframeReadbackError):
            pipeline.readback("kf-1")


class TestPrivacy:
    def test_events_and_logs_contain_no_media_body(self, tmp_path, caplog):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        with caplog.at_level(logging.INFO, logger="llm_loop.realtime.keyframe_pipeline"):
            asyncio.run(runtime.handle_text(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1)))
            asyncio.run(runtime.handle_text(_msg("visual.frame", 2, **_frame_msg())))
        blob = "".join(text_out) + caplog.text
        assert PNG_B64 not in blob
        assert PNG_BYTES.decode("latin-1") not in blob
        assert "m3-e2e-frame-payload" not in blob  # 可重建画面的载荷内容
        assert len(caplog.records) >= 1  # 有观察日志，但只含机械事实

    def test_no_second_evidence_store(self, tmp_path):
        pipeline, artifacts, ws_root, _ = _pipeline(tmp_path)
        _share(pipeline)
        registered = pipeline.ingest(_frame_msg("kf-1"))
        # 工作区内只有一个回读入口文件；artifact 记录只有一条（唯一证据库）
        files = [p for p in ws_root.rglob("*") if p.is_file()]
        assert files == [ws_root / ".realtime" / "frames" / "ms-1" / "kf-1.png"]
        assert artifacts.read_bytes(registered.content_ref, workspace_scope=str(ws_root)) == PNG_BYTES


class _FakeMediaRegistry:
    """WS 归属登记替身：owns + `_by_id`（session_id / connection_epoch）。"""

    def __init__(self, *, owned=True, epoch=5) -> None:
        self.owned = owned
        self.record = SimpleNamespace(session_id="sess-1", connection_epoch=epoch)
        self._by_id = {"ms-1": self.record}

    def owns(self, media_session_id: str, *, session_cookie: str) -> bool:
        return self.owned and media_session_id == "ms-1"


def _ws_app(tmp_path, *, with_keyframes=True, epoch=5):
    app = FastAPI()
    store = WebSessionStore()
    app.state.web_sessions = store
    app.state.realtime_media_sessions = _FakeMediaRegistry(epoch=epoch)
    transport = FakeTransport()
    app.state.realtime_transport_factory = lambda: (transport, ASR_URL)
    if with_keyframes:
        ws_root = tmp_path / "ws-ws"
        ws_root.mkdir(exist_ok=True)
        app.state.realtime_keyframes = KeyframeServiceRegistry(
            artifact_store_factory=lambda: WorkspaceArtifactStore(tmp_path / "art-ws"),
            workspace_root_factory=lambda: str(ws_root),
        )
        tasks: list[object] = []
        app.state.realtime_commit_sink = lambda record: (tasks.append(record), "task-ws-1")[1]
    register_realtime_ws(app)
    return app, store


class TestWsWiring:
    def test_share_frame_commit_over_ws(self, tmp_path):
        app, store = _ws_app(tmp_path)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            REALTIME_WS_PATH.replace("{media_session_id}", "ms-1"),
            headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
        ) as ws:
            ws.send_text(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
            started = json.loads(ws.receive_text())
            assert started["type"] == "visual.share.started"
            assert started["reply_to"] == "e-1"

            ws.send_text(_msg("visual.frame", 2, **_frame_msg()))
            registered = json.loads(ws.receive_text())
            assert registered["type"] == "visual.frame.registered"
            assert registered["content_ref"].startswith("artifact://v1/")

            ws.send_text(
                _msg("input.commit", 3, visual={"source_id": "tab-main", "kind": "current"})
            )
            final = json.loads(ws.receive_text())
            committed = json.loads(ws.receive_text())
            assert final["type"] == "input.final"
            assert committed["type"] == "turn.committed"
            assert committed["evidence_refs"] == [registered["content_ref"]]
            assert committed["task_ref"] == "task-ws-1"
        # WS 断开 → 隐式 stop（当前失效，历史保留）
        pipeline = app.state.realtime_keyframes.pipeline_for(media_session_id="ms-1", session_id="sess-1")
        assert pipeline.active_sources() == ()
        assert pipeline._store.history("tab-main")  # noqa: SLF001 - 历史证据保留

    def test_stale_epoch_rejected_over_ws(self, tmp_path):
        app, store = _ws_app(tmp_path, epoch=5)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            REALTIME_WS_PATH.replace("{media_session_id}", "ms-1"),
            headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
        ) as ws:
            payload = json.loads(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
            payload["connection_epoch"] = 4  # 与登记 epoch=5 不符
            ws.send_text(json.dumps(payload))
            error = json.loads(ws.receive_text())
            assert error["type"] == "error"
            assert error["reason"] == "stale_epoch"

    def test_visual_unavailable_503_when_not_wired(self, tmp_path):
        app, store = _ws_app(tmp_path, with_keyframes=False)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            REALTIME_WS_PATH.replace("{media_session_id}", "ms-1"),
            headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
        ) as ws:
            ws.send_text(_msg("visual.frame", 1, **_frame_msg()))
            error = json.loads(ws.receive_text())
            assert error["type"] == "error"
            assert error["code"] == 503
            assert error["reason"] == "visual_unavailable"
            assert error["reply_to"] == "e-1"


class TestDeleteCleanupHook:
    def test_delete_session_expires_keyframes(self, tmp_path, monkeypatch):
        monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
        monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
        monkeypatch.setenv("WEB_HOST", "127.0.0.1")
        app = FastAPI()
        app.include_router(realtime_router)
        from llm_loop.realtime.media_registry import MediaSessionRegistry

        app.state.realtime_media_sessions = MediaSessionRegistry()
        ws_root = tmp_path / "ws-del"
        ws_root.mkdir()
        registry = KeyframeServiceRegistry(
            artifact_store_factory=lambda: WorkspaceArtifactStore(tmp_path / "art-del"),
            workspace_root_factory=lambda: str(ws_root),
        )
        app.state.realtime_keyframes = registry
        client = TestClient(app)
        created = client.post(
            "/api/v1/realtime/sessions",
            json={"session_id": "sess-1"},
            headers={"authorization": "Bearer tok-1"},
        ).json()
        media_session_id = created["media_session_id"]
        pipeline = registry.pipeline_for(media_session_id=media_session_id, session_id="sess-1")
        pipeline.share_start("tab-main", 1)
        registered = pipeline.ingest(_frame_msg("kf-1"))

        response = client.delete(
            f"/api/v1/realtime/sessions/{media_session_id}",
            headers={"authorization": "Bearer tok-1"},
        )
        assert response.status_code == 200
        with pytest.raises(KeyframeReadbackError):
            pipeline.readback("kf-1")  # 清理后回读明确失效
        assert registered.content_ref


class TestReviewP2Fixes:
    """审查 P2 修复回归：epoch 从 1 起 / 信封严格 + reply_to / 孤儿帧文件清理。"""

    # ---- P2-2：契约 §2.1 epoch 从 1 起，0/负数拒绝 -----------------------

    def test_share_start_epoch_zero_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        outcome, detail = pipeline.share_start("tab-main", 0, None)
        assert (outcome, detail["reason"]) == ("rejected", "malformed")
        assert pipeline.known_sources() == ()  # 无副作用

    def test_share_stop_epoch_zero_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline, epoch=1)
        outcome, detail = pipeline.share_stop("tab-main", 0)
        assert (outcome, detail["reason"]) == ("rejected", "malformed")

    def test_ingest_epoch_zero_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline, epoch=1)
        result = pipeline.ingest(_frame_msg("kf-e0", epoch=0))
        assert result.reason == "malformed"

    # ---- P2-3：version/epoch 布尔严格、event_id/seq 必填、reply_to ------

    def test_envelope_boolean_version_rejected(self, tmp_path):
        # True == 1 在 Python 成立，但契约要求 int：布尔不放行
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
        payload["version"] = True
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        assert _events(text_out)[-1]["reason"] == "unsupported_version"

    def test_envelope_boolean_epoch_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
        payload["connection_epoch"] = True
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        assert _events(text_out)[-1]["reason"] == "stale_epoch"

    def test_envelope_missing_event_id_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
        del payload["event_id"]
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        last = _events(text_out)[-1]
        assert last["reason"] == "malformed_envelope"
        assert "reply_to" not in last  # 无 event_id 可回带

    def test_envelope_missing_seq_rejected(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
        del payload["seq"]
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        assert _events(text_out)[-1]["reason"] == "malformed_envelope"

    def test_envelope_error_receipt_carries_reply_to(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(_msg("visual.share.start", 9, source_id="tab-main", source_epoch=1))
        payload["connection_epoch"] = 99
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        last = _events(text_out)[-1]
        assert last["reason"] == "stale_epoch"
        assert last["reply_to"] == "e-9"

    def test_commit_error_receipt_carries_reply_to(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        _share(pipeline)
        runtime, text_out, _, _ = _runtime(pipeline)
        payload = json.loads(
            _msg("input.commit", 7, visual={"source_id": "tab-main", "kind": "current"})
        )
        payload["connection_epoch"] = 99
        asyncio.run(runtime.handle_text(json.dumps(payload)))
        last = _events(text_out)[-1]
        assert last["reason"] == "stale_epoch"
        assert last["reply_to"] == "e-7"

    # ---- P2-5：artifact 登记失败清理孤儿帧文件，pipeline 不因此断连 -------

    def test_artifact_create_failure_cleans_orphan_file_and_stays_usable(self, tmp_path):
        class _FailingStore:
            def create(self, *args, **kwargs):  # noqa: ARG002 - 只模拟证据库故障
                raise RuntimeError("artifact store down")

        ws_root = tmp_path / "ws-boom"
        ws_root.mkdir()
        holder = [1000.0]
        boom = KeyframePipeline(
            media_session_id="ms-1",
            session_id="sess-1",
            artifact_store=_FailingStore(),
            workspace_root=ws_root,
            limits=KeyframeLimits(),
            now_fn=lambda: holder[0],
        )
        assert boom.share_start("tab-main", 1, None)[0] == "started"
        result = boom.ingest(_frame_msg("kf-boom"))
        assert result.reason == "artifact_store_failed"
        files = [p for p in ws_root.rglob("*") if p.is_file()]
        assert files == []  # 孤儿帧文件已清理，无回读入口

        # 证据库恢复后同工作区继续可用（一次失败不留下持久断连）
        healthy = KeyframePipeline(
            media_session_id="ms-1",
            session_id="sess-1",
            artifact_store=WorkspaceArtifactStore(tmp_path / "art-ok"),
            workspace_root=ws_root,
            limits=KeyframeLimits(),
            now_fn=lambda: holder[0],
        )
        assert healthy.share_start("tab-main", 1, None)[0] == "started"
        registered = healthy.ingest(_frame_msg("kf-ok"))
        assert registered.frame_id == "kf-ok"
        assert registered.content_ref


class _SpyPipeline(KeyframePipeline):
    """记录 bind_commit 调用（P2-9a：断言探测失败时未触发绑定）。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.bind_calls: list[dict] = []

    def bind_commit(self, **kwargs):
        self.bind_calls.append(kwargs)
        return super().bind_commit(**kwargs)


class TestReviewP2RoundTwo:
    """审查 P2 第二轮修复回归：PCM 成功才消费（4）/ registry 回收（6）/
    sink 会话存在性 + commit 前 probe（9a）。"""

    # ---- P2-4：bind 被拒/澄清/入队失败均保留 PCM，提交成功才消费 ----------

    def test_bind_rejected_keeps_pcm_buffer(self, tmp_path):
        holder = [1000.0]
        pipeline, _, _, _ = _pipeline(tmp_path, clock=lambda: holder[0])
        _share(pipeline)
        pipeline.ingest(_frame_msg("kf-1"))
        # 帧先被外部 turn 绑定 → 本次提交必 frame_already_bound
        assert (
            pipeline.bind_commit(turn_id="t-out", visual={"source_id": "tab-main", "kind": "current"})[0]
            == "bound"
        )
        runtime, text_out, _, sinks = _runtime(pipeline)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 1, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert [e["type"] for e in events] == ["input.final", "error"]
        assert events[-1]["code"] == 409
        assert events[-1]["reason"] == "frame_already_bound"
        assert runtime.buffered_bytes == 640  # P2-4：被拒不丢音频
        assert sinks == []  # 不派发任务

    def test_retained_pcm_retranscribed_nonempty_on_retry(self, tmp_path):
        holder = [1000.0]
        pipeline, _, _, _ = _pipeline(tmp_path, clock=lambda: holder[0])
        _share(pipeline)
        pipeline.ingest(_frame_msg("kf-1"))
        assert (
            pipeline.bind_commit(turn_id="t-out", visual={"source_id": "tab-main", "kind": "current"})[0]
            == "bound"
        )
        transport = FakeTransport()
        runtime, text_out, _, _ = _runtime(pipeline, transport=transport)
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 1, visual={"source_id": "tab-main", "kind": "current"}))
        )
        assert _events(text_out)[-1]["reason"] == "frame_already_bound"  # 首次被拒，音频保留
        # 新帧（推进时钟避开频控）→ 第二次提交绑定成功，转写保留的音频
        holder[0] += 1.0
        assert hasattr(pipeline.ingest(_frame_msg("kf-2")), "content_ref")
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert events[-1]["type"] == "turn.committed"
        assert len(transport.transcribed) == 2
        # 第二次终稿转写的是保留的同一音频：wav 非空（>44B 纯文件头，含 PCM 数据）
        assert 0 < len(transport.transcribed[1][1]) == len(transport.transcribed[0][1]) > 44
        assert runtime.buffered_bytes == 0  # 成功后才消费

    def test_clarify_keeps_pcm_buffer(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, sinks = _runtime(pipeline)
        _share(pipeline)  # 无帧：current → clarify
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 1, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert events[-1]["type"] == "visual.clarify"
        assert runtime.buffered_bytes == 640  # P2-4：澄清不丢音频
        assert sinks == []

    def test_sink_failure_keeps_pcm_buffer(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)

        def boom(record):  # noqa: ARG001 - 只模拟入队故障
            raise RuntimeError("queue down")

        runtime, text_out, _, _ = _runtime(pipeline, sink=boom)
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == 503
        assert events[-1]["reason"] == "task_submit_failed"
        assert runtime.buffered_bytes == 640  # P2-4：入队失败不丢音频

    # ---- P2-6：registry 关闭即移除条目（幂等、新实例不复用旧帧） ------------

    def _registry(self, tmp_path, *, tag: str):
        ws_root = tmp_path / f"ws-reg-{tag}"
        ws_root.mkdir()
        return KeyframeServiceRegistry(
            artifact_store_factory=lambda: WorkspaceArtifactStore(tmp_path / f"art-reg-{tag}"),
            workspace_root_factory=lambda: str(ws_root),
        )

    def test_registry_close_removes_pipeline_entry(self, tmp_path):
        registry = self._registry(tmp_path, tag="pop")
        pipeline = registry.pipeline_for(media_session_id="ms-1", session_id="sess-1")
        _share(pipeline)
        assert hasattr(pipeline.ingest(_frame_msg("kf-1")), "content_ref")
        assert registry.close_session("ms-1") == 1
        # registry 不再持有旧条目：同 id 返回全新实例（不复用旧帧）
        fresh = registry.pipeline_for(media_session_id="ms-1", session_id="sess-1")
        assert fresh is not pipeline
        assert fresh.known_sources() == ()
        assert not fresh._store.history("tab-main")  # noqa: SLF001 - 新实例无旧帧
        # 旧实例语义不变：已关闭、回读明确失效（Expired 元数据仍在旧实例内保留）
        with pytest.raises(KeyframeReadbackError):
            pipeline.readback("kf-1")

    def test_registry_close_unknown_id_returns_zero(self, tmp_path):
        registry = self._registry(tmp_path, tag="unknown")
        assert registry.close_session("ms-never") == 0

    def test_registry_close_twice_idempotent(self, tmp_path):
        registry = self._registry(tmp_path, tag="twice")
        pipeline = registry.pipeline_for(media_session_id="ms-1", session_id="sess-1")
        _share(pipeline)
        pipeline.ingest(_frame_msg("kf-1"))
        assert registry.close_session("ms-1") == 1
        assert registry.close_session("ms-1") == 0  # 重复关闭不抛错、返回 0

    # ---- P2-9a：commit 前 session_probe（runtime 层） -----------------------

    def test_session_probe_failure_409_wrong_session_without_bind(self, tmp_path):
        ws_root = tmp_path / "ws-probe"
        ws_root.mkdir()
        spy = _SpyPipeline(
            media_session_id="ms-1",
            session_id="sess-1",
            artifact_store=WorkspaceArtifactStore(tmp_path / "art-probe"),
            workspace_root=ws_root,
        )
        probed: list[str] = []
        runtime, text_out, _, sinks = _runtime(
            spy, session_probe=lambda sid: (probed.append(sid), False)[1]
        )
        _share(spy)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "error"]
        assert events[-1]["code"] == 409
        assert events[-1]["reason"] == "wrong_session"
        assert events[-1]["reply_to"] == "e-2"
        assert probed == ["sess-1"]  # 探测的是目标会话 id
        assert spy.bind_calls == []  # bind_commit 未被调用
        assert sinks == []  # 未入队
        assert runtime.buffered_bytes == 640  # 音频保留

    def test_session_probe_success_keeps_commit_flow(self, tmp_path):
        pipeline, _, _, _ = _pipeline(tmp_path)
        runtime, text_out, _, sinks = _runtime(
            pipeline, session_probe=lambda sid: sid == "sess-1"
        )
        _share(pipeline)
        asyncio.run(runtime.handle_text(_msg("visual.frame", 1, **_frame_msg())))
        asyncio.run(runtime.handle_binary(b"\x00\x00" * 320))
        asyncio.run(
            runtime.handle_text(_msg("input.commit", 2, visual={"source_id": "tab-main", "kind": "current"}))
        )
        events = _events(text_out)
        assert [e["type"] for e in events] == ["visual.frame.registered", "input.final", "turn.committed"]
        assert sinks  # 探测通过：正常派发
        assert runtime.buffered_bytes == 0

    # ---- P2-9a：WS 构造处注入 probe（装配层） --------------------------------

    def test_ws_commit_unknown_engine_session_409_wrong_session(self, tmp_path):
        app, store = _ws_app(tmp_path)
        # 生产装配（build_app）必有 app.state.engine；此处注入"sess-1 不存在"
        app.state.engine = SimpleNamespace(session=SimpleNamespace(exists=lambda sid: False))
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            REALTIME_WS_PATH.replace("{media_session_id}", "ms-1"),
            headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
        ) as ws:
            ws.send_text(_msg("visual.share.start", 1, source_id="tab-main", source_epoch=1))
            ws.receive_text()
            ws.send_text(_msg("visual.frame", 2, **_frame_msg()))
            ws.receive_text()
            ws.send_text(
                _msg("input.commit", 3, visual={"source_id": "tab-main", "kind": "current"})
            )
            error = json.loads(ws.receive_text())
            assert error["type"] == "error"
            assert error["code"] == 409
            assert error["reason"] == "wrong_session"
