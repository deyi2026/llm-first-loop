"""Provider 适配器契约（D1 本地转写会话实现 / D2 远端预留）。

对应需求：`RTM-CAP-01/05/11/12`、`RTM-AUD-01`、`RTM-INP-09`、`RTM-REC-05`、`RTM-SEC-08`。

- **D1**：`LocalVoiceStackAdapter`（见 `local_voice_stack_adapter.py`）是首版**唯一实现**；
- **D2**：`RealtimeProviderAdapter` 仅**预留契约形状**，**不提供任何实现**、不写空适配器、
  不并行接云端主链路（`RTM-CAP-05/11`，设计 D23/D24）。

本模块只定义事实与边界（格式、事件、恢复模式、用量状态），不做语义判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from llm_loop.realtime.media_usage import UsageStatus

_URL_PATTERN = re.compile(r"^(wss?|https?)://[^\s]{1,512}\Z")
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _url(name: str, value: str) -> None:
    if not isinstance(value, str) or not _URL_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a ws(s)/http(s) URL")


class AudioFormat(StrEnum):
    """输入音频格式；本地栈固定 16k 单声道 PCM16（`RTM-AUD-01`）。"""

    PCM16 = "pcm16"


class TranscriptionEventKind(StrEnum):
    """转写会话**仅**产出这两类事件（无音频、无工具事件，`RTM-CAP-12`）。"""

    DELTA = "delta"
    COMPLETED = "completed"


class RecoveryMode(StrEnum):
    """恢复模式。本地栈无远端恢复令牌 → `LOCAL_REBUILD_ONLY`（`RTM-REC-05`）。"""

    LOCAL_REBUILD_ONLY = "local_rebuild_only"
    REMOTE_TOKEN = "remote_token"  # D2 预留；首版不产生


@dataclass(frozen=True)
class LocalStackProfile:
    """本地栈能力档案（参数来自能力档案，不散落硬编码，`RTM-CAP-11/14`）。"""

    realtime_ws_url: str
    transcription_http_url: str
    tts_http_url: str = ""
    text_endpoint: str = ""
    sample_rate_hz: int = 16000
    channels: int = 1
    input_audio_format: AudioFormat = AudioFormat.PCM16
    recovery_mode: RecoveryMode = RecoveryMode.LOCAL_REBUILD_ONLY
    max_frame_bytes: int = 6400
    local_stack_version: str = ""
    streaming_asr_model: str = ""
    final_asr_model: str = ""
    tts_model: str = ""
    vad_model: str = ""
    licenses: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _url("realtime_ws_url", self.realtime_ws_url)
        _url("transcription_http_url", self.transcription_http_url)
        if self.tts_http_url:
            _url("tts_http_url", self.tts_http_url)
        if self.sample_rate_hz <= 0 or self.channels <= 0 or self.max_frame_bytes <= 0:
            raise ValueError("sample_rate/channels/max_frame_bytes must be positive")
        if not isinstance(self.input_audio_format, AudioFormat):
            raise TypeError("input_audio_format must be AudioFormat")
        if not isinstance(self.recovery_mode, RecoveryMode):
            raise TypeError("recovery_mode must be RecoveryMode")
        for entry in self.licenses:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or not all(isinstance(part, str) and part.strip() for part in entry)
            ):
                raise ValueError("licenses entries must be non-empty (model, license) pairs")


@dataclass(frozen=True)
class TranscriptionEvent:
    """规范化转写事件：`delta`（暂定字幕）/ `completed`（识别完成）。"""

    kind: TranscriptionEventKind
    text: str = ""
    turn_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TranscriptionEventKind):
            raise TypeError("kind must be TranscriptionEventKind")
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        if self.turn_id and not _NAME_PATTERN.fullmatch(self.turn_id):
            raise ValueError("turn_id must be a bounded identifier")


@dataclass(frozen=True)
class AppendReceipt:
    """`append` 受理回执：**已受理 ≠ 已转写**（`RTM-CAP-14`）。"""

    accepted: bool
    bytes_accepted: int = 0


@dataclass(frozen=True)
class CommitReceipt:
    committed: bool


@dataclass(frozen=True)
class CloseResult:
    """关闭结果：缺最终用量 → `incomplete`（**不标零**，`RTM-BUD-04/05`）。"""

    usage_status: UsageStatus
    flushed: bool


@dataclass(frozen=True)
class RebuildResult:
    """本地会话重建结果（`RTM-REC-05`）。"""

    mode: RecoveryMode
    rebuilt_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityFacts:
    """能力档案三态记录项（官方 / 实测 / 未知）。"""

    name: str
    official: bool = False
    measured: bool = False
    unknown: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.fullmatch(self.name):
            raise ValueError("name must be a bounded identifier")


@runtime_checkable
class TranscriptionTransport(Protocol):
    """D1 底层传输（可注入 fake，便于确定性测试；生产实现经回环连本机）。

    契约**只**含转写所需能力：**没有 `response.create` 一类方法**，从结构上保证
    「仅转写」（`RTM-CAP-12`）。
    """

    def connect(self, url: str) -> None: ...

    def configure(self, *, sample_rate_hz: int, channels: int, audio_format: str) -> None: ...

    def append(self, frame: bytes) -> None: ...

    def commit(self) -> None: ...

    def next_event(self, timeout: float | None = None) -> TranscriptionEvent | None: ...

    def transcribe(self, url: str, segment: bytes) -> str: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class RealtimeProviderAdapter(Protocol):
    """**D2 预留契约形状**：远端实时适配器。

    首版**不实现**、**不为未选 Provider 写空适配器**（`RTM-CAP-05/11`）。
    本 Protocol 仅登记未来替换所需的接口形状，不产生任何运行时分支。
    """

    def open(self, profile: object) -> object: ...

    def recv(self) -> TranscriptionEvent | None: ...

    def send_media(self, chunk: bytes) -> None: ...

    def send_tool_result(self, tool_call_id: str, result: object, status: str) -> None: ...

    def supply_context(self, items: object) -> None: ...

    def update_playback_boundary(self, response_id: str, played_upto: int) -> None: ...

    def interrupt_response(self, response_id: str) -> None: ...

    def close(self) -> None: ...

    def recover(self, token: str) -> object: ...
