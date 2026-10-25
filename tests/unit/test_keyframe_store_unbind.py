"""P2-1：sink 失败时回滚 keyframe 绑定，解除视觉轮次死锁（红→绿回归）。

缺陷：``_finalize_with_visual`` 先 ``bind_commit`` 后 ``commit_sink``；sink 抛异常时
帧已永久绑定到 doomed turn_id，重试拿新 turn_id → ``frame_already_bound``，该视觉
轮次彻底走死。修复契约：

- ``KeyframeStore.unbind(frame_id, *, turn_id)``：仅当帧当前恰好绑定到给定
  ``turn_id`` 时才释放并返回 True；不匹配/未知/未绑定 → False（不抛、幂等）；
- runtime：sink 抛异常 → 先回滚本次绑定再走既有 503 ``task_submit_failed``
  错误面；sink 成功 → 绑定保持。
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from llm_loop.realtime.keyframe import (
    Keyframe,
    KeyframeReadbackError,
    RetentionState,
)
from llm_loop.realtime.keyframe_pipeline import KeyframePipeline
from llm_loop.realtime.keyframe_store import KeyframeStore
from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime
from llm_loop.workspace.artifacts import WorkspaceArtifactStore

REF_A = "artifact://v1/" + "a" * 32
REF_B = "artifact://v1/" + "b" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"p2-1-unbind-frame" + b"\x00" * 8
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


def _frame(frame_id: str, source_id: str = "tab-1", *, ref: str = REF_A) -> Keyframe:
    return Keyframe(
        frame_id=frame_id,
        source_id=source_id,
        source_epoch=1,
        captured_at_client_monotonic_s=100.0,
        received_at_s=100.1,
        width=1280,
        height=720,
        content_ref=ref,
    )


def _frame_msg(frame_id: str = "kf-1", *, source_id: str = "tab-main") -> dict:
    return {
        "frame_id": frame_id,
        "source_id": source_id,
        "source_epoch": 1,
        "captured_at_ms": 1500,
        "width": 1280,
        "height": 720,
        "mime": "image/png",
        "data_b64": PNG_B64,
    }


class _Transport:
    def append(self, frame: bytes) -> None:  # noqa: ARG002 - 最小替身
        pass

    def transcribe(self, url: str, segment: bytes) -> str:  # noqa: ARG002
        return ""

    def synthesize(self, text: str) -> bytes:  # noqa: ARG002
        return b""

    def close(self) -> None:
        pass


def _pipeline(tmp_path) -> KeyframePipeline:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    pipeline = KeyframePipeline(
        media_session_id="ms-1",
        session_id="sess-1",
        artifact_store=WorkspaceArtifactStore(tmp_path / "art"),
        workspace_root=ws_root,
    )
    pipeline.share_start("tab-main", 1)
    assert hasattr(pipeline.ingest(_frame_msg("kf-1")), "content_ref")
    return pipeline


def _runtime(pipeline: KeyframePipeline, *, sink, epoch: int):
    text_out: list[str] = []

    async def send_text(payload: str) -> None:
        text_out.append(payload)

    async def send_binary(payload: bytes) -> None:  # noqa: ARG001 - 本用例无下行二进制
        pass

    runtime = RealtimeSessionRuntime(
        media_session_id="ms-1",
        session_id="sess-1",
        transport=_Transport(),  # type: ignore[arg-type]
        transcription_url="http://127.0.0.1:8000/v1/audio/transcriptions",
        send_text=send_text,
        send_binary=send_binary,
        connection_epoch=epoch,
        keyframes=pipeline,
        commit_sink=sink,
    )
    return runtime, text_out


def _commit(seq: int, *, epoch: int) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": "input.commit",
            "event_id": f"e-{seq}",
            "seq": seq,
            "connection_epoch": epoch,
            "session_id": "sess-1",
            "media_session_id": "ms-1",
            "visual": {"source_id": "tab-main", "kind": "current"},
        }
    )


class TestKeyframeStoreUnbind:
    def test_unbind_matching_turn_releases_and_allows_rebind(self):
        # (a) 核心回归：精确 turn_id 匹配 → 释放，随后可用新 turn_id 重新绑定
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.bind("f1", turn_id="turn-1")
        assert store.unbind("f1", turn_id="turn-1") is True
        assert store.is_bound("f1") is False
        assert store.bind("f1", turn_id="turn-2").frame_id == "f1"

    def test_unbind_wrong_turn_is_noop(self):
        # (b) turn_id 不匹配 → no-op：原绑定不动，互斥语义不变
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.bind("f1", turn_id="turn-1")
        assert store.unbind("f1", turn_id="turn-2") is False
        assert store.is_bound("f1") is True
        with pytest.raises(ValueError):
            store.bind("f1", turn_id="turn-2")

    def test_unbind_unknown_or_unbound_frame_is_noop(self):
        # (c) 未绑定/未知 frame → no-op 不抛；重复解绑幂等
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        assert store.unbind("missing", turn_id="turn-1") is False
        assert store.unbind("f1", turn_id="turn-1") is False
        store.bind("f1", turn_id="turn-1")
        assert store.unbind("f1", turn_id="turn-1") is True
        assert store.unbind("f1", turn_id="turn-1") is False

    def test_unbind_does_not_resurrect_expired_frame(self):
        # 不复活已过期帧：解绑只移除绑定登记，retention 不回退
        store = KeyframeStore()
        store.register(_frame("f1", "tab-1"))
        store.bind("f1", turn_id="turn-1")
        store.expire("f1")  # Bound→Expired 是 §2.1.3-F 允许的迁移
        assert store.unbind("f1", turn_id="turn-1") is True
        assert store.is_bound("f1") is False
        assert store.get("f1").retention_state is RetentionState.EXPIRED
        with pytest.raises(KeyframeReadbackError):
            store.readback_ref("f1")


class TestPipelineUnbindCommit:
    def test_unbind_commit_releases_only_matching_turn(self, tmp_path):
        pipeline = _pipeline(tmp_path)
        outcome, _ = pipeline.bind_commit(
            turn_id="t-1", visual={"source_id": "tab-main", "kind": "current"}
        )
        assert outcome == "bound"
        assert pipeline.unbind_commit(turn_id="t-2", frame_ids=["kf-1"]) == 0  # 不匹配：不释放
        assert pipeline._store.is_bound("kf-1") is True  # noqa: SLF001 - 观察绑定事实
        assert pipeline.unbind_commit(turn_id="t-1", frame_ids=["kf-1"]) == 1
        assert pipeline._store.is_bound("kf-1") is False  # noqa: SLF001
        # 回滚后同帧可随新 turn 重新绑定提交（视觉轮次不再走死）
        outcome, _ = pipeline.bind_commit(
            turn_id="t-2", visual={"source_id": "tab-main", "kind": "current"}
        )
        assert outcome == "bound"


class TestRuntimeSinkFailureRollback:
    def test_sink_failure_rolls_back_binding_and_retry_succeeds(self, tmp_path):
        # (d) sink 抛异常 → 帧不残留绑定；新 turn_id 重试同帧成功
        pipeline = _pipeline(tmp_path)

        def boom(record) -> str:  # noqa: ARG001 - 只模拟入队故障
            raise RuntimeError("queue down")

        runtime, text_out = _runtime(pipeline, sink=boom, epoch=1)
        asyncio.run(runtime.handle_text(_commit(1, epoch=1)))
        events = [json.loads(payload) for payload in text_out]
        assert [e["type"] for e in events] == ["input.final", "error"]
        assert events[-1]["code"] == 503
        assert events[-1]["reason"] == "task_submit_failed"  # 既有错误面不变
        assert pipeline._store.is_bound("kf-1") is False  # noqa: SLF001 - 核心断言
        # 新连接代次 = 新 turn_id：重试同帧 → 绑定成功并派发任务
        ok_runtime, ok_out = _runtime(pipeline, sink=lambda record: "task-9", epoch=2)
        asyncio.run(ok_runtime.handle_text(_commit(2, epoch=2)))
        ok_events = [json.loads(payload) for payload in ok_out]
        assert ok_events[-1]["type"] == "turn.committed"
        assert ok_events[-1]["visual"][0]["frame_id"] == "kf-1"
        assert pipeline._store.is_bound("kf-1") is True  # noqa: SLF001

    def test_sink_success_keeps_binding(self, tmp_path):
        # (e) sink 成功 → 绑定保持；互斥不变量不受回滚能力影响
        pipeline = _pipeline(tmp_path)
        runtime, text_out = _runtime(pipeline, sink=lambda record: "task-9", epoch=1)
        asyncio.run(runtime.handle_text(_commit(1, epoch=1)))
        events = [json.loads(payload) for payload in text_out]
        assert events[-1]["type"] == "turn.committed"
        assert pipeline._store.is_bound("kf-1") is True  # noqa: SLF001
        outcome, detail = pipeline.bind_commit(
            turn_id="t-other", visual={"source_id": "tab-main", "kind": "current"}
        )
        assert (outcome, detail) == ("rejected", "frame_already_bound")
