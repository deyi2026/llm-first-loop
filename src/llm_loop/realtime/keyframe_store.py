"""M3：关键帧登记、绑定与失效更新（`T-M3-1` / `T-M3-2` 服务端侧）。

对应需求：`RTM-VIS-02/03/05/07/08`、`RTM-RET-01/02`、`RTM-SES-04`。

- 仅登记**用户选定来源**的帧（不采集未共享来源，`RTM-VIS-01` 由前端保证，服务端拒绝未登记来源）；
- 帧元数据齐备（来源标识/`source_epoch`/捕获·接收时刻/宽高/选区/不可变引用/`derived`）；
- **绑定后不可变**：已被提交点绑定的帧不得被新帧替换（`RTM-VIS-04`）；
- 失效更新：来源变化/共享停止/页面代次变化 → **当前有效性失效，证据仍保留**（`RTM-VIS-03`）；
- 拥塞时**只替换未绑定的预览帧**，不丢已绑定帧（`RTM-VIS-05/08`）；
- 删除/到期返回**明确失效**，不用摘要替代原图（`RTM-RET-02/03`）。

本模块只做机械事实（绑定、代次、有效期），不做语义理解。
"""

from __future__ import annotations

import threading

from llm_loop.realtime.keyframe import (
    CurrentValidity,
    Keyframe,
    KeyframeReadbackError,
    RetentionState,
)


class KeyframeCacheFullError(RuntimeError):
    """RET-04：未绑定预览帧已达容量上限且无可淘汰者；**拒绝新帧**（明确降级，不静默丢）。"""


