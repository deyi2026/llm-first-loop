"""M1 代理实装：实时会话运行时测试（上行帧 → 终稿 → TTS 下行）。

覆盖 RTM：SES-07、AUD-01、INP-01/02/09、PLY-07、CAP-11/12/14。
"""

from __future__ import annotations

import asyncio
import json
import threading

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


def _runtime(transport: FakeTransport):
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
    )
    return runtime, text_out, binary_out


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
        runtime, _, _ = _runtime(FakeTransport())
        with pytest.raises(ValueError):
            _run(runtime.handle_binary(b"\x00"))

    def test_streaming_forward_failure_does_not_block(self):
        class BoomTransport(FakeTransport):
            def append(self, frame: bytes) -> None:
                raise RuntimeError("streaming down")

        runtime, _, _ = _runtime(BoomTransport())
        _run(runtime.handle_binary(b"\x00\x00" * 160))  # 不抛
        assert runtime.buffered_bytes == 320


class TestFinalize:
    def test_commit_transcribes_but_does_not_claim_chat_was_committed(self):
        transport = FakeTransport(text="语音链路")
        runtime, text_out, _ = _runtime(transport)
        _run(runtime.handle_binary(b"\x00\x00" * 320))
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        assert len(transport.transcribed) == 1
        assert transport.transcribed[0][0] == ASR_URL
        events = [json.loads(payload) for payload in text_out]
        types = [event["type"] for event in events]
        # ASR completion is not evidence that chat ingress accepted a human turn.
        assert types == ["input.final"]
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

    def test_empty_audio_emits_no_fabricated_final(self):
        transport = FakeTransport()
        runtime, text_out, _ = _runtime(transport)
        _run(runtime.handle_text(json.dumps({"type": "input.commit"})))
        assert transport.transcribed == []  # 空音频不调终稿
        assert text_out == []

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

        async def send_and_finish():
            await runtime.handle_text(json.dumps({"type": "tts.request", "text": "你好", "response_id": "r1"}))
            assert runtime._tts_task is not None
            await runtime._tts_task

        _run(send_and_finish())
        assert transport.synthesized == ["你好"]
        assert binary_out == [b"TTSBYTES"]
        assert json.loads(text_out[0])["type"] == "audio.playback"

    def test_cancel_pending_tts_cannot_emit_stale_audio(self):
        ready = threading.Event()
        done = threading.Event()

        class SlowTransport(FakeTransport):
            def synthesize(self, text: str) -> bytes:
                ready.set()
                assert done.wait(timeout=2)
                return b"STALE_AUDIO"

        runtime, text_out, binary_out = _runtime(SlowTransport())

        async def cancel_during_synthesis():
            await runtime.handle_text(json.dumps({"type": "tts.request", "text": "旧回复", "response_id": "r-old"}))
            assert await asyncio.to_thread(ready.wait, 2)
            await runtime.handle_text(json.dumps({"type": "tts.cancel"}))
            done.set()
            await asyncio.sleep(0.02)

        _run(cancel_during_synthesis())
        assert text_out == []
        assert binary_out == []

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
