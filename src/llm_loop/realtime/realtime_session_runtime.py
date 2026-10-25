"""实时会话运行时（M1 代理实装）：`WS /api/v1/realtime/sessions/{id}/events` 的服务端处理。

对应需求：`RTM-SES-07`、`RTM-AUD-01`、`RTM-INP-01/02/09`、`RTM-PLY-07`、`RTM-CAP-11/12/14`。

链路（服务端回环代理；浏览器不直连 8000）：

    浏览器 --16k PCM16 帧--> LFL WS --转发--> mlx-audio（流式，可选）
    浏览器 --input.commit--> LFL --终稿--> mlx-audio /v1/audio/transcriptions --> 下行 input.final/turn.committed
    浏览器 --tts.request--> LFL --合成--> mlx-audio /v1/audio/speech --> 下行二进制 audio.playback

- **仅转写**：流式通道无 `response.create`；音频输出由服务端在桥接层编排（本地 TTS）；
- 终稿**以高精度重转写为准**（`INP-09`）；流式增量若不可用不影响终稿；
- 事件 envelope 必填字段齐备；**禁止为凑字段造假任务**。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import time
import uuid
import wave
from collections.abc import Awaitable, Callable

from llm_loop.realtime.keyframe_pipeline import (
    CommitRecord,
    FrameRejected,
    KeyframePipeline,
)
from llm_loop.realtime.provider_adapter import (
    AudioFormat,
    TranscriptionEvent,
    TranscriptionEventKind,
    VoiceStackTransport,
)

SendText = Callable[[str], Awaitable[None]]
SendBinary = Callable[[bytes], Awaitable[None]]
CommitSink = Callable[[CommitRecord], str]  # 视觉提交 → 任务输入（返回 task_ref）

PROTOCOL_VERSION = 1


def _envelope_reply_to(payload: dict[str, object]) -> dict[str, object]:
    """错误回执的 ``reply_to``（契约 §1）：上行 event_id 可用时原样回带。"""
    event_id = payload.get("event_id")
    if isinstance(event_id, str) and event_id:
        return {"reply_to": event_id}
    return {}


def pcm16_to_wav(pcm: bytes, *, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """把 16k 单声道 PCM16 包成 WAV（供 `/v1/audio/transcriptions` 使用）。"""
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
    """单个媒体会话的服务端运行时（终稿 + 本地 TTS 代理）。"""

    def __init__(
        self,
        *,
        media_session_id: str,
        session_id: str,
        transport: VoiceStackTransport,
        transcription_url: str,
        send_text: SendText,
        send_binary: SendBinary,
        sample_rate_hz: int = 16000,
        connection_epoch: int = 1,
        keyframes: KeyframePipeline | None = None,
        commit_sink: CommitSink | None = None,
        session_probe: Callable[[str], bool] | None = None,
        max_pcm_bytes: int = 4 * 1024 * 1024,
        max_pcm_seconds: float = 60.0,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._media_session_id = media_session_id
        self._session_id = session_id
        self._transport = transport
        self._transcription_url = transcription_url
        self._send_text = send_text
        self._send_binary = send_binary
        self._sample_rate = sample_rate_hz
        self._epoch = connection_epoch
        self._keyframes = keyframes
        self._commit_sink = commit_sink
        # P2-9a：目标会话存在性探测（可选注入；None = 不探测，行为不变）。
        self._session_probe = session_probe
        # RTM-RET-04 / D12：终稿运行缓存字节+时间双限（默认 4MB / 60s，可配置注入）。
        self._max_pcm_bytes = max_pcm_bytes
        self._max_pcm_seconds = max_pcm_seconds
        self._now_fn = now_fn or time.monotonic
        self._seq = 0
        self._pcm: bytearray = bytearray()
        self._pcm_started: float | None = None  # 当前累积窗口起点（单调时钟）
        # 缓冲代次：任何整段清空/丢弃/成功消费都自增（见 _reset_pcm_buffer）。
        # await 期间的前缀删除守卫据此判断缓冲内容是否已整体换过（缺陷①）。
        self._pcm_generation = 0
        self._pcm_capacity_exceeded = 0
        self._closed = False

    @property
    def buffered_bytes(self) -> int:
        return len(self._pcm)

    @property
    def capacity_exceeded_count(self) -> int:
        """有界降级计数（观察面；超限即丢整段并计数，客户端可重说）。"""
        return self._pcm_capacity_exceeded

    def stop(self) -> None:
        self._closed = True
        self._reset_pcm_buffer()  # close/断连即清理运行缓存（不留跨连接残留）
        if self._keyframes is not None:  # WS 断开 = 隐式停止共享（Stale，证据保留）
            self._keyframes.stop_shares()

    def _reset_pcm_buffer(self) -> None:
        """整段清空运行缓存的**单一真值来源**：清字节、重置窗口、自增代次。

        stop / 413 超限整段丢弃 / text-only commit 即消费都必须走这里；不得
        在别处手写 ``clear`` 而漏自增——否则 _finalize_with_visual 里按旧快照
        长度做的前缀删除会吃掉清空后新到的音频（缺陷①）。
        """
        self._pcm.clear()
        self._pcm_started = None
        self._pcm_generation += 1

    def _poll_event(self) -> TranscriptionEvent | None:
        """非阻塞取一个流式事件；传输不支持 `timeout` 时退化为阻塞取。"""
        try:
            return self._transport.next_event(timeout=0.05)
        except TypeError:
            return self._transport.next_event()

    async def pump_deltas(self) -> None:
        """后台泵：把流式**增量字幕**下行（`input.delta`）。

        终稿仍以 `input.commit` 的**高精度重转写**为准，避免两份终稿冲突（`INP-09`）。
        """
        while not self._closed:
            event = await asyncio.to_thread(self._poll_event)
            if event is None:
                await asyncio.sleep(0.02)
                continue
            if getattr(event, "kind", None) is TranscriptionEventKind.DELTA and event.text:
                await self._emit("input.delta", {"text": event.text})

    async def handle_binary(self, frame: bytes) -> None:
        """上行 16k PCM16 帧：累积（供终稿）并尝试转发流式（失败不影响终稿）。"""
        if len(frame) % 2 != 0:
            # P2-1：奇数字节帧显式拒绝（有界错误事件），不断开整条控制通道
            await self._emit(
                "error",
                {
                    "code": 400,
                    "reason": "malformed_frame",
                    "detail": "audio frame must be 2-byte aligned PCM16",
                },
            )
            return
        if not self._pcm and frame:
            self._pcm_started = self._now_fn()  # 新累积窗口起点
        self._pcm.extend(frame)
        overflow = self._pcm_overflow_reason()
        if overflow != "":
            # RTM-RET-04 / D12：字节+时间双限超限 → 有界降级（error 事件）并
            # 丢弃整段运行缓存（该段终稿原料已不可用）；后续帧重新累积，
            # 用户可直接重说，无需断开重连。
            dropped = len(self._pcm)
            window_s = (
                round(self._now_fn() - self._pcm_started, 3)
                if self._pcm_started is not None
                else None
            )
            self._reset_pcm_buffer()  # 整段丢弃（代次自增：旧快照的前缀删除须失效）
            self._pcm_capacity_exceeded += 1
            await self._emit(
                "error",
                {
                    "code": 413,
                    "reason": "capacity_exceeded",
                    "detail": overflow,
                    "buffered_bytes": dropped,
                    "window_s": window_s,
                },
            )
        with contextlib.suppress(Exception):  # 流式可选：仅转写；不可用不阻断终稿
            self._transport.append(frame)

    def _pcm_overflow_reason(self) -> str:
        """运行缓存超限原因码（字节/时间）；空串 = 未超限。"""
        if self._max_pcm_bytes > 0 and len(self._pcm) > self._max_pcm_bytes:
            return "pcm_buffer_bytes_exceeded"
        if (
            self._max_pcm_seconds > 0
            and self._pcm_started is not None
            and (self._now_fn() - self._pcm_started) > self._max_pcm_seconds
        ):
            return "pcm_buffer_window_exceeded"
        return ""

    async def handle_text(self, raw: str) -> None:
        payload = json.loads(raw)
        event_type = str(payload.get("type", ""))
        if event_type == "input.commit":
            visual = payload.get("visual")
            if visual is None:
                await self._finalize()  # 文本-only：既有行为零变化
                return
            await self._finalize_with_visual(payload, visual)
            return
        if event_type == "tts.request":
            text = str(payload.get("text", ""))
            audio = await asyncio.to_thread(self._transport.synthesize, text)
            await self._send_binary(audio)
            await self._emit("audio.playback", {"response_id": str(payload.get("response_id", ""))})
            return
        if event_type in ("visual.share.start", "visual.share.stop", "visual.frame"):
            await self._handle_visual_event(event_type, payload)
            return

    async def _visual_envelope_error(self, payload: dict[str, object]) -> str:
        """上行视觉信封校验（契约 §1）；返回有界 reason 或空串。

        P2-3：version/epoch 布尔严格（``True == 1`` 不放行）；``event_id``/``seq``
        必填（非空字符串 / ≥1 的 int，排除 bool）；错误回执由调用方附
        ``reply_to``（能取到 event_id 时）。
        """
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
            return "unsupported_version"
        epoch = payload.get("connection_epoch")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch != self._epoch:
            return "stale_epoch"
        if payload.get("media_session_id") != self._media_session_id:
            return "wrong_session"
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return "malformed_envelope"
        seq = payload.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            return "malformed_envelope"
        return ""

    async def _handle_visual_event(self, event_type: str, payload: dict[str, object]) -> None:
        """M3 关键帧控制消息：share/帧摄取（契约 docs/M3-KEYFRAME-WIRE-CONTRACT.md）。"""
        reply_to = {"reply_to": payload["event_id"]} if isinstance(payload.get("event_id"), str) else {}
        if self._keyframes is None:
            await self._emit("error", {"code": 503, "reason": "visual_unavailable", **reply_to})
            return
        reason = await self._visual_envelope_error(payload)
        if reason:
            await self._emit("error", {"code": 409, "reason": reason, **reply_to})
            return
        pipeline = self._keyframes
        if event_type == "visual.share.start":
            outcome, detail = await asyncio.to_thread(
                pipeline.share_start,
                payload.get("source_id"),
                payload.get("source_epoch"),
                payload.get("label"),
            )
            if outcome == "started":
                await self._emit("visual.share.started", {**detail, **reply_to})
            else:
                await self._emit("error", {"code": 409, **detail, **reply_to})
            return
        if event_type == "visual.share.stop":
            outcome, detail = await asyncio.to_thread(
                pipeline.share_stop, payload.get("source_id"), payload.get("source_epoch")
            )
            if outcome == "stopped":
                await self._emit("visual.share.stopped", {**detail, **reply_to})
            else:
                await self._emit("error", {"code": 409, **detail, **reply_to})
            return
        # visual.frame
        message = {
            key: payload.get(key)
            for key in (
                "frame_id",
                "source_id",
                "source_epoch",
                "captured_at_ms",
                "width",
                "height",
                "mime",
                "data_b64",
                "selection",
            )
        }
        result = await asyncio.to_thread(pipeline.ingest, message)
        if isinstance(result, FrameRejected):
            await self._emit(
                "visual.frame.rejected",
                {"frame_id": message["frame_id"] or "", "reason": result.reason, **reply_to},
            )
            return
        await self._emit(
            "visual.frame.registered",
            {
                "frame_id": result.frame_id,
                "content_ref": result.content_ref,
                "sha256": result.sha256,
                "path": result.path,
                "received_at_s": result.received_at_s,
                **reply_to,
            },
        )

    async def _finalize_with_visual(self, payload: dict[str, object], visual: object) -> None:
        """带视觉指代的提交：解析当前/历史候选 → 绑定 committed turn + 任务输入。

        歧义/无候选 → `visual.clarify`（不派发）；严格拒绝（未知来源等）→ `error` 且不消费音频。
        错误回执按契约 §1 附 ``reply_to``（上行 event_id 可用时）。

        P2-4（审查 2026-10-25 第 4 条）：音频只在**提交真正成功**（bind bound +
        sink 成功、即将发 turn.committed）时才消费；clarify/rejected/503 均保留
        缓冲（仍受 max_pcm_bytes/max_pcm_seconds 双限与超限降级约束），客户端
        修正后可重提交。P2-9a：可选 ``session_probe`` 在消费音频与 bind 前探测
        目标会话，不存在 → 409 ``wrong_session``（契约 §4 已枚举），不绑定不入队。
        """
        reply_to = _envelope_reply_to(payload)
        reason = await self._visual_envelope_error(payload)
        if reason:
            await self._emit("error", {"code": 409, "reason": reason, **reply_to})
            return
        if self._keyframes is None:
            await self._emit("error", {"code": 503, "reason": "visual_unavailable", **reply_to})
            return
        if self._commit_sink is None:
            # 任务提交入口未装配（仅测试/显式禁用路径）：fail-safe 503，
            # 不消费音频、不伪造 turn.committed（客户端本地也不得再提交）。
            await self._emit("error", {"code": 503, "reason": "task_submit_unavailable", **reply_to})
            return
        problem = self._keyframes.validate_commit_visual(visual)
        if problem:
            await self._emit("error", {"code": 409, "reason": problem, **reply_to})
            return  # 无副作用：音频保留，客户端修正后可重提交
        # validate_commit_visual 的首检即 isinstance(visual, dict)，通过 ⇒ 必为映射。
        # 显式收窄而不是 cast，让「校验通过」这个事实留在可检查的类型里。
        assert isinstance(visual, dict), "validated visual must be a mapping"
        if self._session_probe is not None:
            # P2-9a：目标会话不存在（如前端无会话 fallback "local"）→ 在消费
            # 音频/bind 之前拒绝（409 wrong_session，契约 §4 已枚举集合）。
            # 探测自身故障按不存在处理（fail-safe：宁可拒绝也不入死队）。
            try:
                session_exists = bool(self._session_probe(self._session_id))
            except Exception:  # noqa: BLE001 - 探测故障 = 无法核实存在性
                session_exists = False
            if not session_exists:
                await self._emit(
                    "error",
                    {
                        "code": 409,
                        "reason": "wrong_session",
                        "detail": "commit target session does not exist",
                        **reply_to,
                    },
                )
                return  # 不消费音频、不绑定、不入队
        generation = self._pcm_generation  # 快照代次：成功消费前比对（缺陷①守卫）
        segment = bytes(self._pcm)  # P2-4：只读快照，提交真正成功前不消费
        turn_id = f"turn-{self._epoch}-{self._seq}"
        if segment:
            wav = pcm16_to_wav(segment, sample_rate=self._sample_rate)
            text = await asyncio.to_thread(self._transport.transcribe, self._transcription_url, wav)
        else:
            text = ""
        # visual=true：终稿由服务端 commit_sink 派发任务；客户端不得本地重复提交，
        # 只等待 turn.committed / visual.clarify / error（文本-only 的 input.final 无此字段）。
        await self._emit("input.final", {"turn_id": turn_id, "text": text, "visual": True})
        outcome, detail = await asyncio.to_thread(
            self._keyframes.bind_commit, turn_id=turn_id, visual=visual, text=text
        )
        if outcome == "clarify":
            await self._emit("visual.clarify", {"turn_id": turn_id, "question": str(detail)})
            return  # 不派发任务；P2-4：音频保留（双限约束不变），澄清后可重提交
        if outcome == "rejected":
            await self._emit("error", {"code": 409, "reason": str(detail), **reply_to})
            return  # P2-4：音频保留（如 frame_already_bound），客户端修正后可重提交
        # clarify/rejected 已在上方返回；走到这里 outcome 只能是 "bound"，detail 只能是
        # 证据序列。用断言把这条不变式写成可检查的事实（而不是 cast 掩盖它）。
        assert isinstance(detail, tuple), "bind_commit('bound') must carry an evidence tuple"
        evidences = detail
        task_ref = ""
        if self._commit_sink is not None:
            record = CommitRecord(
                session_id=self._session_id,
                media_session_id=self._media_session_id,
                turn_id=turn_id,
                text=text,
                visual_evidence=tuple(evidences),
            )
            try:
                task_ref = await asyncio.to_thread(self._commit_sink, record)
            except Exception:  # noqa: BLE001 - 提交失败如实报错，不伪造成功
                await self._emit("error", {"code": 503, "reason": "task_submit_failed", **reply_to})
                return  # P2-4：音频保留；同帧已绑定本 turn，重提交须换新帧（否则 frame_already_bound）
        # P2-4：仅当绑定成功且任务已入队（即将发 turn.committed）才消费音频。
        # 只移除本次转写过的快照长度——等待期间新到的帧保留在缓存继续累积
        # （仍受 max_pcm_bytes/max_pcm_seconds 双限与既有超限降级路径约束，
        # 超限仍整段丢弃）。
        # 缺陷①守卫：快照之后代次若已变化（等待期间 413 整段清空 / stop /
        # 其它成功消费），当前缓冲内容已**全部晚于快照**——此时跳过删除，
        # 绝不可按旧快照长度删前缀（那会吃掉用户新说的话）。代次未变才
        # 删除并自增。
        if self._pcm_generation == generation:
            del self._pcm[: len(segment)]
            self._pcm_generation += 1
        if not self._pcm:
            self._pcm_started = None  # 缓存已空：重置累积窗口起点
        await self._emit(
            "turn.committed",
            {
                "turn_id": turn_id,
                "text": text,
                "evidence_refs": [e.content_ref for e in evidences],
                "visual": [e.to_public_dict() for e in evidences],
                "task_ref": task_ref,
            },
        )

    async def _finalize(self) -> None:
        """提交：高精度终稿 → 下行 `input.final` + `turn.committed`。"""
        segment = bytes(self._pcm)
        self._reset_pcm_buffer()  # commit 即消费：重置累积窗口（同步清空，行为不变）
        turn_id = f"turn-{self._epoch}-{self._seq}"
        if segment:
            wav = pcm16_to_wav(segment, sample_rate=self._sample_rate)
            text = await asyncio.to_thread(self._transport.transcribe, self._transcription_url, wav)
        else:
            text = ""  # 空音频：不提交（由前端/契约保证；此处如实返回空）
        await self._emit("input.final", {"turn_id": turn_id, "text": text})
        await self._emit("turn.committed", {"turn_id": turn_id, "text": text})

    async def notify_session_closed(self) -> None:
        """会话登记已 closed（take_over / DELETE）：向旧连接下发有界 error。

        reason `session_closed` 取自契约 §5/§4 枚举（docs/M3-KEYFRAME-WIRE-
        CONTRACT.md，不自造）；调用方（realtime_ws 收包循环）随后应退出并走
        既有 finally 清理，避免新旧连接短暂双写入（缺陷②）。
        """
        await self._emit("error", {"code": 409, "reason": "session_closed"})

    async def _emit(self, event_type: str, extra: dict[str, object]) -> None:
        self._seq += 1
        envelope: dict[str, object] = {
            "version": PROTOCOL_VERSION,
            "type": event_type,
            "event_id": uuid.uuid4().hex,
            "seq": self._seq,
            "connection_epoch": self._epoch,
            "session_id": self._session_id,
            "media_session_id": self._media_session_id,
            "input_audio_format": AudioFormat.PCM16.value,
            **extra,
        }
        await self._send_text(json.dumps(envelope))
