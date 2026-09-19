"""后台 run 执行器（对齐 DSH 后台任务架构；设计 docs/local/DESIGN-20260816-background-run.md v0.3）.

现状问题：run_stream 是生成器，SSE 端点持会话锁迭代它；连接断开 → GeneratorExit
→ run 中断（部分落盘但任务终止）。改造：run 在后台 daemon 线程执行，delta 经事件总线
广播给订阅者（SSE 端点改为订阅），断连只停订阅不杀后台线程；结果经 done/error 事件
送达，run_stream 结束时照常 session.save 全量落盘（刷新/切换会话后可见完整结果）。

关键点（盘问盲点落实）:
- B1: handle 状态在 registry 锁内读写，对外只读快照（get_handle 返回 dict）
- B3: start 短暂持 registry 锁（检查+注册+起线程）；同会话已有 running → 拒绝
- B4: 后台线程 daemon=True（进程退出不阻塞；残余丢弃，会话落盘兜底）
- B6: 事件总线广播（每订阅者独立 queue；done/error 广播含结果；unsubscribe 后不再 put）
- 运行中 delta 不增量落盘（简化）——完成时 run_stream 内部 session.save 全量落盘；
  刷新时 registry 有 handle → 订阅剩余广播；无 handle → 读会话完整结果
- 兼容: 不装配/disabled 时 routes 回退旧生成器直驱（enabled=False）
"""

from __future__ import annotations

import contextvars
import copy
import logging
import pickle
import queue
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.runtime.resolver import business_config_snapshot

logger = logging.getLogger(__name__)

_RUNNER_CONFIG = business_config_snapshot("runner")

# EVO-20260825（任务12 §5.12）: 残留 run 巡检/清理配置（spec §6.11）
_STALE_RUN_INSPECT_HOURS = float(_RUNNER_CONFIG.get("STALE_RUN_INSPECT_HOURS", "24"))
_RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC = float(
    _RUNNER_CONFIG.get("RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC", "10.0")
)
_RUN_CLEANUP_CONFIRMATION_REQUIRED = bool(
    int(_RUNNER_CONFIG.get("RUN_CLEANUP_CONFIRMATION_REQUIRED", "1"))
)

# 取消原因值域（结构化标记位，可审计；空串=未取消）。
# reason 为可扩展枚举，本 P1 不实现 RunControl，仅预留与未来统一 cancel contract
# （Web/Feishu 同源）的接口形状兼容：cancel(session_id, reason="user_stop") 形参
# 顺序与命名保持稳定，后续新增原因只扩展枚举不改结构。
CANCEL_REASON_USER_STOP = "user_stop"
CANCEL_REASON_RUNNER_STOP = "runner_stop"


class SessionBusyError(RuntimeError):
    """同会话已有进行中的后台 run（跨入口互斥，设计 B5/B7）.

    engine.run_stream 入口检查抛出；调用方（web /chat、飞书、CLI）捕获转友好提示。
    """


class QueuedIngressDurabilityError(RuntimeError):
    """Queued human ingress could not cross its mandatory durable EventStore boundary."""


class RunGenerationMismatchError(RuntimeError):
    """A resume request did not name the exact currently-running generation."""

    def __init__(
        self, *, expected_run_generation: str | None, actual_run_generation: str
    ) -> None:
        self.expected_run_generation = str(expected_run_generation or "")
        self.actual_run_generation = str(actual_run_generation or "")
        super().__init__(
            "resume run generation mismatch: "
            f"expected={self.expected_run_generation or '<missing>'} "
            f"actual={self.actual_run_generation or '<missing>'}"
        )


