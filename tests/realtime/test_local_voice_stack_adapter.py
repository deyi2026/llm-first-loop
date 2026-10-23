"""T-CONTRACT-3 / T-CONTRACT-3D：本地转写适配器（D1）与远端预留（D2）单元测试。

覆盖 RTM：CAP-01/05/11/12/14、AUD-01、INP-09、REC-05、SEC-08。

核心断言：
- **仅转写**：全流程不出现 `response.create`；
- `append` 是受理回执，**已受理 ≠ 已转写**；
- 参数来自能力档案（16k / 单声道 / pcm16），帧格式校验；
- `flush_close` 必须 flush；`close` 缺用量 → `incomplete`；
- 无远端恢复令牌 → 本地重建；
- **D2 仅预留 Protocol、无任何实现**。
"""

from __future__ import annotations

import pytest

from llm_loop.realtime import provider_adapter as pa
from llm_loop.realtime.local_voice_stack_adapter import LocalVoiceStackAdapter
from llm_loop.realtime.media_usage import UsageStatus
from llm_loop.realtime.provider_adapter import (
    AudioFormat,
    LocalStackProfile,
    RealtimeProviderAdapter,
    RecoveryMode,
    TranscriptionEvent,
    TranscriptionEventKind,
)

WS_URL = "ws://127.0.0.1:8000/v1/realtime"
ASR_URL = "http://127.0.0.1:8000/v1/audio/transcriptions"


def _profile(**over: object) -> LocalStackProfile:
    base: dict[str, object] = {
        "realtime_ws_url": WS_URL,
        "transcription_http_url": ASR_URL,
    }
    base.update(over)
    return LocalStackProfile(**base)  # type: ignore[arg-type]


class FakeTransport:
    def __init__(self, events: list[TranscriptionEvent] | None = None, final_text: str = "终稿") -> None:
        self.calls: list[tuple] = []
        self._events = list(events or [])
        self._final_text = final_text

    def connect(self, url: str) -> None:
        self.calls.append(("connect", url))

    def configure(self, *, sample_rate_hz: int, channels: int, audio_format: str) -> None:
        self.calls.append(("configure", sample_rate_hz, channels, audio_format))

    def append(self, frame: bytes) -> None:
        self.calls.append(("append", len(frame)))

    def commit(self) -> None:
        self.calls.append(("commit",))

    def next_event(self) -> TranscriptionEvent | None:
        self.calls.append(("next_event",))
        return self._events.pop(0) if self._events else None

    def transcribe(self, url: str, segment: bytes) -> str:
        self.calls.append(("transcribe", url, len(segment)))
        return self._final_text

    def flush(self) -> None:
        self.calls.append(("flush",))

    def close(self) -> None:
        self.calls.append(("close",))

    def caller_names(self) -> set[str]:
        return {str(call[0]) for call in self.calls}


def _opened(transport: FakeTransport | None = None) -> tuple[LocalVoiceStackAdapter, FakeTransport]:
    transport = transport or FakeTransport()
    adapter = LocalVoiceStackAdapter(transport)
    adapter.open(_profile())
    return adapter, transport


class TestOpenConfigure:
    def test_open_uses_loopback_url_from_profile(self):
        adapter, transport = _opened()
        assert adapter.ready is True
        assert transport.calls[0] == ("connect", WS_URL)

    def test_open_configures_16k_mono_pcm16_from_profile(self):
        _, transport = _opened()
        assert ("configure", 16000, 1, "pcm16") in transport.calls

    def test_configure_without_open_raises(self):
        adapter = LocalVoiceStackAdapter(FakeTransport())
        with pytest.raises(RuntimeError):
            adapter.configure()

    def test_reconfigure_uses_explicit_values(self):
        adapter, transport = _opened()
        adapter.configure(sample_rate_hz=8000, channels=2)
        assert ("configure", 8000, 2, "pcm16") in transport.calls

    def test_rejects_invalid_configure_values(self):
        adapter, _ = _opened()
        with pytest.raises(ValueError):
            adapter.configure(sample_rate_hz=0)
        with pytest.raises(ValueError):
            adapter.configure(channels=-1)


