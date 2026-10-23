"""D1 本地转写会话适配器 `LocalVoiceStackAdapter`（首版唯一实现）。

对应需求：`RTM-CAP-01/05/11/12/14`、`RTM-AUD-01`、`RTM-INP-09`、`RTM-REC-05`、`RTM-SEC-08`。

硬约束（`DESIGN v1.3 §2.2.2-D1`、D24）：

- 经**回环**连接本机 `WS /v1/realtime`，**仅转写**——**不调用 `response.create`**、
  不期待音频事件、不期待工具回环（`RTM-CAP-12`）；
- `append` 是**受理回执**，**已受理 ≠ 已转写**；
- `ready` 以**握手 + 转写会话配置成功**为准（不要求先收到首帧）；
- 参数（16k / 单声道 / pcm16）来自能力档案，不散落硬编码（`RTM-AUD-01`）；
- `flush_close` **必须** flush 收尾（`RTM-CAP-14`）；`close` 缺最终用量 → `incomplete`（**不标零**）；
- 无远端恢复令牌 → `recover()` 走**本地会话重建**（`RTM-REC-05`）。

本适配器只做机械事实（格式、状态、受理/完成区分），不做语义理解。
"""

from __future__ import annotations

from llm_loop.realtime.media_usage import UsageStatus
from llm_loop.realtime.provider_adapter import (
    AppendReceipt,
    AudioFormat,
    CloseResult,
    CommitReceipt,
    LocalStackProfile,
    RebuildResult,
    RecoveryMode,
    TranscriptionEvent,
    TranscriptionEventKind,
    TranscriptionTransport,
)

_LOCAL_REBUILD_SOURCES = ("committed_inputs", "task_summary", "evidence_refs")


class LocalVoiceStackAdapter:
    """D1：本地转写会话适配器。"""

    def __init__(self, transport: TranscriptionTransport) -> None:
        if transport is None:
            raise TypeError("transport is required")
        self._transport = transport
        self._profile: LocalStackProfile | None = None
        self._ready = False
        self._closed = False
        self._flushed = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def profile(self) -> LocalStackProfile | None:
        return self._profile

    def open(self, profile: LocalStackProfile) -> bool:
        """建立转写会话；返回就绪确认（握手 + 转写会话配置成功）。"""
        if not isinstance(profile, LocalStackProfile):
            raise TypeError("profile must be LocalStackProfile")
        self._transport.connect(profile.realtime_ws_url)
        self._transport.configure(
            sample_rate_hz=profile.sample_rate_hz,
            channels=profile.channels,
            audio_format=profile.input_audio_format.value,
        )
        self._profile = profile
        self._ready = True
        self._closed = False
        self._flushed = False
        return True

    def configure(self, *, sample_rate_hz: int | None = None, channels: int | None = None) -> None:
        """重新协商格式；缺省沿用能力档案值（不硬编码）。"""
        profile = self._require_profile()
        rate = profile.sample_rate_hz if sample_rate_hz is None else sample_rate_hz
        ch = profile.channels if channels is None else channels
        if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
            raise ValueError("sample_rate_hz must be a positive integer")
        if isinstance(ch, bool) or not isinstance(ch, int) or ch <= 0:
            raise ValueError("channels must be a positive integer")
        self._transport.configure(
            sample_rate_hz=rate, channels=ch, audio_format=profile.input_audio_format.value
        )

    def append(self, pcm_frame: bytes) -> AppendReceipt:
        """提交一帧音频；返回**受理回执**（不代表已转写）。"""
        self._require_ready()
        profile = self._require_profile()
        raw = self._validate_frame(pcm_frame, profile)
        self._transport.append(raw)
        return AppendReceipt(accepted=True, bytes_accepted=len(raw))

    def commit(self) -> CommitReceipt:
        """提交本轮音频，触发流式 `completed`。"""
        self._require_ready()
        self._transport.commit()
        return CommitReceipt(committed=True)

    def recv(self) -> TranscriptionEvent | None:
        """取下一规范化转写事件（**仅** `delta` / `completed`）。"""
        self._require_ready()
        event = self._transport.next_event()
        if event is not None and event.kind not in (
            TranscriptionEventKind.DELTA,
            TranscriptionEventKind.COMPLETED,
        ):
            raise ValueError("transcription session must only yield delta/completed events")
        return event

    def transcribe_final(self, pcm_segment: bytes) -> str:
        """整段高精度终稿转写（`/v1/audio/transcriptions`，`RTM-INP-09`）。"""
        profile = self._require_profile()
        if not isinstance(pcm_segment, (bytes, bytearray)):
            raise TypeError("pcm_segment must be bytes")
        raw = bytes(pcm_segment)
        if not raw:
            raise ValueError("empty transcription segment")
        sample_bytes = 2 * profile.channels
        if len(raw) % sample_bytes != 0:
            raise ValueError("segment not aligned to PCM16 samples")
        return self._transport.transcribe(profile.transcription_http_url, raw)

    def flush_close(self) -> bool:
        """flush 收尾并关闭（**必须** flush，`RTM-CAP-14`）。"""
        self._transport.flush()
        self._transport.close()
        self._flushed = True
        self._ready = False
        self._closed = True
        return True

    def close(self, *, final_usage: object | None = None) -> CloseResult:
        """关闭并结算。缺最终用量 → `incomplete`（**不标零**）。"""
        if not self._closed:
            self._transport.close()
            self._closed = True
        self._ready = False
        status = UsageStatus.SETTLED if final_usage is not None else UsageStatus.INCOMPLETE
        return CloseResult(usage_status=status, flushed=self._flushed)

    def recover(self) -> RebuildResult:
        """恢复：本地栈无远端恢复令牌 → **本地会话重建**（`RTM-REC-05`）。"""
        profile = self._require_profile()
        if profile.recovery_mode is not RecoveryMode.LOCAL_REBUILD_ONLY:
            raise ValueError("remote recovery is D2-reserved and not implemented in first release")
        return RebuildResult(
            mode=RecoveryMode.LOCAL_REBUILD_ONLY, rebuilt_from=_LOCAL_REBUILD_SOURCES
        )

    def _require_profile(self) -> LocalStackProfile:
        if self._profile is None:
            raise RuntimeError("adapter is not open")
        return self._profile

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("transcription session is not ready")

    @staticmethod
    def _validate_frame(pcm_frame: bytes, profile: LocalStackProfile) -> bytes:
        if not isinstance(pcm_frame, (bytes, bytearray)):
            raise TypeError("pcm_frame must be bytes")
        raw = bytes(pcm_frame)
        if not raw:
            raise ValueError("empty audio frame")
        if profile.input_audio_format is not AudioFormat.PCM16:
            raise ValueError("unsupported input audio format")
        if len(raw) % (2 * profile.channels) != 0:
            raise ValueError("frame not aligned to PCM16 samples")
        if len(raw) > profile.max_frame_bytes:
            raise ValueError("frame exceeds max_frame_bytes")
        return raw
