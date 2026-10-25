"""M3 服务端视觉证据链：关键帧摄取、指代绑定、失效与保留（`T-M3-1/2` 端到端）。

对应需求：`RTM-VIS-01..09`、`RTM-RET-01/02/04/05`、`RTM-SES-04`、`RTM-IDN-02`、`RTM-OBS-02`。

链路（服务端，仅经既有 WS 控制通道，无第二条连接）：

    浏览器 --share.start{source_id, source_epoch}--> 登记活动源（allowlist）
    浏览器 --keyframe.up{base64 帧}--> 校验 → WorkspaceArtifactStore（字节）+ KeyframeStore（元数据）
    浏览器 --input.commit{visual:{source_id, kind}}--> VisualContextResolver 绑定 → turn.committed(evidence_refs)
                                       └ 候选不唯一/无当前帧 → turn.clarify（不派发）
    浏览器 --share.stop--> 当前有效性失效（Stale ≠ 删除，历史仍可答）
    DELETE /api/v1/realtime/sessions/{id} --> 全部到期（回读明确失效）

不变量：

- **只允许用户显式共享的来源**（`share.start` 登记）上送帧；未知来源/epoch 不符**有界拒绝**，
  绝不回退到任意最新帧（`RTM-VIS-01`、IDN-02）；
- 帧字节**只**经既有 `WorkspaceArtifactStore` 承载（`artifact://v1/<32hex>`，**无第二证据库**，RET-05）；
  工作区内文件仅为 `read_image` 回读入口，不可变精确源以 artifact blob 为准（RET-01）；
- RET-04 双限在 `KeyframeStore` 层执行：未绑定预览帧容量上限（超限先淘汰最旧未绑定预览，
  全部已绑定时**显式拒绝** `cache_full`）+ 帧龄时长上限（到期即失去回读）；
- 日志/事件/错误**不含媒体体或可重建画面的内容**（RET-05、OBS-02）：只记 frame_id/来源/尺寸/计数；
- 帧龄（客户端单调时钟）由客户端计算；服务端只报 `received_at_s` 口径的接收时延（VIS-06）。
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from llm_loop.realtime.keyframe import Keyframe, KeyframeReadbackError, RetentionState, Selection
from llm_loop.realtime.keyframe_store import KeyframeCacheFullError, KeyframeStore
from llm_loop.realtime.visual_context import QuestionKind, VisualContextResolver

logger = logging.getLogger(__name__)

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
ALLOWED_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class _MalformedSelection:
    """哨兵类型：``selection`` 字段畸形（唯一实例，见 `_MALFORMED_SELECTION`）。

    用类型而非裸 ``object()`` 承载，才能让「畸形」与「已解析的 Selection」在
    类型层面可区分，调用点无需 cast 即可收窄（行为与原先的同一性判断等价）。
    """

    __slots__ = ()


_MALFORMED_SELECTION = _MalformedSelection()  # 哨兵：selection 字段畸形


# 有界拒绝码（visual.frame.rejected / share 失败 reason；不携带内部细节）
UNKNOWN_SOURCE = "unknown_source"
SOURCE_NOT_ACTIVE = "source_not_active"
SOURCE_EPOCH_MISMATCH = "source_epoch_mismatch"
MIME_UNSUPPORTED = "mime_unsupported"
FRAME_TOO_LARGE = "frame_too_large"
RATE_LIMITED = "rate_limited"
CACHE_FULL = "cache_full"
MALFORMED = "malformed"
SESSION_CLOSED = "session_closed"
DUPLICATE_FRAME_ID = "duplicate_frame_id"
FRAME_ALREADY_BOUND = "frame_already_bound"
ARTIFACT_STORE_FAILED = "artifact_store_failed"  # P2-5：证据库写入失败（帧文件已清理）


class _FrameFacts:
    """摄取时登记的机械事实（mime/相对路径/sha256）；**不含**帧字节。"""

    __slots__ = ("mime", "rel_path", "sha256")

    def __init__(self, mime: str, rel_path: str, sha256: str) -> None:
        self.mime = mime
        self.rel_path = rel_path
        self.sha256 = sha256


@dataclass(frozen=True)
class KeyframeLimits:
    """服务端防线（客户端采样建议 0.5–1fps 由契约约束，此处为硬上限）。"""

    max_frame_bytes: int = 512 * 1024  # 单帧字节上限（解码后）
    min_interval_s: float = 0.2  # 同源两帧最小间隔（≈5fps 上限）
    max_unbound_frames: int = 32  # RET-04 容量上限（KeyframeStore 层执行）
    max_frame_age_s: float = 1800.0  # RET-04 时长上限


@dataclass(frozen=True)
class FrameRegistered:
    frame_id: str
    content_ref: str
    sha256: str
    path: str
    received_at_s: float


@dataclass(frozen=True)
class FrameRejected:
    reason: str


@dataclass(frozen=True)
class VisualEvidence:
    """绑定到 committed turn 的视觉证据（独立结构化注记；**不含**媒体体）。"""

    frame_id: str
    source_id: str
    source_epoch: int
    kind: str
    content_ref: str
    path: str
    sha256: str
    mime: str
    width: int
    height: int
    captured_at_client_monotonic_s: float
    received_at_s: float

    def to_public_dict(self) -> dict[str, object]:
        return {
            "frame_id": self.frame_id,
            "source_id": self.source_id,
            "source_epoch": self.source_epoch,
            "kind": self.kind,
            "content_ref": self.content_ref,
            "path": self.path,
            "sha256": self.sha256,
            "mime": self.mime,
            "width": self.width,
            "height": self.height,
            "captured_at_client_monotonic_s": self.captured_at_client_monotonic_s,
            "received_at_s": self.received_at_s,
        }


# 提交点绑定结果：三态判别式联合（``outcome`` 收窄 ``detail`` 的类型）。
# ``bound`` 携带证据序列；``clarify``/``rejected`` 携带有界原因串。
CommitBinding = (
    tuple[Literal["bound"], tuple[VisualEvidence, ...]]
    | tuple[Literal["clarify"], str]
    | tuple[Literal["rejected"], str]
)


@dataclass(frozen=True)
class CommitRecord:
    """视觉提交点产物：用户原文原样 + 独立视觉证据注记（不篡改原文）。"""

    session_id: str
    media_session_id: str
    turn_id: str
    text: str
    visual_evidence: tuple[VisualEvidence, ...] = ()


@dataclass
class _SourceState:
    epoch: int
    active: bool
    label: str | None = None
    last_accepted_received_s: float = -1.0


def _magic_matches(data: bytes, mime: str) -> bool:
    if mime == "image/png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if mime == "image/jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if mime == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


class KeyframePipeline:
    """单媒体会话的关键帧摄取与视觉指代绑定。"""

    def __init__(
        self,
        *,
        media_session_id: str,
        session_id: str,
        artifact_store: object,
        workspace_root: str | Path,
        limits: KeyframeLimits | None = None,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._media_session_id = media_session_id
        self._session_id = session_id
        self._artifacts = artifact_store
        self._workspace_root = Path(workspace_root).expanduser().resolve()
        self._limits = limits or KeyframeLimits()
        self._now = now_fn
        self._store = KeyframeStore(max_unbound_frames=self._limits.max_unbound_frames)
        self._resolver = VisualContextResolver()
        self._sources: dict[str, _SourceState] = {}
        self._frame_facts: dict[str, _FrameFacts] = {}
        self._closed = False
        self._counters: dict[str, int] = {"registered": 0, "evicted": 0, "bound_turns": 0}
        self._rejected: dict[str, int] = {}

    # ------------------------------------------------------------------ 共享源

    def share_start(
        self, source_id: object, source_epoch: object, label: object = None
    ) -> tuple[str, dict[str, object]]:
        """登记活动共享源（allowlist）。epoch 变化 = 旧帧当前有效性失效（证据保留）。

        参数按上行信封原样接收（``object``）并在下方逐项校验：畸形值一律以
        `MALFORMED` 有界拒绝，与侵入前的行为一致。
        """
        if self._closed:
            return "rejected", {"reason": SESSION_CLOSED}
        if not isinstance(source_id, str) or not _NAME.fullmatch(source_id):
            return "rejected", {"reason": MALFORMED}
        if isinstance(source_epoch, bool) or not isinstance(source_epoch, int) or source_epoch < 1:
            return "rejected", {"reason": MALFORMED}
        if label is not None and (not isinstance(label, str) or len(label) > 128):
            return "rejected", {"reason": MALFORMED}
        state = self._sources.get(source_id)
        resumed = False
        if state is not None:
            if state.epoch != source_epoch:
                self._store.mark_source_stale(source_id)  # 源 epoch 变化：当前失效，历史保留
            else:
                resumed = True
            state.epoch = source_epoch
            state.active = True
            if label is not None:
                state.label = label
        else:
            self._sources[source_id] = _SourceState(epoch=source_epoch, active=True, label=label)
        logger.info(
            "realtime_share_start media_session_id=%s source_id=%s source_epoch=%s resumed=%s",
            self._media_session_id,
            source_id,
            source_epoch,
            resumed,
        )
        return "started", {
            "source_id": source_id,
            "source_epoch": source_epoch,
            "resumed": resumed,
        }

    def share_stop(self, source_id: object, source_epoch: object = None) -> tuple[str, dict[str, object]]:
        """停止共享：当前有效性失效；**证据仍保留**（Stale ≠ 删除，历史可答）。

        带 ``source_epoch`` 时必须与当前登记 epoch 一致，否则拒绝（不误停新代次源）。
        参数按上行信封原样接收（``object``）：非字符串 ``source_id`` 不可能命中已登记
        源，故与字典未命中同样以 `UNKNOWN_SOURCE` 拒绝（行为不变）。
        """
        if not isinstance(source_id, str):
            return "rejected", {"reason": UNKNOWN_SOURCE}
        state = self._sources.get(source_id)
        if state is None:
            return "rejected", {"reason": UNKNOWN_SOURCE}
        if source_epoch is not None:
            if isinstance(source_epoch, bool) or not isinstance(source_epoch, int) or source_epoch < 1:
                return "rejected", {"reason": MALFORMED}
            if state.epoch != source_epoch:
                return "rejected", {"reason": SOURCE_EPOCH_MISMATCH}
        state.active = False
        staled = self._store.mark_source_stale(source_id)
        logger.info(
            "realtime_share_stop media_session_id=%s source_id=%s frames_staled=%s",
            self._media_session_id,
            source_id,
            staled,
        )
        return "stopped", {"source_id": source_id, "frames_staled": staled}

    def known_sources(self) -> tuple[str, ...]:
        return tuple(self._sources)

    def active_sources(self) -> tuple[str, ...]:
        return tuple(sid for sid, st in self._sources.items() if st.active)

    # ------------------------------------------------------------------ 摄取

    def ingest(self, message: dict[str, object]) -> FrameRegistered | FrameRejected:
        """登记一帧：严格校验 → 字节入 WorkspaceArtifactStore → 元数据入 KeyframeStore。

        字段（对齐 docs/M3-KEYFRAME-WIRE-CONTRACT.md）：``frame_id``（客户端生成）、
        ``data_b64``、``captured_at_ms``（客户端单调时钟，毫秒）。同 ``frame_id`` 同字节
        重复上送幂等返回已登记的 content_ref；同 id 不同字节拒绝。
        """
        if self._closed:
            return self._reject(SESSION_CLOSED)
        self._enforce_age()
        source_id = message.get("source_id")
        source_epoch = message.get("source_epoch")
        if not isinstance(source_id, str) or not _NAME.fullmatch(source_id):
            return self._reject(MALFORMED)
        if isinstance(source_epoch, bool) or not isinstance(source_epoch, int) or source_epoch < 1:
            return self._reject(MALFORMED)
        frame_id = message.get("frame_id")
        if not isinstance(frame_id, str) or not _NAME.fullmatch(frame_id):
            return self._reject(MALFORMED)
        state = self._sources.get(source_id)
        if state is None:
            return self._reject(UNKNOWN_SOURCE)  # 只允许显式共享来源；不回退到任意来源
        if not state.active:
            return self._reject(SOURCE_NOT_ACTIVE)
        if state.epoch != source_epoch:
            return self._reject(SOURCE_EPOCH_MISMATCH)  # 源代次不符：拒绝，不误绑旧帧
        mime = message.get("mime")
        if mime not in ALLOWED_MIMES:
            return self._reject(MIME_UNSUPPORTED)
        width, height = message.get("width"), message.get("height")
        if (
            isinstance(width, bool) or not isinstance(width, int) or width <= 0
            or isinstance(height, bool) or not isinstance(height, int) or height <= 0
            or width > 32768 or height > 32768
        ):
            return self._reject(MALFORMED)
        captured_ms = message.get("captured_at_ms")
        if isinstance(captured_ms, bool) or not isinstance(captured_ms, (int, float)) or captured_ms < 0:
            return self._reject(MALFORMED)
        data_b64 = message.get("data_b64")
        if not isinstance(data_b64, str) or not data_b64:
            return self._reject(MALFORMED)
        if len(data_b64) > ((self._limits.max_frame_bytes * 4) // 3) + 4:
            return self._reject(FRAME_TOO_LARGE)
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError):
            return self._reject(MALFORMED)
        if len(data) > self._limits.max_frame_bytes:
            return self._reject(FRAME_TOO_LARGE)
        if not data or not _magic_matches(data, str(mime)):
            return self._reject(MIME_UNSUPPORTED)  # 魔数与声明不符：拒绝
        selection = self._parse_selection(message.get("selection"))
        if isinstance(selection, _MalformedSelection):
            return self._reject(MALFORMED)
        data_sha = hashlib.sha256(data).hexdigest()
        existing = self._store.get(frame_id)
        if existing is not None:
            prior = self._frame_facts.get(frame_id)
            if prior is not None and prior.sha256 == data_sha:
                try:  # 幂等：同 id 同字节，返回已登记引用
                    return FrameRegistered(
                        frame_id=frame_id,
                        content_ref=self._store.readback_ref(frame_id),
                        sha256=data_sha,
                        path=prior.rel_path,
                        received_at_s=existing.received_at_s,
                    )
                except KeyframeReadbackError:
                    pass
            return self._reject(DUPLICATE_FRAME_ID)
        now = self._now()
        if state.last_accepted_received_s >= 0 and (now - state.last_accepted_received_s) < self._limits.min_interval_s:
            return self._reject(RATE_LIMITED)
        frame_path = self._frame_path(frame_id, str(mime))
        expired_before = self._store.count(retention=RetentionState.EXPIRED)
        try:
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            frame_path.write_bytes(data)
            try:
                record = self._artifacts.create(  # type: ignore[attr-type]
                    workspace_scope=str(self._workspace_root),
                    canonical_path=str(frame_path),
                    data=data,
                    owner_session_id=self._session_id,
                    execution_id=self._media_session_id,
                    tool_call_id=frame_id,
                    tool_name="realtime_keyframe",
                    effect_kind="keyframe",
                )
                self._store.register(
                    Keyframe(
                        frame_id=frame_id,
                        source_id=source_id,
                        source_epoch=source_epoch,
                        captured_at_client_monotonic_s=float(captured_ms) / 1000.0,
                        received_at_s=now,
                        width=width,
                        height=height,
                        content_ref=record.ref,
                        selection=selection,
                    )
                )
            except Exception:
                # P2-5：artifact 登记/元数据任一步失败都清理刚写入的工作区帧文件，
                # 不留孤儿回读入口（也不让异常穿透断开 WS 连接）。
                with contextlib.suppress(OSError):
                    frame_path.unlink(missing_ok=True)
                raise
        except KeyframeCacheFullError:
            return self._reject(CACHE_FULL)  # RET-04：显式暂停/降级，不静默丢弃
        except Exception:  # noqa: BLE001 - 证据库失败：有界拒绝且不留半成品
            logger.exception(
                "realtime_keyframe_store_failed media_session_id=%s frame_id=%s",
                self._media_session_id,
                frame_id,
            )
            return self._reject(ARTIFACT_STORE_FAILED)
        state.last_accepted_received_s = now
        self._counters["registered"] += 1
        self._counters["evicted"] += max(
            0,
            self._store.count(retention=RetentionState.EXPIRED) - expired_before,
        )
        rel_path = frame_path.relative_to(self._workspace_root).as_posix()
        self._frame_facts[frame_id] = _FrameFacts(mime=str(mime), rel_path=rel_path, sha256=record.sha256)
        # 日志只记机械事实：不含帧字节/可重建内容（RET-05、OBS-02）
        logger.info(
            "realtime_keyframe_registered media_session_id=%s frame_id=%s source_id=%s bytes=%s mime=%s",
            self._media_session_id,
            frame_id,
            source_id,
            len(data),
            mime,
        )
        return FrameRegistered(
            frame_id=frame_id,
            content_ref=record.ref,
            sha256=record.sha256,
            path=rel_path,
            received_at_s=now,
        )

    def _parse_selection(self, raw: object) -> Selection | None | _MalformedSelection:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            return _MALFORMED_SELECTION
        try:
            selection = Selection(
                x=int(raw["x"]), y=int(raw["y"]), width=int(raw["width"]), height=int(raw["height"])
            )
        except (KeyError, TypeError, ValueError):
            return _MALFORMED_SELECTION
        if selection.width <= 0 or selection.height <= 0:
            return _MALFORMED_SELECTION
        return selection

    def _frame_path(self, frame_id: str, mime: str) -> Path:
        return self._workspace_root / ".realtime" / "frames" / self._media_session_id / f"{frame_id}{_EXT[mime]}"

    def _reject(self, reason: str) -> FrameRejected:
        self._rejected[reason] = self._rejected.get(reason, 0) + 1
        return FrameRejected(reason=reason)

    def _enforce_age(self) -> None:
        if self._limits.max_frame_age_s > 0:
            self._store.expire_older_than(self._now() - self._limits.max_frame_age_s)

    # ------------------------------------------------------------------ 绑定

    def validate_commit_visual(self, visual: object) -> str:
        """严格校验提交点视觉字段；返回有界错误码或空串（通过）。无副作用。"""
        if not isinstance(visual, dict):
            return MALFORMED
        source_id = visual.get("source_id")
        kind = visual.get("kind")
        if not isinstance(source_id, str) or not _NAME.fullmatch(source_id):
            return MALFORMED
        if kind not in (QuestionKind.CURRENT.value, QuestionKind.HISTORY.value):
            return MALFORMED
        if source_id not in self._sources:
            return UNKNOWN_SOURCE  # 从未共享：拒绝，不回退到任意最新帧
        return ""

    def bind_commit(self, *, turn_id: str, visual: dict[str, object], text: str = "") -> CommitBinding:
        """提交点绑定候选帧：``("bound", evidences)`` / ``("clarify", question)`` /
        ``("rejected", reason)``（如该帧已绑给其他 turn：绑定互斥，见 KeyframeStore）。

        ``text`` 为终稿原文（原样，不修改）：其中的历史/当前指代由 resolver 解析，
        优先于 ``visual.kind`` 提示（RTM-VIS-09）。
        """
        try:
            binding = self._resolver.resolve(
                store=self._store,
                turn_id=turn_id,
                source_id=str(visual["source_id"]),
                kind=QuestionKind(str(visual["kind"])),
                available_sources=self.active_sources(),
                text=text,
            )
        except ValueError:  # 同一帧已绑定到其他 turn：互斥，不回退不重绑
            return "rejected", FRAME_ALREADY_BOUND
        if not binding.bound or binding.chosen is None:
            return "clarify", binding.clarification or "请澄清要引用的画面"
        chosen = binding.chosen
        try:
            content_ref = self._store.readback_ref(chosen.frame_id)
        except KeyframeReadbackError:
            return "clarify", "该来源无可回读的历史证据（可能已到期或删除）"
        frame = self._store.get(chosen.frame_id)
        assert frame is not None  # bind 之后必然存在
        facts = self._frame_facts.get(frame.frame_id)
        assert facts is not None  # 摄取时已登记机械事实
        evidence = VisualEvidence(
            frame_id=frame.frame_id,
            source_id=frame.source_id,
            source_epoch=frame.source_epoch,
            kind=binding.kind.value,  # 生效 kind（终稿文本指代可能覆盖 visual.kind 提示）
            content_ref=content_ref,
            path=facts.rel_path,
            sha256=facts.sha256,
            mime=facts.mime,
            width=frame.width,
            height=frame.height,
            captured_at_client_monotonic_s=frame.captured_at_client_monotonic_s,
            received_at_s=frame.received_at_s,
        )
        self._counters["bound_turns"] += 1
        logger.info(
            "realtime_visual_bound media_session_id=%s turn_id=%s frame_id=%s source_id=%s kind=%s",
            self._media_session_id,
            turn_id,
            frame.frame_id,
            frame.source_id,
            evidence.kind,
        )
        return "bound", (evidence,)

    def readback(self, frame_id: str) -> str:
        """授权回读入口：保留期内返回 content_ref；到期/删除 → 明确失效。"""
        return self._store.readback_ref(frame_id)

    # ------------------------------------------------------------------ 失效与观察

    def stop_shares(self) -> int:
        """WS 断开等：全部活动源停止共享（当前失效，证据保留）。"""
        affected = 0
        for source_id, state in list(self._sources.items()):
            if state.active:
                state.active = False
                affected += self._store.mark_source_stale(source_id)
        return affected

    def close_session(self) -> int:
        """会话清理（DELETE）：停止共享 + 全部帧到期（回读明确失效，RET-02）。"""
        self.stop_shares()
        self._closed = True
        expired = 0
        for frame_id in list(self._store_frames()):
            frame = self._store.get(frame_id)
            if frame is not None and frame.retention_state.value == "retained":
                self._store.expire(frame_id)
                expired += 1
        logger.info(
            "realtime_keyframes_closed media_session_id=%s frames_expired=%s",
            self._media_session_id,
            expired,
        )
        return expired

    def _store_frames(self) -> tuple[str, ...]:
        ids: list[str] = []
        for probe in (self._sources or {}):
            ids.extend(f.frame_id for f in self._store.history(probe))
        seen: set[str] = set()
        unique: list[str] = []
        for fid in ids:
            if fid not in seen:
                seen.add(fid)
                unique.append(fid)
        return tuple(unique)

    def observe(self) -> dict[str, object]:
        """观察面（M3-4/M1-7）：计数与帧龄；**默认不含媒体体**（OBS-02）。"""
        self._enforce_age()
        now = self._now()
        sources = []
        for source_id, state in self._sources.items():
            latest = self._store.current_frame(source_id) or (
                self._store.history(source_id)[-1] if self._store.history(source_id) else None
            )
            sources.append(
                {
                    "source_id": source_id,
                    "active": state.active,
                    "source_epoch": state.epoch,
                    "retained_frames": len(self._store.history(source_id)),
                    "latest_frame_id": latest.frame_id if latest else "",
                    "latest_server_age_s": round(now - latest.received_at_s, 3) if latest else None,
                }
            )
        return {
            "media_session_id": self._media_session_id,
            "closed": self._closed,
            "sources": sources,
            "counters": {**self._counters, "rejected": dict(self._rejected)},
            "store": {
                "unbound_retained": self._store.unbound_retained_count(),
                "retained": len(
                    {f.frame_id for s in self._sources for f in self._store.history(s)}
                ),
                "limits": {
                    "max_unbound_frames": self._limits.max_unbound_frames,
                    "max_frame_age_s": self._limits.max_frame_age_s,
                    "max_frame_bytes": self._limits.max_frame_bytes,
                    "min_interval_s": self._limits.min_interval_s,
                },
            },
        }


class KeyframeServiceRegistry:
    """按媒体会话惰性构建 pipeline（装配点：``app.state.realtime_keyframes``）。"""

    def __init__(
        self,
        *,
        artifact_store_factory: Callable[[], object],
        workspace_root_factory: Callable[[], str],
        limits: KeyframeLimits | None = None,
    ) -> None:
        self._artifact_store_factory = artifact_store_factory
        self._workspace_root_factory = workspace_root_factory
        self._limits = limits
        self._lock = threading.Lock()
        self._pipelines: dict[str, KeyframePipeline] = {}

    def pipeline_for(self, *, media_session_id: str, session_id: str) -> KeyframePipeline:
        with self._lock:
            pipeline = self._pipelines.get(media_session_id)
            if pipeline is None:
                pipeline = KeyframePipeline(
                    media_session_id=media_session_id,
                    session_id=session_id,
                    artifact_store=self._artifact_store_factory(),
                    workspace_root=self._workspace_root_factory(),
                    limits=self._limits,
                )
                self._pipelines[media_session_id] = pipeline
            return pipeline

    def close_session(self, media_session_id: str) -> int:
        """会话清理：全部帧到期，并于锁内从 registry 移除该 pipeline 条目。

        P2-6（审查 2026-10-25 第 6 条）：长生命周期服务下 ``_pipelines`` 只增不
        减会缓慢积累内存；关闭即移除条目。幂等：未知会话返回 0，重复关闭返回 0
        （不抛错）。之后 ``pipeline_for`` 同 id 返回全新实例（不复用旧帧）。
        Expired 元数据保留策略不变——仍在旧 pipeline 实例内（若运行时仍引用它，
        历史指代继续可答）；registry 不再持有该实例引用，可被回收。
        """
        with self._lock:
            pipeline = self._pipelines.pop(media_session_id, None)
        if pipeline is None:
            return 0
        return pipeline.close_session()