class TestAppendAndCommit:
    def test_append_returns_receipt_not_transcription(self):
        adapter, transport = _opened()
        receipt = adapter.append(b"\x00" * 640)
        assert receipt.accepted is True
        assert receipt.bytes_accepted == 640
        # 无转写事件被消费：受理 ≠ 已转写
        assert "next_event" not in transport.caller_names()

    def test_append_before_open_raises(self):
        adapter = LocalVoiceStackAdapter(FakeTransport())
        with pytest.raises(RuntimeError):
            adapter.append(b"\x00" * 640)

    def test_append_rejects_empty_unaligned_and_oversized(self):
        adapter, _ = _opened()
        with pytest.raises(ValueError):
            adapter.append(b"")
        with pytest.raises(ValueError):
            adapter.append(b"\x00")  # 1 字节，非 PCM16 对齐
        with pytest.raises(ValueError):
            adapter.append(b"\x00" * 6401)  # 超过 max_frame_bytes(6400)

    def test_append_rejects_non_bytes(self):
        adapter, _ = _opened()
        with pytest.raises(TypeError):
            adapter.append("not-bytes")  # type: ignore[arg-type]

    def test_commit_returns_receipt(self):
        adapter, transport = _opened()
        assert adapter.commit().committed is True
        assert "commit" in transport.caller_names()


class TestRecv:
    def test_recv_only_delta_and_completed(self):
        events = [
            TranscriptionEvent(kind=TranscriptionEventKind.DELTA, text="语"),
            TranscriptionEvent(kind=TranscriptionEventKind.COMPLETED, text="语音链路"),
        ]
        adapter, _ = _opened(FakeTransport(events=events))
        assert adapter.recv().kind is TranscriptionEventKind.DELTA
        assert adapter.recv().kind is TranscriptionEventKind.COMPLETED
        assert adapter.recv() is None

    def test_recv_before_ready_raises(self):
        adapter = LocalVoiceStackAdapter(FakeTransport())
        with pytest.raises(RuntimeError):
            adapter.recv()


class TestTranscribeFinal:
    def test_transcribe_final_calls_http_endpoint(self):
        adapter, transport = _opened(FakeTransport(final_text="逐字正确的终稿"))
        text = adapter.transcribe_final(b"\x00" * 128)
        assert text == "逐字正确的终稿"
        assert ("transcribe", ASR_URL, 128) in transport.calls

    def test_transcribe_final_rejects_empty_and_unaligned(self):
        adapter, _ = _opened()
        with pytest.raises(ValueError):
            adapter.transcribe_final(b"")
        with pytest.raises(ValueError):
            adapter.transcribe_final(b"\x00")


class TestCloseAndRecover:
    def test_flush_close_flushes_then_closes(self):
        adapter, transport = _opened()
        assert adapter.flush_close() is True
        assert "flush" in transport.caller_names()
        assert "close" in transport.caller_names()
        assert adapter.ready is False

    def test_close_without_final_usage_is_incomplete_not_zero(self):
        adapter, _ = _opened()
        result = adapter.close()
        assert result.usage_status is UsageStatus.INCOMPLETE

    def test_close_with_final_usage_is_settled(self):
        adapter, _ = _opened()
        result = adapter.close(final_usage={"audio_input_ms": 6960})
        assert result.usage_status is UsageStatus.SETTLED

    def test_recover_is_local_rebuild_only(self):
        adapter, _ = _opened()
        result = adapter.recover()
        assert result.mode is RecoveryMode.LOCAL_REBUILD_ONLY
        assert "committed_inputs" in result.rebuilt_from

    def test_never_calls_response_create(self):
        adapter, transport = _opened(FakeTransport(events=[TranscriptionEvent(TranscriptionEventKind.COMPLETED)]))
        adapter.append(b"\x00" * 640)
        adapter.commit()
        adapter.recv()
        adapter.transcribe_final(b"\x00" * 128)
        adapter.flush_close()
        adapter.recover()
        rendered = " ".join(str(call) for call in transport.calls)
        assert "response.create" not in rendered
        assert "response_create" not in rendered


class TestProfileValidation:
    def test_profile_requires_urls(self):
        with pytest.raises(ValueError):
            LocalStackProfile(realtime_ws_url="not-a-url", transcription_http_url=ASR_URL)

    def test_default_format_is_16k_mono_pcm16(self):
        profile = _profile()
        assert profile.sample_rate_hz == 16000
        assert profile.channels == 1
        assert profile.input_audio_format is AudioFormat.PCM16
        assert profile.recovery_mode is RecoveryMode.LOCAL_REBUILD_ONLY


class TestD2Reserved:
    def test_d2_is_protocol_only_no_implementation(self):
        assert getattr(RealtimeProviderAdapter, "_is_protocol", False) is True

    def test_no_concrete_remote_provider_class_defined(self):
        concrete = [
            name
            for name, obj in vars(pa).items()
            if isinstance(obj, type)
            and not getattr(obj, "_is_protocol", False)
            and name.endswith("Adapter")
        ]
        assert concrete == []  # D2：不为未选 Provider 写空适配器

    def test_no_webrtc_import_in_adapter_modules(self):
        import inspect

        from llm_loop.realtime import local_voice_stack_adapter as lva

        source = inspect.getsource(pa) + inspect.getsource(lva)
        assert "WebRTC" not in source
        assert "aiortc" not in source
