"""Loopback audio transport for the authenticated media WebSocket.

Only recognition facts leave this runtime. The browser submits a final through
the existing chat endpoint; this module never claims that a task was dispatched.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import uuid
import wave
from collections.abc import Awaitable, Callable
from typing import Protocol

from llm_loop.realtime.provider_adapter import TranscriptionEvent, TranscriptionEventKind

SendText = Callable[[str], Awaitable[None]]
SendBinary = Callable[[bytes], Awaitable[None]]
MAX_PCM_BYTES = 16000 * 2 * 120  # A bounded two-minute push-to-talk segment.


class VoiceTransport(Protocol):
    def append(self, frame: bytes) -> None: ...
    def next_event(self, *, timeout: float | None = None) -> TranscriptionEvent | None: ...
    def transcribe(self, url: str, segment: bytes) -> str: ...
    def synthesize(self, text: str) -> bytes: ...


def pcm16_to_wav(pcm: bytes, *, sample_rate: int = 16000, channels: int = 1) -> bytes:
    if len(pcm) % 2 != 0:
        raise ValueError("PCM16 payload must be 2-byte aligned")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


class RealtimeSessionRuntime:
    def __init__(
        self, *, media_session_id: str, session_id: str, transport: VoiceTransport,
        transcription_url: str, send_text: SendText, send_binary: SendBinary,
        sample_rate_hz: int = 16000, connection_epoch: int = 1,
        is_active: Callable[[], bool] = lambda: True,
    ) -> None:
        self._media_session_id = media_session_id
        self._session_id = session_id
        self._transport = transport
        self._transcription_url = transcription_url
        self._send_text = send_text
        self._send_binary = send_binary
        self._sample_rate = sample_rate_hz
        self._epoch = connection_epoch
        self._is_active = is_active
        self._seq = 0
        self._pcm = bytearray()
        self._closed = False
        self._send_lock = asyncio.Lock()
        self._tts_generation = 0
        self._tts_task: asyncio.Task[None] | None = None

    @property
    def buffered_bytes(self) -> int:
        return len(self._pcm)

    def stop(self) -> None:
        self._closed = True
        self._pcm.clear()
        self._cancel_tts()

    def _cancel_tts(self) -> None:
        self._tts_generation += 1
        if self._tts_task is not None:
            self._tts_task.cancel()
            self._tts_task = None

    def _active(self) -> bool:
        return not self._closed and self._is_active()

    async def pump_deltas(self) -> None:
        while self._active():
            try:
                event = await asyncio.to_thread(self._transport.next_event, timeout=0.05)
            except Exception:
                await self._emit("input.streaming_unavailable", {})
                return
            if event is None:
                await asyncio.sleep(0.02)
            elif event.kind is TranscriptionEventKind.DELTA and event.text:
                await self._emit("input.delta", {"text": event.text})

    async def handle_binary(self, frame: bytes) -> None:
        if not self._active():
            return
        if len(frame) % 2:
            raise ValueError("audio frame must be 2-byte aligned PCM16")
        if len(self._pcm) + len(frame) > MAX_PCM_BYTES:
            raise ValueError("audio segment exceeds the two-minute transport limit")
        self._pcm.extend(frame)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._transport.append, frame)

    async def handle_text(self, raw: str) -> None:
        if not self._active():
            return
        payload = json.loads(raw)
        for key, expected in (
            ("session_id", self._session_id), ("media_session_id", self._media_session_id),
            ("connection_epoch", self._epoch),
        ):
            if key in payload and payload[key] != expected:
                raise ValueError("media control ownership mismatch")
        if payload.get("type") == "input.clear":
            self._pcm.clear()
        elif payload.get("type") == "input.commit":
            await self._finalize()
        elif payload.get("type") == "tts.cancel":
            self._cancel_tts()
        elif payload.get("type") == "tts.request":
            text = str(payload.get("text", ""))
            if not text.strip():
                return
            self._cancel_tts()
            current = self._tts_generation
            self._tts_task = asyncio.create_task(self._play_tts(text, str(payload.get("response_id", "")), current))

    async def _play_tts(self, text: str, response_id: str, generation: int) -> None:
        try:
            audio = await asyncio.to_thread(self._transport.synthesize, text)
        except asyncio.CancelledError:
            return
        except Exception:
            if generation == self._tts_generation:
                await self._emit("audio.playback_unavailable", {"response_id": response_id})
            return
        async with self._send_lock:
            if generation != self._tts_generation or not self._active():
                return
            await self._send_envelope("audio.playback", {"response_id": response_id})
            if generation == self._tts_generation and self._active():
                await self._send_binary(audio)

    async def _finalize(self) -> None:
        if not self._pcm:
            return
        wav = pcm16_to_wav(bytes(self._pcm), sample_rate=self._sample_rate)
        text = await asyncio.to_thread(self._transport.transcribe, self._transcription_url, wav)
        self._pcm.clear()
        await self._emit("input.final", {"turn_id": "turn-" + uuid.uuid4().hex, "text": text})

    async def _send_envelope(self, event_type: str, extra: dict[str, object]) -> None:
        self._seq += 1
        await self._send_text(json.dumps({
            "version": 1, "type": event_type, "event_id": uuid.uuid4().hex, "seq": self._seq,
            "connection_epoch": self._epoch, "session_id": self._session_id,
            "media_session_id": self._media_session_id, "input_audio_format": "pcm16", **extra,
        }))

    async def _emit(self, event_type: str, extra: dict[str, object]) -> None:
        async with self._send_lock:
            if self._active():
                await self._send_envelope(event_type, extra)