@dataclass
class RunHandle:
    """一次后台 run 的句柄（状态仅 registry 锁内变更；对外用 snapshot 只读快照）.

    _bus 内部引用（unsubscribe 用，不对外暴露）.
    """

    session_id: str
    # Fresh per execution, never derived from session id or timestamps.  Reconnect/resume
    # must bind this exact generation so an old tab cannot subscribe to a later run.
    run_generation: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "running"  # running | done | error
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str = ""
    _bus: Any = field(default=None, repr=False)

    # 2026-08-23 停止按钮修复: 取消标志（前端 stopStreaming → runner.cancel → 引擎主循环检查）
    cancelled: bool = field(default=False, repr=False)
    # 取消原因标记位（""=未取消；值域 CANCEL_REASON_*，结构化可审计）
    cancel_reason: str = ""
    # EVO-20260825（任务12 §5.12）: 压测残留 run 巡检数据源——最后活跃时间 + 当前轮数
    last_active_ts: float = field(default_factory=time.time)
    current_round: int = 0
    # Human steer mailbox. Web threads may append only through BackgroundRunner;
    # the engine worker is the sole consumer at a safe round boundary.
    interjections: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "run_generation": self.run_generation,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "cancelled": self.cancelled,
            "last_active_ts": self.last_active_ts,
            "current_round": self.current_round,
            "interjection_pending": len(self.interjections),
        }


