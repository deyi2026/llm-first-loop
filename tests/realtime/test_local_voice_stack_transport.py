"""M1 接线（`T-M1-10/13`）：本地语音栈回环传输测试。

覆盖 RTM：CAP-11/12/14、AUD-01、INP-09、SEC-08、PLY-07。
"""

from __future__ import annotations

import json

import pytest

from llm_loop.realtime.local_voice_stack_transport import (
    DEFAULT_MLX_AUDIO_BASE,
    LocalVoiceStackTransport,
    LoopbackOnlyError,
    assert_loopback,
)
from llm_loop.realtime.provider_adapter import TranscriptionEventKind


class FakeResponse:
    def __init__(self, *, status_code: int = 200, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text


class FakeHttp:
    def __init__(self, *, post: FakeResponse | None = None, get: FakeResponse | None = None) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []
        self._post = post or FakeResponse()
        self._get = get or FakeResponse()
        self.raise_on_get = False

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.posts.append((url, kwargs))
        return self._post

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        if self.raise_on_get:
            raise ConnectionError("refused")
        self.gets.append(url)
        return self._get


class FakeWs:
    def __init__(self, recv_values: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._recv = list(recv_values or [])

    def send(self, data: str | bytes) -> None:
        self.sent.append(data if isinstance(data, str) else data.decode("utf-8", "ignore"))

    def recv(self, timeout: float | None = None) -> str:
        if not self._recv:
            raise TimeoutError("no message")
        return self._recv.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, conn: FakeWs) -> None:
        self.conn = conn
        self.urls: list[str] = []

    def __call__(self, url: str) -> FakeWs:
        self.urls.append(url)
        return self.conn


def _transport(http: FakeHttp, ws: FakeWs | None = None) -> LocalVoiceStackTransport:
    return LocalVoiceStackTransport(http_client=http, ws_connector=FakeConnector(ws or FakeWs()))


class TestLoopbackOnly:
    def test_accepts_loopback(self):
        assert_loopback("http://127.0.0.1:8000")
        assert_loopback("ws://localhost:8000/v1/realtime")

    def test_rejects_non_loopback(self):
        for url in ("http://10.0.0.5:8000", "https://api.example.com/v1", "ws://192.168.1.9:8000"):
            with pytest.raises(LoopbackOnlyError):
                assert_loopback(url)

    def test_transport_rejects_non_loopback_target(self):
        with pytest.raises(LoopbackOnlyError):
            LocalVoiceStackTransport(
                http_client=FakeHttp(), ws_connector=FakeConnector(FakeWs()), base_url="http://evil.example"
            )


class TestHttpCapabilities:
    def test_transcribe_returns_text(self):
        http = FakeHttp(post=FakeResponse(content=json.dumps({"text": "逐字正确的终稿"}).encode()))
        transport = _transport(http)
        assert transport.transcribe(f"{DEFAULT_MLX_AUDIO_BASE}/v1/audio/transcriptions", b"\x00" * 64) == "逐字正确的终稿"
        assert http.posts[0][0].endswith("/v1/audio/transcriptions")

    def test_transcribe_failure_raises_visible_error(self):
        transport = _transport(FakeHttp(post=FakeResponse(status_code=500, text="boom")))
        with pytest.raises(RuntimeError):
            transport.transcribe(f"{DEFAULT_MLX_AUDIO_BASE}/v1/audio/transcriptions", b"\x00" * 64)

    def test_synthesize_returns_bytes(self):
        http = FakeHttp(post=FakeResponse(content=b"AUDIOBYTES"))
        transport = _transport(http)
        assert transport.synthesize("你好") == b"AUDIOBYTES"
        assert http.posts[0][0].endswith("/v1/audio/speech")

    def test_probe_reports_models(self):
        payload = json.dumps({"data": [{"id": "Qwen3-ASR-0.6B"}, {"id": "Qwen3-TTS-0.6B"}]}).encode()
        probe = _transport(FakeHttp(get=FakeResponse(content=payload))).probe()
        assert probe.reachable is True
        assert probe.model_ids == ("Qwen3-ASR-0.6B", "Qwen3-TTS-0.6B")

    def test_probe_unreachable_is_explicit(self):
        http = FakeHttp()
        http.raise_on_get = True
        probe = _transport(http).probe()
        assert probe.reachable is False
        assert "unreachable" in probe.detail


class TestWsTranscription:
    def test_connect_sends_session_update_only_transcription(self):
        ws = FakeWs()
        transport = _transport(FakeHttp(), ws)
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        sent = [json.loads(m) for m in ws.sent]
        assert sent[0]["type"] == "session.update"
        assert sent[0]["session"]["input_audio_format"] == "pcm16"
        assert sent[0]["session"]["input_audio_sample_rate"] == 16000
        assert sent[0]["session"]["turn_detection"] is None
        assert all("response.create" not in m for m in ws.sent)

    def test_connect_appends_model_query_to_ws_url(self):
        ws = FakeWs()
        connector = FakeConnector(ws)
        transport = LocalVoiceStackTransport(http_client=FakeHttp(), ws_connector=connector)
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        assert connector.urls[0].startswith("ws://127.0.0.1:8000/v1/realtime?model=")
        assert "nemotron" in connector.urls[0]

    def test_append_carries_base64_audio(self):
        ws = FakeWs()
        transport = _transport(FakeHttp(), ws)
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.append(b"\x01\x02" * 320)
        append_msg = [json.loads(m) for m in ws.sent if json.loads(m)["type"] == "input_audio_buffer.append"][0]
        assert "audio" in append_msg and append_msg["audio"]

    def test_append_commit_and_events(self):
        ws = FakeWs(
            recv_values=[
                json.dumps({"type": "conversation.item.input_audio_transcription.delta", "delta": "语音路"}),
                json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "语音链路"}),
            ]
        )
        transport = _transport(FakeHttp(), ws)
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.append(b"\x00" * 640)
        transport.commit()
        delta = transport.next_event()
        final = transport.next_event()
        assert delta is not None and delta.kind is TranscriptionEventKind.DELTA
        assert final is not None and final.kind is TranscriptionEventKind.COMPLETED
        assert final.text == "语音链路"  # 读取 `transcript` 字段

    def test_next_event_timeout_returns_none(self):
        transport = _transport(FakeHttp(), FakeWs())  # 无排队消息 → TimeoutError
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        assert transport.next_event(timeout=0.01) is None

    def test_non_transcription_events_ignored(self):
        ws = FakeWs(recv_values=[json.dumps({"type": "response.audio.delta", "delta": "x"})])
        transport = _transport(FakeHttp(), ws)
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        assert transport.next_event() is None

    def test_close_closes_connection(self):
        ws = FakeWs()
        transport = _transport(FakeHttp(), ws)
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.close()
        assert ws.closed is True


class TestRealMlxAudioProbe:
    def test_probe_real_service_if_running(self):
        try:
            import httpx

            response = httpx.get(f"{DEFAULT_MLX_AUDIO_BASE}/v1/models", timeout=2.0)
        except Exception:
            pytest.skip("mlx-audio server not running on 127.0.0.1:8000")
        assert response.status_code == 200
        ids = [item.get("id") for item in response.json().get("data", [])]
        assert ids, "expected mlx-audio to report loaded models"
