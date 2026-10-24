"""M1 代理实装：实时会话运行时测试（上行帧 → 终稿 → TTS 下行）。

覆盖 RTM：SES-07、AUD-01、INP-01/02/09、PLY-07、CAP-11/12/14。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime, pcm16_to_wav

ASR_URL = "http://127.0.0.1:8000/v1/audio/transcriptions"


class FakeTransport:
    def __init__(self, *, text: str = "逐字正确的终稿", audio: bytes = b"WAVAUDIO") -> None:
        self.text = text
        self.audio = audio
        self.appended: list[bytes] = []
        self.transcribed: list[tuple[str, bytes]] = []
        self.synthesized: list[str] = []
        self.closed = False

    def append(self, frame: bytes) -> None:
        self.appended.append(frame)

    def transcribe(self, url: str, segment: bytes) -> str:
        self.transcribed.append((url, segment))
        return self.text

    def synthesize(self, text: str) -> bytes:
        self.synthesized.append(text)
        return self.audio

    def close(self) -> None:
        self.closed = True


def _runtime(transport: FakeTransport, **overrides):
    text_out: list[str] = []
    binary_out: list[bytes] = []

    async def send_text(payload: str) -> None:
        text_out.append(payload)

    async def send_binary(payload: bytes) -> None:
        binary_out.append(payload)

    runtime = RealtimeSessionRuntime(
        media_session_id="ms-1",
        session_id="sess-1",
        transport=transport,  # type: ignore[arg-type]
        transcription_url=ASR_URL,
        send_text=send_text,
        send_binary=send_binary,
        **overrides,
    )
    return runtime, text_out, binary_out


def _events(text_out: list[str]) -> list[dict]:
    return [json.loads(payload) for payload in text_out]


def _run(coro):
    return asyncio.run(coro)


class TestAudioFrames:
    def test_frames_are_buffered_and_forwarded(self):
        transport = FakeTransport()
        runtime, _, _ = _runtime(transport)
        _run(runtime.handle_binary(b"\x00\x00" * 160))
        assert runtime.buffered_bytes == 320
        assert len(transport.appended) == 1

    def test_unaligned_frame_rejected(self):
        # P2-1：奇数字节帧显式拒绝（有界 error 事件），连接保持打开
        runtime, text_out, _ = _runtime(FakeTransport())
        _run(runtime.handle_binary(b"\x00"))
        events = _events(text_out)
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == 400
        assert events[-1]["reason"] == "malformed_frame"
        assert runtime.buffered_bytes == 0
        # 连接未被断开：后续合法帧仍正常累积
        _run(runtime.handle_binary(b"\x00\x00" * 160))
        assert runtime.buffered_bytes == 320

    def test_streaming_forward_failure_does_not_block(self):
        class BoomTransport(FakeTransport):
            def append(self, frame: bytes) -> None:
                raise RuntimeError("streaming down")

        runtime, _, _ = _runtime(BoomTransport())
        _run(runtime.handle_binary(b"\x00\x00" * 160))  # 不抛
        assert runtime.buffered_bytes == 320


class TestPcmRunwayLimits:
    """P1-3：_pcm 字节+时间双限（RTM-RET-04 / D12）。"""

    def _capacity_runtime(self, *, max_bytes=None, max_seconds=None, clock=None):
        transport = FakeTransport()
        overrides: dict = {}
        if max_bytes is not None:
            overrides["max_pcm_bytes"] = max_bytes
        if max_seconds is not None:
            overrides["max_pcm_seconds"] = max_seconds
        if clock is not None:
            overrides["now_fn"] = clock
        runtime, text_out, _ = _runtime(transport, **overrides)
        return runtime, transport, text_out

    def test_byte_limit_exceeded_drops_buffer_with_bounded_error(self):
        runtime, transport, text_out = self._capacity_runtime(max_bytes=64)
        _run(runtime.handle_binary(b"\x00\x00" * 40))  # 80B > 64B：超限
        events = _events(text_out)
        assert events[-1]["type"] == "error"
        assert events[-1]["reason"] == "capacity_exceeded"
        assert events[-1]["detail"] == "pcm_buffer_bytes_exceeded"
        assert events[-1]["code"] == 413
        assert runtime.buffered_bytes == 0  # 超限即丢整段
        assert runtime.capacity_exceeded_count == 1
        # 恢复：后续帧重新累积（无需断开重连）
        _run(runtime.handle_binary(b"\x00\x00" * 8))
        assert runtime.buffered_bytes == 16
        assert runtime.capacity_exceeded_count == 1

    def test_time_window_limit_exceeded_emits_capacity_error(self):
        holder = [0.0]
        runtime, _, text_out = self._capacity_runtime(max_seconds=5.0, clock=lambda: holder[0])
        _run(runtime.handle_binary(b"\x00\x00" * 10))
        holder[0] = 6.0  # 窗口已过 5s
        _run(runtime.handle_binary(b"\x00\x00" * 10))
        events = _events(text_out)
        assert events[-1]["type"] == "error"
        assert events[-1]["reason"] == "capacity_exceeded"
        assert events[-1]["detail"] == "pcm_buffer_window_exceeded"
        assert runtime.buffered_bytes == 0
        assert runtime.capacity_exceeded_count == 1

    def test_within_limits_no_error_and_window_resets_after_commit(self):
        holder = [0.0]
        runtime, transport, text_out = self._capacity_runtime(
            max_seconds=5.0, clock=lambda: holder[0]
        )
        _run(runtime.handle_binary(b"\x00\x00" * 10))
        holder[0] = 4.0  # 窗口内：不超限
        _run(runtime.handle_binary(b"\x00\x00" * 10))
        assert [e["type"] for e in _events(text_out)] == []
        assert runtime.buffered_bytes == 40
        # commit 即消费：窗口与缓存重置，之后按新窗口继续
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        assert runtime.buffered_bytes == 0
        holder[0] = 12.0  # 旧窗口若未重置，此处必超限
        _run(runtime.handle_binary(b"\x00\x00" * 10))
        assert [e["type"] for e in _events(text_out)] == ["input.final", "turn.committed"]

    def test_stop_clears_runway_buffer(self):
        runtime, _, _ = self._capacity_runtime(max_bytes=64)
        _run(runtime.handle_binary(b"\x00\x00" * 10))
        assert runtime.buffered_bytes == 20
        runtime.stop()
        assert runtime.buffered_bytes == 0

    def test_defaults_are_bounded(self):
        # 默认装配即有界（4MB / 60s），不带上限的连接不存在无界增长
        import inspect

        signature = inspect.signature(RealtimeSessionRuntime.__init__)
        assert signature.parameters["max_pcm_bytes"].default == 4 * 1024 * 1024
        assert signature.parameters["max_pcm_seconds"].default == 60.0


class TestFinalize:
    def test_commit_transcribes_and_emits_final_and_committed(self):
        transport = FakeTransport(text="语音链路")
        runtime, text_out, _ = _runtime(transport)
        _run(runtime.handle_binary(b"\x00\x00" * 320))
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        assert len(transport.transcribed) == 1
        assert transport.transcribed[0][0] == ASR_URL
        events = [json.loads(payload) for payload in text_out]
        types = [event["type"] for event in events]
        assert types == ["input.final", "turn.committed"]
        assert events[0]["text"] == "语音链路"
        assert runtime.buffered_bytes == 0  # 提交后清空

    def test_envelope_has_required_fields(self):
        runtime, text_out, _ = _runtime(FakeTransport())
        _run(runtime.handle_binary(b"\x00\x00" * 320))
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        envelope = json.loads(text_out[0])
        for field in ("version", "type", "event_id", "seq", "connection_epoch", "session_id", "media_session_id", "turn_id"):
            assert envelope.get(field) is not None, field
        assert envelope["connection_epoch"] == 1
        assert envelope["seq"] == 1

    def test_empty_audio_commits_empty_text(self):
        transport = FakeTransport()
        runtime, text_out, _ = _runtime(transport)
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        assert transport.transcribed == []  # 空音频不调终稿
        assert json.loads(text_out[0])["text"] == ""

    def test_wav_wrapper_is_valid(self):
        wav = pcm16_to_wav(b"\x00\x00" * 100)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"

    def test_wav_rejects_unaligned_pcm(self):
        with pytest.raises(ValueError):
            pcm16_to_wav(b"\x00")


class TestTtsDownlink:
    def test_tts_request_synthesizes_and_sends_binary(self):
        transport = FakeTransport(audio=b"TTSBYTES")
        runtime, text_out, binary_out = _runtime(transport)
        _run(runtime.handle_text(json.dumps({"type": "tts.request", "text": "你好", "response_id": "r1"})))
        assert transport.synthesized == ["你好"]
        assert binary_out == [b"TTSBYTES"]
        assert json.loads(text_out[0])["type"] == "audio.playback"

    def test_unknown_event_ignored(self):
        runtime, text_out, binary_out = _runtime(FakeTransport())
        _run(runtime.handle_text(json.dumps({"type": "unknown.event"})))
        assert text_out == [] and binary_out == []

    def test_no_response_create_ever_emitted(self):
        transport = FakeTransport()
        runtime, text_out, _ = _runtime(transport)
        _run(runtime.handle_binary(b"\x00\x00" * 320))
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        rendered = " ".join(text_out)
        assert "response.create" not in rendered


class _FakeKeyframes:
    """最小视觉链替身：校验恒过、bind 恒 bound（聚焦运行时缓冲守卫本身）。"""

    def __init__(self) -> None:
        self.bound: list[str] = []

    def validate_commit_visual(self, visual: object) -> str:
        return ""

    def bind_commit(self, *, turn_id: str, visual: object, text: str):
        self.bound.append(turn_id)
        evidence = SimpleNamespace(
            content_ref="artifact://v1/" + "f" * 32,
            to_public_dict=lambda: {"frame_id": "kf-1"},
        )
        return "bound", (evidence,)


def _ok_sink(record: object) -> str:  # noqa: ARG001 - 断言只需成功入队
    return "task-9"


class _InjectingTransport(FakeTransport):
    """转写回调返回前，先经事件循环向运行时注入并发帧（模拟 await 期间新音频）。"""

    def __init__(self, frames: list[bytes]) -> None:
        super().__init__(text="终稿照常")
        self.frames = frames
        self.runtime: RealtimeSessionRuntime | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def transcribe(self, url: str, segment: bytes) -> str:
        assert self.runtime is not None and self.loop is not None
        for frame in self.frames:
            asyncio.run_coroutine_threadsafe(self.runtime.handle_binary(frame), self.loop).result()
        self.transcribed.append((url, segment))
        return self.text


def _visual_commit(seq: int = 1) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": "input.commit",
            "event_id": f"e-{seq}",
            "seq": seq,
            "connection_epoch": 1,
            "session_id": "sess-1",
            "media_session_id": "ms-1",
            "visual": {"source_id": "tab-main", "kind": "current"},
        }
    )


class TestCommitBufferGenerationGuard:
    """缺陷①回归：await 期间 413 清空缓冲后，成功提交的前缀删除不得吃掉新音频。"""

    def test_overflow_clear_during_await_keeps_new_audio(self):
        # 反例先行锚定：旧实现在此会 del[:len(segment)]，把 16B 新音频全删掉。
        new_audio = b"\x11\x22" * 8  # 16B：清空后到达的"新说的话"

        async def scenario() -> tuple[RealtimeSessionRuntime, list[str], _InjectingTransport]:
            loop = asyncio.get_running_loop()
            transport = _InjectingTransport(
                frames=[b"\x00\x01" * 30, new_audio]  # 60B 触发 413 整段清空 → 16B 新音频
            )
            runtime, text_out, _ = _runtime(
                transport, max_pcm_bytes=64, keyframes=_FakeKeyframes(), commit_sink=_ok_sink
            )
            transport.runtime = runtime
            transport.loop = loop
            await runtime.handle_binary(b"\x00\x01" * 20)  # 40B 待提交音频（< 64）
            await runtime.handle_text(_visual_commit())  # ② 不抛
            return runtime, text_out, transport

        runtime, text_out, transport = _run(scenario())
        events = _events(text_out)
        # ③ 413 先行（await 期间触发），随后终稿链路照常走完
        assert [e["type"] for e in events] == ["error", "input.final", "turn.committed"]
        assert events[0]["code"] == 413
        assert events[0]["reason"] == "capacity_exceeded"
        assert events[0]["buffered_bytes"] == 100  # 40B 旧音频 + 60B 触发帧整段丢弃
        assert events[-1]["task_ref"] == "task-9"
        assert runtime.capacity_exceeded_count == 1
        # ① 新音频完好保留：长度与内容均为清空后到达的那帧（未被前缀删除吃掉）
        assert runtime.buffered_bytes == 16
        assert bytes(runtime._pcm) == new_audio  # noqa: SLF001 - 断言"新说的话"原样保留
        assert runtime._pcm_started is not None  # noqa: SLF001 - 新窗口在累积
        # 终稿转写的是删除前快照（旧 40B 音频），与新音频无关
        assert len(transport.transcribed) == 1
        assert len(transport.transcribed[0][1]) == 44 + 40  # WAV 头 44B + PCM

    def test_no_overflow_prefix_delete_keeps_only_new_frames(self):
        # 无溢出反例：代次未变 → 正常按快照长度删前缀，只剩 await 期间新到的帧
        async def scenario() -> tuple[RealtimeSessionRuntime, list[str]]:
            loop = asyncio.get_running_loop()
            follow_up = b"\x33\x44" * 4  # 8B，不触发溢出
            transport = _InjectingTransport(frames=[follow_up])
            runtime, text_out, _ = _runtime(
                transport, max_pcm_bytes=64, keyframes=_FakeKeyframes(), commit_sink=_ok_sink
            )
            transport.runtime = runtime
            transport.loop = loop
            await runtime.handle_binary(b"\x00\x01" * 10)  # 20B
            await runtime.handle_text(_visual_commit())
            return runtime, text_out

        runtime, text_out = _run(scenario())
        assert [e["type"] for e in _events(text_out)] == ["input.final", "turn.committed"]
        assert runtime.buffered_bytes == 8  # 28B - 20B 快照
        assert bytes(runtime._pcm) == b"\x33\x44" * 4  # noqa: SLF001

    def test_commit_success_empties_buffer_and_resets_window(self):
        # 无反例：无并发注入时，成功提交后缓冲为空、累积窗口复位
        async def scenario() -> tuple[RealtimeSessionRuntime, list[str]]:
            runtime, text_out, _ = _runtime(
                FakeTransport(), keyframes=_FakeKeyframes(), commit_sink=_ok_sink
            )
            await runtime.handle_binary(b"\x00\x01" * 10)
            await runtime.handle_text(_visual_commit())
            return runtime, text_out

        runtime, text_out = _run(scenario())
        assert [e["type"] for e in _events(text_out)] == ["input.final", "turn.committed"]
        assert runtime.buffered_bytes == 0
        assert runtime._pcm_started is None  # noqa: SLF001