class KeyframeStore:
    """按媒体会话登记关键帧；绑定、失效与预览替换。

    ``max_unbound_frames``（可选，RET-04 容量上限，默认 None=不限制）在**登记时**执行：
    超限时按登记顺序淘汰**最旧的未绑定预览帧**（VIS-05 拥塞替换，已绑定帧永不淘汰）；
    无可淘汰者（全部已绑定）时抛 :class:`KeyframeCacheFullError`，由调用方**显式拒绝**。
    """

    def __init__(self, *, max_unbound_frames: int | None = None) -> None:
        if max_unbound_frames is not None and (
            isinstance(max_unbound_frames, bool) or not isinstance(max_unbound_frames, int) or max_unbound_frames < 1
        ):
            raise ValueError("max_unbound_frames must be a positive integer or None")
        self._max_unbound = max_unbound_frames
        self._lock = threading.Lock()
        self._frames: dict[str, Keyframe] = {}
        self._bound: dict[str, str] = {}  # frame_id -> turn_id
        self._latest_by_source: dict[str, str] = {}

    def register(self, frame: Keyframe) -> Keyframe:
        with self._lock:
            if self._max_unbound is not None:
                while self._unbound_retained_locked() >= self._max_unbound:
                    victim = self._oldest_unbound_locked()
                    if victim is None:
                        raise KeyframeCacheFullError(
                            "unbound keyframe cache full; all frames bound (RET-04 explicit pause)"
                        )
                    self._frames[victim] = self._frames[victim].expire()  # 只淘汰未绑定预览帧
            self._frames[frame.frame_id] = frame
            self._latest_by_source[frame.source_id] = frame.frame_id
        return frame

    def _unbound_retained_locked(self) -> int:
        return sum(
            1
            for fid, f in self._frames.items()
            if fid not in self._bound and f.retention_state is RetentionState.RETAINED
        )

    def _oldest_unbound_locked(self) -> str | None:
        for fid, f in self._frames.items():  # dict 保持登记顺序
            if fid not in self._bound and f.retention_state is RetentionState.RETAINED:
                return fid
        return None

    def unbound_retained_count(self) -> int:
        """当前保留中的未绑定预览帧数（RET-04 观察面）。"""
        with self._lock:
            return self._unbound_retained_locked()

    def expire_older_than(self, cutoff_received_s: float) -> int:
        """RET-04 时长上限：把 ``received_at_s < cutoff`` 的保留帧置为到期（失去回读）。

        到期作用于**全部保留帧**（含已绑定帧：Bound→Expired 是设计 §2.1.3-F 允许迁移，
        与「预览替换不碰已绑定帧」正交）；返回到期数量。
        """
        with self._lock:
            affected = 0
            for fid, frame in list(self._frames.items()):
                if frame.retention_state is RetentionState.RETAINED and frame.received_at_s < cutoff_received_s:
                    self._frames[fid] = frame.expire()
                    affected += 1
            return affected

    def bind(self, frame_id: str, *, turn_id: str) -> Keyframe:
        """绑定到提交点：**绑定后不可变**，且不再可被预览替换。"""
        with self._lock:
            frame = self._frames[frame_id]
            if frame_id in self._bound and self._bound[frame_id] != turn_id:
                raise ValueError("frame already bound to another turn")
            self._bound[frame_id] = turn_id
            return frame

    def is_bound(self, frame_id: str) -> bool:
        with self._lock:
            return frame_id in self._bound

    def get(self, frame_id: str) -> Keyframe | None:
        with self._lock:
            return self._frames.get(frame_id)

    def bound_frames(self, turn_id: str) -> tuple[Keyframe, ...]:
        with self._lock:
            return tuple(
                self._frames[fid] for fid, tid in self._bound.items() if tid == turn_id and fid in self._frames
            )

    def current_frame(self, source_id: str) -> Keyframe | None:
        """该来源**当前可用**（current valid + retained）的最新帧。"""
        with self._lock:
            frame_id = self._latest_by_source.get(source_id)
            frame = self._frames.get(frame_id) if frame_id else None
        if frame is None or not frame.can_answer_current():
            return None
        return frame

    def history(self, source_id: str) -> tuple[Keyframe, ...]:
        """该来源**保留**的帧（含 `Stale`；不含到期/删除）。"""
        with self._lock:
            frames = [f for f in self._frames.values() if f.source_id == source_id]
        return tuple(f for f in frames if f.can_answer_history())

    def mark_source_stale(self, source_id: str) -> int:
        """来源变化/共享停止/页面代次变化：当前有效性失效，**证据仍保留**。"""
        with self._lock:
            affected = 0
            for frame_id, frame in list(self._frames.items()):
                if frame.source_id == source_id and frame.current_validity is CurrentValidity.VALID:
                    self._frames[frame_id] = frame.mark_stale()
                    affected += 1
            return affected

    def expire(self, frame_id: str) -> Keyframe:
        """到期：失去回读能力（此后回读返回明确失效）。"""
        with self._lock:
            frame = self._frames[frame_id].expire()
            self._frames[frame_id] = frame
            return frame

    def delete(self, frame_id: str) -> Keyframe:
        with self._lock:
            frame = self._frames[frame_id].delete()
            self._frames[frame_id] = frame
            return frame

    def readback_ref(self, frame_id: str) -> str:
        """回读不可变引用；已失效/到期 → 明确失效（不用摘要替代原图）。"""
        with self._lock:
            frame = self._frames.get(frame_id)
        if frame is None:
            raise KeyframeReadbackError(f"keyframe {frame_id} not found")
        return frame.readback_ref()

    def replace_preview(self, frame_id: str, new_frame: Keyframe) -> bool:
        """拥塞时**只替换未绑定的预览帧**；已绑定帧拒绝替换。"""
        with self._lock:
            if frame_id not in self._frames:
                return False
            if frame_id in self._bound:
                return False  # 已绑定：不丢
            self._frames.pop(frame_id, None)
            self._frames[new_frame.frame_id] = new_frame
            self._latest_by_source[new_frame.source_id] = new_frame.frame_id
            return True

    def count(self, *, retention: RetentionState | None = None) -> int:
        with self._lock:
            if retention is None:
                return len(self._frames)
            return sum(1 for f in self._frames.values() if f.retention_state is retention)
