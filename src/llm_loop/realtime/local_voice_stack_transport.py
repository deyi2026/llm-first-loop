"""本地语音栈真实回环传输（M1 接线）：连接本机 `mlx-audio`。

对应需求：`RTM-CAP-11/12/14`、`RTM-AUD-01`、`RTM-INP-09`、`RTM-SEC-08`、`RTM-PLY-07`。

- **仅回环**：默认 `http://127.0.0.1:8000`（`mlx-audio`），浏览器**不直连**（经 LFL 受信服务端）；
- **HTTP**：`/v1/audio/transcriptions`（高精度终稿，INP-09）、`/v1/audio/speech`（本地 TTS，PLY-07）、`/v1/models`（preflight）；
- **WS**：`/v1/realtime`（仅转写，CAP-12）；
- 实现 `TranscriptionTransport` 协议，供 `LocalVoiceStackAdapter` 使用；
- 依赖（`httpx.Client`、WS 连接工厂）**注入**，故可离线测试；真实网络不在此验证。

> 注意：LFL Web 自身默认端口为 `WEB_PORT=8903`，与 `mlx-audio` 的 `8000` **不同**；两者不得互相抢占。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from llm_loop.realtime.provider_adapter import (
    AudioFormat,
    TranscriptionEvent,
    TranscriptionEventKind,
)


class HttpResponseLike(Protocol):
    """响应最小形状（`httpx.Response` 满足它）。

    三个成员都用只读 property 声明：`httpx.Response.content/text/status_code`
    是只读 property，若协议声明成可写属性，真实响应会因「不可赋值」被判不兼容。
    """

    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...

    @property
    def text(self) -> str: ...


class HttpClientLike(Protocol):
    """HTTP 客户端最小形状（`httpx.Client` 满足它；测试的 `FakeHttp` 也可）。

    参数逐个列出而不是 `**kwargs`：`httpx.Client.post` 用的是显式关键字参数、
    没有 ``**kwargs``，把协议写成 ``**kwargs: Any`` 反而无法被它满足。
    """

    def post(
        self,
        url: str,
        *,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        data: Mapping[str, object] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> HttpResponseLike: ...

    def get(self, url: str) -> HttpResponseLike: ...


class WsConnectionLike(Protocol):
    def send(self, data: bytes | str) -> None: ...

    def recv(self, timeout: float | None = None) -> str: ...

    def close(self) -> None: ...


def default_websocket_connector(url: str) -> WsConnectionLike:
    """真实回环 WS 连接（`websockets` 同步客户端）。"""
    from websockets.sync.client import connect

    return connect(url, max_size=8 * 1024 * 1024, open_timeout=5.0)  # type: ignore[return-value]


DEFAULT_MLX_AUDIO_BASE = "http://127.0.0.1:8000"
DEFAULT_MLX_AUDIO_WS = "ws://127.0.0.1:8000/v1/realtime"
DEFAULT_WS_MODEL = "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"
DEFAULT_FINAL_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
DEFAULT_TTS_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"

# 转写事件**精确**类型（不得按后缀匹配，避免把音频事件误判为转写，CAP-12）
TRANSCRIPTION_DELTA_EVENT = "conversation.item.input_audio_transcription.delta"
TRANSCRIPTION_COMPLETED_EVENT = "conversation.item.input_audio_transcription.completed"


class LoopbackOnlyError(ValueError):
    """非回环目标：拒绝（浏览器/服务端不得把媒体送到任意远端，SEC-08）。"""


def assert_loopback(url: str) -> None:
    lowered = url.lower()
    allowed = ("http://127.0.0.1", "http://localhost", "ws://127.0.0.1", "ws://localhost")
    if not any(lowered.startswith(prefix) for prefix in allowed):
        raise LoopbackOnlyError(f"local voice stack must be loopback-only: {url}")


@dataclass
class LocalStackProbe:
    """preflight 结果：可达性与可用模型（CAP-14 缺项显式、不静默空结果）。"""

    reachable: bool
    model_ids: tuple[str, ...]
    detail: str = ""


class LocalVoiceStackTransport:
    """`TranscriptionTransport` 的本地回环实现 + 终稿/TTS HTTP 能力。"""

    def __init__(
        self,
        *,
        http_client: HttpClientLike,
        ws_connector: object,
        base_url: str = DEFAULT_MLX_AUDIO_BASE,
        ws_url: str = DEFAULT_MLX_AUDIO_WS,
        ws_model: str = DEFAULT_WS_MODEL,
        final_model: str = DEFAULT_FINAL_MODEL,
        tts_model: str = DEFAULT_TTS_MODEL,
        owns_http_client: bool = False,
    ) -> None:
        assert_loopback(base_url)
        assert_loopback(ws_url)
        self._http = http_client
        # P2-2：仅当调用方显式移交所有权（工厂自建客户端）时，close 才负责关闭；
        # 注入的客户端归调用方所有，transport 不得代关。
        self._owns_http_client = owns_http_client
        self._ws_connector = ws_connector
        self._base_url = base_url.rstrip("/")
        self._ws_url = ws_url
        self._ws_model = ws_model
        self._final_model = final_model
        self._tts_model = tts_model
        self._sample_rate = 16000
        self._conn: WsConnectionLike | None = None

    # ---- TranscriptionTransport ----

    def connect(self, url: str) -> None:
        assert_loopback(url)
        # mlx-audio 要求 WS URL 携带 `?model=`（否则握手后立即关闭）
        separator = "&" if "?" in url else "?"
        target = f"{url}{separator}model={quote(self._ws_model, safe='')}"
        connect = self._ws_connector  # type: ignore[assignment]
        self._conn = connect(target)  # type: ignore[operator]
        # 握手后协商（仅转写；无 response.create、无音频输出）
        self._send_json(
            {
                "type": "session.update",
                "session": {
                    "model": self._ws_model,
                    "turn_detection": None,
                    "input_audio_format": AudioFormat.PCM16.value,
                    "input_audio_sample_rate": self._sample_rate,
                },
            }
        )

    def configure(self, *, sample_rate_hz: int, channels: int, audio_format: str) -> None:
        if channels != 1:
            raise ValueError("local stack supports mono input only")
        self._sample_rate = sample_rate_hz
        self._send_json(
            {
                "type": "session.update",
                "session": {
                    "model": self._ws_model,
                    "turn_detection": None,
                    "input_audio_format": audio_format,
                    "input_audio_sample_rate": sample_rate_hz,
                },
            }
        )

    def append(self, frame: bytes) -> None:
        """上行一帧：**必须携带 base64 音频**（mlx-audio 协议）。"""
        self._send_json(
            {"type": "input_audio_buffer.append", "audio": base64.b64encode(frame).decode("ascii")}
        )

    def commit(self) -> None:
        self._send_json({"type": "input_audio_buffer.commit"})

    def next_event(self, *, timeout: float | None = None) -> TranscriptionEvent | None:
        """读取下一个转写事件；`timeout` 到期返回 None（供非阻塞轮询增量字幕）。"""
        conn = self._require_conn()
        try:
            raw = conn.recv(timeout=timeout)
        except TimeoutError:
            return None
        if not raw:
            return None
        payload = json.loads(raw)
        kind_raw = str(payload.get("type", ""))
        if kind_raw == TRANSCRIPTION_DELTA_EVENT:
            return TranscriptionEvent(kind=TranscriptionEventKind.DELTA, text=str(payload.get("delta", "")))
        if kind_raw == TRANSCRIPTION_COMPLETED_EVENT:
            # mlx-audio 的完成事件字段为 `transcript`；兼容 `text`
            text = payload.get("transcript", payload.get("text", ""))
            return TranscriptionEvent(kind=TranscriptionEventKind.COMPLETED, text=str(text))
        # 非转写事件：忽略（仅转写，CAP-12）——**不得**按后缀误判音频事件为转写
        return None

    def transcribe(self, url: str, segment: bytes) -> str:
        assert_loopback(url)
        response = self._http.post(
            url,
            files={"file": ("segment.wav", segment, "application/octet-stream")},
            data={"model": self._final_model},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"transcription failed: {response.status_code} {response.text[:200]}")
        payload = json.loads(response.content.decode("utf-8"))
        return str(payload.get("text", ""))

    def flush(self) -> None:
        self._send_json({"type": "input_audio_buffer.commit"})

    def close(self) -> None:
        # P2-2：会话结束收口——先摘除引用再关（重复 close 幂等、恰好一次）；
        # 自有 httpx 客户端在 try/finally 内关闭：WS 关闭抛错也不漏掉连接池。
        conn, self._conn = self._conn, None
        try:
            if conn is not None:
                conn.close()
        finally:
            if self._owns_http_client:
                self._owns_http_client = False  # 先翻转所有权标志：重入/取消下不二次关
                http_close = getattr(self._http, "close", None)
                if callable(http_close):
                    http_close()

    # ---- 本地 TTS（PLY-07）----

    def synthesize(self, text: str, *, voice: str = "default", response_format: str = "wav") -> bytes:
        url = f"{self._base_url}/v1/audio/speech"
        response = self._http.post(
            url,
            json={"model": self._tts_model, "input": text, "voice": voice, "response_format": response_format},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"tts failed: {response.status_code} {response.text[:200]}")
        return response.content

    # ---- preflight（CAP-14）----

    def probe(self) -> LocalStackProbe:
        url = f"{self._base_url}/v1/models"
        try:
            response = self._http.get(url)
        except Exception as exc:  # noqa: BLE001 - 本地服务未起/不可达：显式缺项
            return LocalStackProbe(reachable=False, model_ids=(), detail=f"unreachable: {exc}")
        if response.status_code >= 400:
            return LocalStackProbe(
                reachable=False, model_ids=(), detail=f"http {response.status_code}"
            )
        try:
            payload = json.loads(response.content.decode("utf-8"))
            ids = tuple(str(item.get("id", "")) for item in payload.get("data", []))
        except Exception as exc:  # noqa: BLE001
            return LocalStackProbe(reachable=True, model_ids=(), detail=f"bad payload: {exc}")
        return LocalStackProbe(reachable=True, model_ids=ids)

    def _require_conn(self) -> WsConnectionLike:
        if self._conn is None:
            raise RuntimeError("transcription websocket is not connected")
        return self._conn

    def _send_json(self, payload: dict[str, object]) -> None:
        self._require_conn().send(json.dumps(payload))