class EventBus:
    """Per-run event bus with live broadcast and lossless active-run replay.

    Live subscribers receive the original event objects immediately.  Replay history is
    different: provider streams can emit hundreds or thousands of tiny reasoning/text
    deltas, so retaining a Python object per delta both wastes RAM and made the old
    ``_HISTORY_MAX=500`` policy truncate the beginning of long reasoning on reconnect.

    The replay source of truth is therefore a short-lived ``SpooledTemporaryFile``:
    small runs stay in memory up to a fixed byte ceiling, larger runs spill to an
    anonymous temporary file.  A reconnect reads that mechanical event stream in order
    and coalesces only adjacent *pure* text or *pure* reasoning deltas into bounded
    chunks.  Tool progress/results keep their own event boundaries and terminal events
    remain independent.  Nothing here is persisted into conversation history or fed
    back to the model prompt.
    """

    # Compatibility marker for the historical truncation boundary.  It is intentionally
    # no longer a retention cap; regression tests cross it to prove prefixes survive.
    _HISTORY_MAX = 500
    _SUBSCRIBER_MAX = 1024
    _REPLAY_SPOOL_MAX_BYTES = 256 * 1024
    _REPLAY_CHUNK_CHARS = 64 * 1024
    _TERMINAL_TYPES = frozenset({"done", "error"})

    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._guard = threading.Lock()
        self._replay = tempfile.SpooledTemporaryFile(  # noqa: SIM115 - run-scoped; close() is explicit
            max_size=self._REPLAY_SPOOL_MAX_BYTES,
            mode="w+b",
        )
        self._terminal_event: dict | None = None
        self._replay_write_errors = 0

    @staticmethod
    def _put_latest(q: queue.Queue, event: dict) -> None:
        """Non-blocking live delivery; a slow live consumer keeps the newest facts."""
        try:
            q.put_nowait(event)
            return
        except queue.Full:
            logger.debug("event bus subscriber queue full; evicting oldest live event")
        try:
            q.get_nowait()
        except queue.Empty:
            logger.debug("event bus queue drained while evicting oldest event")
        try:
            q.put_nowait(event)
        except queue.Full:
            logger.warning("event bus subscriber queue stayed full; newest live event dropped")

    @staticmethod
    def _pure_stream_delta(event: dict) -> tuple[str, str, Any] | None:
        """Return (channel, content, delta) only for mechanically merge-safe deltas."""
        if event.get("type") != "delta":
            return None
        delta = event.get("delta")
        if delta is None:
            return None
        if getattr(delta, "tool_round", None) is not None:
            return None
        if getattr(delta, "tool_result", None) is not None:
            return None
        text = str(getattr(delta, "text", "") or "")
        reasoning = str(getattr(delta, "reasoning", "") or "")
        if text and not reasoning:
            return ("text", text, delta)
        if reasoning and not text:
            return ("reasoning", reasoning, delta)
        return None

    @staticmethod
    def _merged_delta_event(template: Any, channel: str, content: str) -> dict:
        """Copy the original delta type while changing only one text-bearing field."""
        delta = copy.copy(template)
        if channel == "text":
            delta.text = content
            delta.reasoning = None
        else:
            delta.text = ""
            delta.reasoning = content
        return {"type": "delta", "delta": delta}

    def _append_replay_locked(self, event: dict) -> None:
        """Append one nonterminal replay fact without making live delivery depend on it."""
        try:
            pickle.dump(event, self._replay, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:  # noqa: BLE001 - replay observability must not kill the run
            self._replay_write_errors += 1
            logger.exception("event bus replay spool write failed; live delivery continues")

    def _replay_frame_count_locked(self) -> int:
        """Count compacted replay frames without materializing replay text in RAM."""
        end = self._replay.tell()
        self._replay.seek(0)
        count = 0
        pending_channel: str | None = None
        pending_chars = 0

        def flush_pending() -> None:
            nonlocal count, pending_channel, pending_chars
            if pending_channel is not None and pending_chars > 0:
                count += (pending_chars + self._REPLAY_CHUNK_CHARS - 1) // self._REPLAY_CHUNK_CHARS
            pending_channel = None
            pending_chars = 0

        try:
            while self._replay.tell() < end:
                try:
                    event = pickle.load(self._replay)
                except EOFError:
                    break
                pure = self._pure_stream_delta(event)
                if pure is None:
                    flush_pending()
                    count += 1
                    continue
                channel, content, _template = pure
                if pending_channel is not None and pending_channel != channel:
                    flush_pending()
                if pending_channel is None:
                    pending_channel = channel
                pending_chars += len(content)
            flush_pending()
            if self._terminal_event is not None:
                count += 1
            return count
        finally:
            self._replay.seek(end)

    def _replay_into_queue_locked(self, q: queue.Queue) -> None:
        """Replay the current spool snapshot in order with bounded text/reasoning chunks."""
        end = self._replay.tell()
        self._replay.seek(0)

        pending_channel: str | None = None
        pending_template: Any = None
        pending_parts: list[str] = []
        pending_chars = 0

        def flush_pending() -> None:
            nonlocal pending_channel, pending_template, pending_parts, pending_chars
            if pending_channel is None or pending_template is None or not pending_parts:
                pending_channel = None
                pending_template = None
                pending_parts = []
                pending_chars = 0
                return
            self._put_latest(
                q,
                self._merged_delta_event(
                    pending_template,
                    pending_channel,
                    "".join(pending_parts),
                ),
            )
            pending_channel = None
            pending_template = None
            pending_parts = []
            pending_chars = 0

        def append_piece(channel: str, content: str, template: Any) -> None:
            nonlocal pending_channel, pending_template, pending_parts, pending_chars
            if pending_channel is not None and pending_channel != channel:
                flush_pending()
            if pending_channel is None:
                pending_channel = channel
                pending_template = template

            remaining = content
            while remaining:
                room = self._REPLAY_CHUNK_CHARS - pending_chars
                if room <= 0:
                    flush_pending()
                    pending_channel = channel
                    pending_template = template
                    room = self._REPLAY_CHUNK_CHARS
                piece = remaining[:room]
                pending_parts.append(piece)
                pending_chars += len(piece)
                remaining = remaining[room:]
                if pending_chars >= self._REPLAY_CHUNK_CHARS:
                    flush_pending()
                    if remaining:
                        pending_channel = channel
                        pending_template = template

        try:
            while self._replay.tell() < end:
                try:
                    event = pickle.load(self._replay)
                except EOFError:
                    break
                pure = self._pure_stream_delta(event)
                if pure is not None:
                    channel, content, template = pure
                    append_piece(channel, content, template)
                    continue
                flush_pending()
                self._put_latest(q, event)
            flush_pending()
            if self._terminal_event is not None:
                self._put_latest(q, self._terminal_event)
        finally:
            # emit() always appends at EOF; restore the write cursor after snapshot replay.
            self._replay.seek(end)

    def subscribe(self) -> queue.Queue:
        with self._guard:
            # Count after mechanical compaction, not raw provider fragments.  Replay gets
            # enough queue headroom to be lossless while live slow-consumer headroom stays
            # bounded at the existing _SUBSCRIBER_MAX beyond that snapshot.
            replay_frames = self._replay_frame_count_locked()
            q: queue.Queue = queue.Queue(
                maxsize=max(self._SUBSCRIBER_MAX, replay_frames + self._SUBSCRIBER_MAX)
            )
            # Holding the guard across replay establishes strict history-before-live order:
            # emit() cannot interleave a new event between the replay snapshot and adding
            # this queue to the live subscriber set.
            self._replay_into_queue_locked(q)
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._guard:
            self._subs.discard(q)

    def emit(self, event: dict) -> None:
        with self._guard:
            if event.get("type") in self._TERMINAL_TYPES:
                # One bounded terminal fact avoids serializing an arbitrary LoopResult while
                # preserving the narrow race where resume subscribes just after completion.
                self._terminal_event = event
            else:
                self._append_replay_locked(event)
            subs = list(self._subs)
        for q in subs:
            try:
                self._put_latest(q, event)
            except Exception:  # noqa: BLE001 — one subscriber never affects the run
                logger.warning("event bus put failed (ignored)", exc_info=True)

    def close(self) -> None:
        """Release ephemeral replay storage after the run leaves the active registry."""
        with self._guard:
            try:
                self._replay.close()
            except Exception:  # noqa: BLE001 - cleanup only
                logger.debug("event bus replay spool close failed", exc_info=True)


class BackgroundRunner:
    """后台 run 执行器：start 启动 daemon 线程消费 run_stream，事件总线广播.

    构造注入 engine（duck typing：仅需 engine.run_stream(session_id, user_text, model)
    返回 Iterator[StreamDelta]，StopIteration.value 为 LoopResult；不 import 具体类型）。
    """

    def __init__(self, engine: Any, *, enabled: bool = True) -> None:
        self._engine = engine
        self.enabled = enabled
        self._registry: dict[str, RunHandle] = {}
        self._guard = threading.Lock()
        self._worker_idents: set[int] = set()  # 后台工作线程 ident（自调用 run_stream 放行）
        # 会话级同步取消登记（sid→reason）：飞书同步 run（engine.run 直驱，登记于
        # engine._sync_active）不在 registry，/stop 经此落取消标记；生命周期与 run
        # 对齐（lifecycle 注册时清残留、finally 注销时移除）。
        self._sync_cancelled: dict[str, str] = {}

    # ── 查询 ──
    def is_running(self, session_id: str) -> bool:
        """同会话是否有进行中 run（B5 跨入口互斥查询用）."""
        with self._guard:
            return session_id in self._registry

    def has_running(self) -> bool:
        """是否存在任意后台run；workspace切换用全局根安全门。"""
        with self._guard:
            return bool(self._registry)

    def is_worker(self) -> bool:
        """当前线程是否为后台 run 工作线程（engine 入口自调用放行）."""
        return threading.get_ident() in self._worker_idents

    def is_sync_active(self, session_id: str) -> bool:
        """同步 run 是否活跃于该会话（EVO-20260817 审查 P0-3: 后台 start 互斥）."""
        engine = getattr(self, "_engine", None)
        if engine is None:
            return False
        guard = getattr(engine, "_sync_guard", None)
        if guard is None:
            return False  # 旧装配无同步注册表 → 跳过（fail-open 不阻断）
        with guard:
            return session_id in engine._sync_active

    def get_handle(self, session_id: str) -> dict | None:
        """只读快照（B1：不暴露裸可变 handle）."""
        with self._guard:
            h = self._registry.get(session_id)
            return h.snapshot() if h else None

    def enqueue_interjection(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        expected_run_generation: str | None = None,
    ) -> bool:
        """Queue one human interjection into the currently running generation.

        This is intentionally process-local and run-owned: the durable queue item is the
        transport/source-of-truth, while this mailbox is only the handoff into the exact
        live worker.  The engine worker consumes it at a safe model-round boundary.
        """
        with self._guard:
            h = self._registry.get(session_id)
            if h is None or h.status != "running" or h.cancelled:
                return False
            expected = str(expected_run_generation or "")
            if expected and expected != h.run_generation:
                return False
            h.interjections.append(dict(payload))
            return True

    def take_interjections(self, session_id: str) -> list[dict[str, Any]]:
        """Atomically drain pending human interjections for the current run worker."""
        with self._guard:
            h = self._registry.get(session_id)
            if h is None or h.status != "running" or not h.interjections:
                return []
            rows = list(h.interjections)
            h.interjections.clear()
            return rows

    @staticmethod
    def acknowledge_interjection(payload: dict[str, Any]) -> None:
        """Best-effort transport acknowledgement after the engine persisted the steer."""
        callback = payload.get("_on_received")
        if callable(callback):
            try:
                callback()
            except Exception:  # noqa: BLE001 - UI acknowledgement cannot rewrite run truth
                logger.warning("interjection acknowledgement failed (fail-open)", exc_info=True)

    def cancel(self, session_id: str, reason: str = CANCEL_REASON_USER_STOP) -> bool:
        """请求取消进行中的 run（2026-08-23 停止按钮修复；双路径扩展）.

        - 置 handle.cancelled=True（registry 命中，后台 run）或写入 _sync_cancelled
          登记（registry 未命中且同步 run 活跃，飞书 engine.run 直驱路径）→
          引擎在 LLM 流/轮次/同步返回检查点提前终止
        - 对该会话发起 session 定向工具取消；支持的长工具可立即释放外部进程
        - reason: 取消原因标记位（可扩展枚举，默认 user_stop；Web 停止按钮零改动
          自动获得同语义，运维清理路径显式传 runner_stop 保持可区分）
        - 返回 True=该会话确有进行中 run（后台或同步）且已请求取消；False=无 run
        """
        run_generation = ""
        with self._guard:
            h = self._registry.get(session_id)
            if h is not None:
                h.cancelled = True
                h.cancel_reason = reason
                run_generation = str(h.run_generation or "")
            elif self.is_sync_active(session_id):
                self._sync_cancelled[session_id] = reason
                active_generation = getattr(getattr(self._engine, "session", None), "active_run_generation", None)
                if callable(active_generation):
                    run_generation = str(active_generation(session_id) or "")
            else:
                return False
        registry = getattr(self._engine, "registry", None)
        cancel_session = getattr(registry, "cancel_session", None)
        if callable(cancel_session):
            try:
                cancel_session(session_id, run_generation=run_generation)
            except Exception:  # noqa: BLE001 — 工具硬取消失败仍保留循环 cancelled 标志
                logger.warning("后台 run 工具取消失败（fail-open）: session=%s", session_id, exc_info=True)
        return True

    def is_cancelled(self, session_id: str) -> bool:
        """该会话 run 是否已被请求取消（引擎主循环轮询检查；registry 优先+同步登记回查）."""
        with self._guard:
            h = self._registry.get(session_id)
            if h is not None:
                return h.cancelled
            return session_id in self._sync_cancelled

    def cancel_reason(self, session_id: str) -> str:
        """该会话取消原因（""=未取消；engine 检查点原因捕获数据源，双路径同构）."""
        with self._guard:
            h = self._registry.get(session_id)
            if h is not None:
                return h.cancel_reason if h.cancelled else ""
            return self._sync_cancelled.get(session_id, "")

    def discard_sync_cancel(self, session_id: str) -> None:
        """移除会话级同步取消登记（同步 run 注册清残留/finally 注销时调用，防旧标记误杀下一轮）."""
        with self._guard:
            self._sync_cancelled.pop(session_id, None)

    def note_active(self, session_id: str, round_no: int | None = None) -> None:
        """EVO-20260825（任务12 §5.12）: 每轮记录活跃——刷新 last_active_ts + 当前轮数.

        引擎主循环每轮边界调用；残留 run 巡检据此区分"仍在跑"与"僵尸滞留"。
        """
        try:
            with self._guard:
                h = self._registry.get(session_id)
                if h is None or h.status != "running":
                    return
                h.last_active_ts = time.time()
                if round_no is not None:
                    h.current_round = round_no
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("runner.note_active 异常（fail-open）")

    # ── 运维（任务12 §5.12）──
    def inspect_stale_runs(self) -> list[dict]:
        """启动巡检：列出超过 STALE_RUN_INSPECT_HOURS 无活跃的后台 run.

        依据 handle.last_active_ts（每轮 note_active 刷新）；输出 WARN 日志
        「残留 run 巡检：发现 N 个超过 X 小时无活跃的后台 run：{run_ids}」。
        """
        try:
            threshold = _STALE_RUN_INSPECT_HOURS * 3600
            now = time.time()
            stale: list[dict] = []
            with self._guard:
                items = list(self._registry.items())
            for run_id, h in items:
                if h.status != "running":
                    continue
                if now - h.last_active_ts <= threshold:
                    continue
                stale.append({
                    "run_id": run_id,
                    "running_hours": (now - h.started_at) / 3600,
                    "rounds": h.current_round,
                })
            if stale:
                detail = ", ".join(
                    f"{s['run_id']}（运行 {s['running_hours']:.0f}h）" for s in stale
                )
                logger.warning(
                    "残留 run 巡检：发现 %d 个超过 %s 小时无活跃的后台 run：%s",
                    len(stale), int(_STALE_RUN_INSPECT_HOURS), detail,
                )
            return stale
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("inspect_stale_runs 异常（fail-open）")
            return []

    async def stop(self, run_id: str, *, operator: str = "admin") -> dict:
        """运维接口（任务12 §5.12）: 按 run_id 强制清理指定后台 run.

        流程：
        1. 输出确认清单（run_id + 运行时长 + 当前轮数）——RUN_CLEANUP_CONFIRMATION_REQUIRED=1
           时要求调用方二次确认（confirm=True）后才实际执行
        2. 设置 cancelled + 等待后台线程轮次检查点退出（超时 RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC）
        3. 从 registry 移除 handle、惰性移除 CacheHealthMonitor/PromptGuard 对应 session 分桶
        4. 审计日志写入 runner.stop 事件（engine._record_action 可用时）
        """
        try:
            with self._guard:
                h = self._registry.get(run_id)
                if h is None or h.status != "running":
                    logger.warning("run %s 不存在或已结束，跳过", run_id)
                    return {
                        "run_id": run_id,
                        "status": "skipped",
                        "reason": "not_found_or_ended",
                    }
                confirm = dict(h.snapshot())
            logger.info(
                "runner.stop 确认清单: run=%s 运行时长=%.1fh 当前轮数=%d 操作者=%s%s",
                run_id, (time.time() - confirm["started_at"]) / 3600,
                confirm["current_round"], operator,
                "（需二次确认）" if _RUN_CLEANUP_CONFIRMATION_REQUIRED else "",
            )
            # 设置取消标志 → 引擎主循环/LLM 流检查点退出（超时兜底强制移除）；
            # 运维清理显式传 runner_stop 与用户主动停止保持可区分
            self.cancel(run_id, reason=CANCEL_REASON_RUNNER_STOP)
            deadline = time.time() + _RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC
            while time.time() < deadline:
                with self._guard:
                    h = self._registry.get(run_id)
                    if h is None or h.status != "running":
                        break
                time.sleep(0.05)
            with self._guard:
                h = self._registry.get(run_id)
                still_running = h is not None and h.status == "running"
                if not still_running:
                    self._registry.pop(run_id, None)

            if still_running:
                # Python cannot safely kill an arbitrary blocked worker thread.  Hiding
                # its handle would turn a still-live run (and its EventBus/spool) into an
                # unobservable orphan.  Keep exact lifecycle truth registered; the worker
                # will remove itself and close the bus if/when it actually reaches a
                # cancellation/terminal boundary.
                record_action = getattr(self._engine, "_record_action", None)
                if callable(record_action):
                    try:
                        record_action("runner", "stop_timeout", f"{run_id} operator={operator}")
                    except Exception:  # noqa: BLE001
                        logger.debug("runner.stop timeout 审计写入 fail-open")
                logger.warning("runner.stop 超时，保留仍运行handle: run=%s", run_id)
                return {
                    "run_id": run_id,
                    "status": "shutdown_timeout",
                    "operator": operator,
                }

            # 惰性移除 session 分桶（monitor / guard）
            monitor = getattr(self._engine, "_cache_monitor", None)
            if monitor is not None:
                try:
                    monitor.reset_session(run_id)
                except Exception:  # noqa: BLE001
                    logger.debug("runner.stop reset_session(monitor) fail-open")
            guard = getattr(self._engine, "_cache_guard", None)
            if guard is not None:
                try:
                    guard.reset_session(run_id)
                except Exception:  # noqa: BLE001
                    logger.debug("runner.stop reset_session(guard) fail-open")
            record_action = getattr(self._engine, "_record_action", None)
            if callable(record_action):
                try:
                    record_action("runner", "stop", f"{run_id} operator={operator}")
                except Exception:  # noqa: BLE001
                    logger.debug("runner.stop 审计写入 fail-open")
            else:
                logger.info("runner.stop 审计: run=%s operator=%s", run_id, operator)
            return {"run_id": run_id, "status": "stopped", "operator": operator}
        except Exception as exc:  # noqa: BLE001 — 运维接口 fail-open
            logger.warning("runner.stop 异常: run=%s", run_id, exc_info=True)
            return {"run_id": run_id, "status": "error", "reason": str(exc)}

    def unsubscribe(self, session_id: str, q: queue.Queue) -> None:
        """订阅者退出（SSE 断连）时释放队列（B6：不再向其 put）.

        run 已完成（handle 已移除）时无可解除的订阅，返回即可（emit 已结束）.
        """
        with self._guard:
            h = self._registry.get(session_id)
            bus = h._bus if h is not None else None
        if bus is not None:
            bus.unsubscribe(q)

    # ── 启动 ──
    def start(
        self,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_mode: str | None = None,
        *,
        resume: bool = False,
        expected_run_generation: str | None = None,
        before_start: Callable[[Any], None] | None = None,
        expected_workspace_epoch: int | None = None,
        ingress: object | None = None,
        user_metadata: dict[str, Any] | None = None,
        terminal_callback: Callable[[str, str | None], None] | None = None,
    ) -> tuple[RunHandle | None, queue.Queue | None]:
        """注册 + 起后台线程；返回 (handle, queue)，调用方订阅消费.

        - resume=False（默认）: 同会话已有 running → (None, None)（调用方按 session_busy 处理）
        - resume=True: 同会话已有 running 且 expected_run_generation 精确匹配 →
          返回 (None, 新订阅队列)；缺失/不匹配 fail-closed，绝不订阅该 session 的
          "当前最新 run"。done 后 handle 已移除 → 返回 (None, None)。
        - disabled → (None, None)
        - ingress: R8.24-D D-D2（DT-1.3④盘点补齐）——后台 run 的 user 写入同样
          需要人类通道凭据（web 通道由 routes 调用方签发传入；fail-closed 下
          无凭据写入将被 guard 拒绝）。
        """
        if not self.enabled:
            return None, None
        workspace_guard = getattr(self._engine, "_workspace_transition_guard", None)
        acquired_workspace = True
        if workspace_guard is not None:
            acquired_workspace = workspace_guard.acquire(blocking=False)
        if not acquired_workspace:
            return None, None
        try:
            if (
                expected_workspace_epoch is not None
                and getattr(self._engine, "_workspace_epoch", expected_workspace_epoch)
                != expected_workspace_epoch
            ):
                from llm_loop.workspace.store import WorkspaceChangedError

                raise WorkspaceChangedError("请求解析会话后工作区已切换，请重新选择会话后重试")
            with self._guard:
                existing = self._registry.get(session_id)
                if existing is not None:
                    if resume:
                        # EVO-20260817 审查中危修复: done/error 广播后、registry pop 前的
                        # 窗口内 resume 会拿到"已结束"的 run → 订阅空队列永挂。
                        # 终态 handle 不再可订阅（调用方按"无进行中 run"处理）。
                        if existing.status in ("done", "error"):
                            return None, None
                        expected = str(expected_run_generation or "")
                        if not expected or expected != existing.run_generation:
                            raise RunGenerationMismatchError(
                                expected_run_generation=expected_run_generation,
                                actual_run_generation=existing.run_generation,
                            )
                        return None, existing._bus.subscribe()
                    return None, None
                # EVO-20260817 审查 P0-3: 同步 run 活跃时拒绝后台 start（双向互斥闭环）
                if not resume and self.is_sync_active(session_id):
                    return None, None
                if resume:
                    # resume 语义=订阅已有 run；无进行中 run 时无可订阅（不启动新 run）
                    return None, None
                handle = RunHandle(session_id=session_id)
                self._registry[session_id] = handle
                # _bus 在锁内赋值，避免unsubscribe观察到半初始化handle。
                bus = EventBus()
                handle._bus = bus
        finally:
            if workspace_guard is not None:
                workspace_guard.release()
        # before_start 在 worker 取得跨进程 run lease 后才执行；此处仅进程内占位。
        q = bus.subscribe()  # 先订阅再起线程（保证不丢 start 后首个事件）
        t = threading.Thread(
            target=self._consume,
            args=(
                session_id,
                user_text,
                model,
                reasoning_effort,
                reasoning_mode,
                before_start,
                handle,
                bus,
                ingress,
                user_metadata,
                terminal_callback,
            ),
            name=f"bg-run-{session_id[:8]}",
            daemon=True,  # B4: 进程退出不阻塞
        )
        t.start()
        return handle, q

    # ── 后台消费 ──
    @staticmethod
    def _notify_terminal(
        callback: Callable[[str, str | None], None] | None,
        status: str,
        detail: str | None,
    ) -> None:
        """Best-effort owner callback; subscriber lifecycle must not own run terminal truth."""
        if callback is None:
            return
        try:
            callback(status, detail)
        except Exception:  # noqa: BLE001 - queue/sidecar failure cannot rewrite run outcome
            logger.exception("background run terminal callback failed: status=%s", status)

    def _consume(
        self,
        session_id: str,
        user_text: str,
        model: str | None,
        reasoning_effort: str | None,
        reasoning_mode: str | None,
        before_start: Callable[[Any], None] | None,
        handle: RunHandle,
        bus: EventBus,
        ingress: object | None = None,
        user_metadata: dict[str, Any] | None = None,
        terminal_callback: Callable[[str, str | None], None] | None = None,
    ) -> None:
        """后台线程体：copy_context 传播（P0-5 模式）→ 迭代 run_stream → 广播终态."""
        self._worker_idents.add(threading.get_ident())
        try:
            ctx = contextvars.copy_context()

            def _run() -> Any:
                from llm_loop.core.run_context import current_run_generation

                generation_token = current_run_generation.set(handle.run_generation)
                run_kwargs: dict[str, Any] = {}
                try:
                    it: Any
                    if reasoning_effort is not None:
                        run_kwargs["reasoning_effort"] = reasoning_effort
                    if reasoning_mode is not None:
                        run_kwargs["reasoning_mode"] = reasoning_mode
                    if ingress is not None:
                        run_kwargs["ingress"] = ingress
                    if user_metadata is not None:
                        run_kwargs["user_metadata"] = user_metadata
                    if before_start is not None:
                        accepted_stream = getattr(self._engine, "_run_stream_with_acquired", None)
                        if not callable(accepted_stream):
                            raise RuntimeError("engine 不支持 accepted-boundary callback")
                        it = accepted_stream(
                            session_id, user_text, model,
                            on_run_acquired=before_start, **run_kwargs,
                        )
                    else:
                        it = self._engine.run_stream(session_id, user_text, model, **run_kwargs)
                    while True:
                        try:
                            delta = next(it)
                        except StopIteration as exc:
                            return exc.value
                        bus.emit({"type": "delta", "delta": delta})
                finally:
                    current_run_generation.reset(generation_token)

            result = ctx.run(_run)
            # The run itself owns terminal side effects. Subscribers may disconnect at any
            # point and therefore cannot be the sole owner of durable terminal callbacks.
            self._notify_terminal(terminal_callback, "completed", None)
            bus.emit({"type": "done", "result": result})
            with self._guard:
                handle.status = "done"
                handle.finished_at = time.time()
                self._registry.pop(session_id, None)
            bus.close()
        except Exception as exc:  # noqa: BLE001 — 后台异常如实广播，不泄漏线程
            logger.exception("后台 run 失败: session=%s", session_id)
            err = f"{type(exc).__name__}: {exc}"
            not_started = isinstance(exc, (SessionBusyError, QueuedIngressDurabilityError))
            if isinstance(exc, SessionBusyError):
                code = "session_busy"
            elif isinstance(exc, QueuedIngressDurabilityError):
                code = "queue_ingress_durability_unavailable"
            else:
                code = "internal_error"
            terminal_status = "not_started" if not_started else "failed"
            self._notify_terminal(terminal_callback, terminal_status, err)
            bus.emit({"type": "error", "error": err, "error_code": code})
            with self._guard:
                handle.status = "error"
                handle.error = err
                handle.finished_at = time.time()
                self._registry.pop(session_id, None)
            bus.close()
        finally:
            self._worker_idents.discard(threading.get_ident())


__all__ = [
    "SessionBusyError",
    "QueuedIngressDurabilityError",
    "RunHandle",
    "EventBus",
    "BackgroundRunner",
]
