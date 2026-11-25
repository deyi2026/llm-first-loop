"""排队消息恢复语义服务端化（SPEC-20260923-queue-recovery-server-owned）.

事故（2026-09-22 13:27 → 09-23 07:0x）：消息在重启窗口被持久化排队并承诺
"恢复后自动继续"，但承诺的承载是浏览器派发循环——服务重启后循环死亡，承诺
失效；取消后的项连刷新也无法续。

- **A（兜底派发）**：常驻巡检——会话空闲且存在到期 queued 项（项龄超过
  阈值，避让浏览器正常领取窗口）时，服务端经同一 ``dispatch_claim`` 原子
  FIFO 认领并按 schedule-wake 同构路径无头执行该轮。浏览器与服务端竞争
  认领天然单赢家；屏障期不派发（§8.2-2 语义零变化）；领取后无法启动则
  回滚 queued（与浏览器领取方义务一致）。
- **B（恢复重排）**：barrier 窗口入队带 ``origin=barrier_window`` 机械
  标记；非 user 取消的此类项在恢复期以**新项**重排（origin=recovery_requeue，
  原终态不改写——诚实溯源，learning journal crash_recovered 先例同构）。

机械边界（治理对照）：两案均为恢复语义管道（消息必达，agency 放大），
无语义裁决门；不解析任何文本内容。
"""

from __future__ import annotations

import logging
import queue as _queue
import threading
import time
from typing import TYPE_CHECKING, Any

from llm_loop.runtime.admission_barrier import task_admission_barrier
from llm_loop.web.human_turn_queue import HumanTurnQueue
from llm_loop.workspace.store import WorkspaceChangedError

if TYPE_CHECKING:  # pragma: no cover - 类型-only import
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

_TICK_S = 15.0
_MIN_AGE_S = 60.0
_WAKE_MAX = 64  # 事件唤醒队列上限（有界：满则丢弃，tick 兜底，不放大生产者）
_BACKOFF_BASE_S = 60.0  # A05 单目标连续失败退避基数（有界指数）
_BACKOFF_CAP_S = 600.0  # A05 退避上限，保证最终重试可达
_REQUEUE_MAX_AGE_S = 86400.0  # 恢复重排只看最近 24h 的取消项（有界）


def recovery_requeue(
    hq: HumanTurnQueue,
    *,
    now: float | None = None,
    max_age_s: float = _REQUEUE_MAX_AGE_S,
) -> list[dict[str, Any]]:
    """B：恢复重排——非 user 取消的 barrier 窗口项以新项复活.

    只认机械标记（origin=barrier_window 且 cancelled_by≠user）；原终态记录
    不改写；新项携带 recovery_requeue 溯源与原操作号。
    """
    ts = now if now is not None else time.time()
    requeued: list[dict[str, Any]] = []
    for it in hq.snapshot_items():
        if it.get("status") != "cancelled":
            continue
        if it.get("origin") != "barrier_window":
            continue
        if str(it.get("cancelled_by") or "system") == "user":
            continue
        terminal_at = float(it.get("terminal_at") or 0)
        if terminal_at and ts - terminal_at > max_age_s:
            continue
        fresh = hq.enqueue(
            str(it.get("session_id") or ""),
            str(it.get("message") or ""),
            attachments=list(it.get("attachments") or []),
            model=it.get("model"),
            model_change=bool(it.get("model_change")),
            reasoning_effort=it.get("reasoning_effort"),
            reasoning_mode=str(it.get("reasoning_mode") or "auto"),
            attachment_facts=list(it.get("attachment_facts") or []),
            origin="recovery_requeue",
            origin_operation_id=str(it.get("origin_operation_id") or ""),
        )
        requeued.append(fresh)
        logger.info(
            "queue recovery requeued: %s -> %s sid=%s origin_op=%s",
            it.get("queue_id"),
            fresh.get("queue_id"),
            str(it.get("session_id") or "")[:8],
            it.get("origin_operation_id"),
        )
    return requeued


class QueueServerFallback:
    """A：服务端兜底派发（常驻巡检线程；单实例，daemon）.

    与浏览器派发循环共存：同一 ``dispatch_claim`` 原子 FIFO，竞争单赢家；
    服务端仅在项龄超过 ``min_age_s``（默认 60s）时参与，正常节奏完全
    归浏览器。屏障期（web_queue_dispatch 准入）整 tick 跳过。
    """

    def __init__(
        self,
        engine: LoopEngine,
        hq: HumanTurnQueue,
        *,
        tick_s: float = _TICK_S,
        min_age_s: float = _MIN_AGE_S,
        backoff_base_s: float = _BACKOFF_BASE_S,
        backoff_cap_s: float = _BACKOFF_CAP_S,
    ) -> None:
        self._engine = engine
        self._hq = hq
        self._tick_s = max(1.0, float(tick_s))
        self._min_age_s = max(0.0, float(min_age_s))
        self._backoff_base_s = max(0.0, float(backoff_base_s))
        self._backoff_cap_s = max(1.0, float(backoff_cap_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # M1 事件唤醒（SA-M1M3-20261125-1236）：入队/run 终态等事件即时请求
        # 派发目标会话——正常空闲路径 P95 目标 ≤5s，15s tick + 60s min_age
        # 只保留为兜底（不再作为正常路径）。有界队列：满则丢弃（tick 兜底），
        # 不放大生产者。
        self._wake: _queue.Queue[str] = _queue.Queue(maxsize=_WAKE_MAX)
        # A05 单目标失败隔离：连续启动失败 → 有界指数退避（不阻塞其他目标）；
        # 派发成功即解除；工作区切换竞态不计入失败（见 _execute_claimed）。
        self._fail_streak: dict[str, int] = {}
        self._defer_until: dict[str, float] = {}
        # M0 workspace/epoch 绑定（SA-RESUME-20261125）：派发身份=引擎工作区根
        # （engine.workspace_root，与 HumanTurnQueue 盖章同源）；缺省/空=测试
        # 注入或未显式指定 → 不启用绑定过滤（遗留行为不变）。
        self._workspace_scope = (
            str(getattr(engine, "workspace_root", "") or "") or None
        )

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="queue-server-fallback"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 启动即执行一次 B 恢复重排（服务重启完成语义）
        try:
            revived = recovery_requeue(self._hq)
            if revived:
                logger.info("queue recovery requeue at startup: %d item(s)", len(revived))
        except Exception:  # noqa: BLE001 - 自愈：单次失败不退出
            logger.exception("queue recovery requeue failed at startup")
        # 二审 P1-2（SA-REVIEW-FIX-20261125）：全表巡检改为单调时钟绝对截止
        # ——事件只触发单目标直达，巡检无论 wake 多忙都按 deadline 有界执行。
        # 旧实现仅在 wake 空满 tick_s 后才 tick_once，持续 poke（每次 enqueue/
        # run 终态都会 poke）会令全表扫描无限饥饿：退避到期、唤醒队列满被丢
        # 弃、重启恢复的条目都可能永久滞留。
        next_full_scan_deadline = time.monotonic() + self._tick_s
        while not self._stop.is_set():
            sid: str | None = None
            try:
                remaining = max(0.0, next_full_scan_deadline - time.monotonic())
                sid = self._wake.get(timeout=min(remaining, self._tick_s))
            except _queue.Empty:
                pass
            if self._stop.is_set():
                break
            due_full_scan = time.monotonic() >= next_full_scan_deadline
            try:
                if sid is not None:
                    # M1 事件路径：已知目标确定性直达（R02/R08），不等 tick
                    # 与 min_age。
                    self._dispatch_session_now(sid)
                if due_full_scan:
                    self.tick_once()
                    next_full_scan_deadline = time.monotonic() + self._tick_s
            except Exception:  # noqa: BLE001 - 单次循环失败不退出
                logger.exception("queue server fallback cycle failed")

    def poke_session(self, sid: str) -> bool:
        """M1 事件唤醒（R08 最小有界）：入队/run 终态等事件到达时请求立即
        派发该目标，不等 15s tick 与 60s min_age。

        有界：唤醒队列满则丢弃（tick 兜底），不放大生产者；失败不重试循环
        （退避由 _defer_until 既有 A05 隔离承担，busy 等竞态由下一事件或
        tick 兜底）。已知目标直达，不做全表扫描。
        """
        sid = str(sid or "")
        if not sid:
            return False
        try:
            self._wake.put_nowait(sid)
            return True
        except _queue.Full:
            logger.debug("queue fallback wake full, poke dropped: sid=%s", sid[:8])
            return False

    def _dispatch_session_now(self, sid: str) -> int:
        """事件直达单目标：跳过 min_age（事件语义=刚入队/刚空闲），保留屏障/
        liveness/A05 退避/epoch 守卫与 scope 裁决（与 tick 同一原子路径）.
        """
        runner = getattr(self._engine, "runner", None)
        if runner is None or not getattr(runner, "enabled", True):
            return 0
        settings = getattr(self._engine, "settings", None)
        data_dir = str(getattr(settings, "data_dir", "./data"))
        # §8.2-2 零变化：屏障期不派发（领取只会再被屏障拒绝）
        if task_admission_barrier(data_dir, "web_queue_dispatch") is not None:
            return 0
        now = time.time()
        defer_until = self._defer_until.get(sid)
        if defer_until is not None and now < defer_until:
            return 0  # A05 退避中：不放大失败目标（tick 到期后自然重试）
        try:
            if runner.is_running(sid) or runner.is_sync_active(sid):
                return 0  # 会话忙：条目留队，待 run 终态事件再唤醒
        except Exception:  # noqa: BLE001 - one target probe must not stall others
            logger.exception("queue fallback liveness probe failed: sid=%s", sid[:8])
            return 0
        tick_epoch = getattr(self._engine, "_workspace_epoch", None)
        claimed = self._hq.dispatch_claim(
            sid,
            claimed_by="server-fallback",
            expected_workspace_scope=self._workspace_scope,
        )
        if not claimed:
            return 0  # 队首在途/scope HOLD/他人赢（正常收敛）
        return self._execute_claimed(
            runner, sid, claimed, expected_workspace_epoch=tick_epoch
        )

    # ------------------------------------------------------- A05 目标失败隔离

    def _record_start_failure(self, sid: str) -> None:
        streak = self._fail_streak.get(sid, 0) + 1
        self._fail_streak[sid] = streak
        delay = min(self._backoff_base_s * (2 ** (streak - 1)), self._backoff_cap_s)
        self._defer_until[sid] = time.time() + delay
        logger.warning(
            "queue fallback start failure defer: sid=%s streak=%d defer_s=%.0f",
            sid[:8],
            streak,
            delay,
        )

    def quarantine_status(self) -> dict[str, dict[str, float | int]]:
        """A05 可查询隔离面：单目标连续失败计数与退避到期（无退避目标不出现）."""
        now = time.time()
        return {
            sid: {
                "fail_streak": int(self._fail_streak.get(sid, 0)),
                "defer_until": until,
                "deferred_s": max(0.0, until - now),
            }
            for sid, until in self._defer_until.items()
        }

    # ------------------------------------------------------------------ 巡检

    def tick_once(self) -> int:
        """单次巡检：回收孤儿插话项、认领并执行到期 queued 项；返回本轮启动的 run 数."""
        runner = getattr(self._engine, "runner", None)
        if runner is None or not getattr(runner, "enabled", True):
            return 0
        # 孤儿回收在屏障检查之前：回滚≠派发（不启动 run），与 _load() 重启
        # 恢复同构；屏障只约束 dispatch 领取（§8.2-2）。
        self._reap_orphan_interjects(runner)
        settings = getattr(self._engine, "settings", None)
        data_dir = str(getattr(settings, "data_dir", "./data"))
        # §8.2-2 零变化：屏障期不派发（领取只会再被屏障拒绝）
        if task_admission_barrier(data_dir, "web_queue_dispatch") is not None:
            return 0

        now = time.time()
        # M1（SA-M1M3-20261125-1236）：tick 与事件路径共用 _dispatch_session_now
        # ——同一原子裁决（屏障/liveness/A05 退避/epoch 守卫/scope 队首阻断，
        # M0 SA-RESUME-20261125 语义原样），消除双路径漂移；min_age 由
        # _due_sessions 过滤，tick 兜底节奏不变。
        started = 0
        for sid, _oldest in self._due_sessions(now):
            started += self._dispatch_session_now(sid)
        return started

    def _reap_orphan_interjects(self, runner: Any) -> None:
        """interject_pending 孤儿回收：live run 已消失/换代的项回滚 queued.

        enqueue_interjection 接受后 run 若在轮边界消费 mailbox 前终止，该项
        会停在 interject_pending（此前仅进程重启 _load() 恢复）。判据与
        queue-interject 端点 CAS 同构：get_handle 为空或代次已换。runner 无
        get_handle 能力时保守跳过（退化为重启恢复现状）。
        """
        get_handle = getattr(runner, "get_handle", None)
        if not callable(get_handle):
            return

        def _alive(sid: str) -> str | None:
            try:
                handle = get_handle(sid)
            except Exception:  # noqa: BLE001 - 探测失败视同无 live run
                return None
            if not handle:
                return None
            return str(handle.get("run_generation") or "")

        requeued = self._hq.reap_orphan_interjects(_alive)
        if requeued:
            logger.info(
                "queue recovery reaped orphan interject(s): %d item(s)", len(requeued)
            )

    def _due_sessions(self, now: float) -> list[tuple[str, dict[str, Any]]]:
        """每会话最老的 queued 项已达龄 → (sid, oldest) 列表（去重保序）."""
        seen: dict[str, dict[str, Any]] = {}
        for it in self._hq.snapshot_items():
            if it.get("status") != "queued":
                continue
            sid = str(it.get("session_id") or "")
            if not sid:
                continue
            created_at = float(it.get("created_at") or 0)
            if now - created_at < self._min_age_s:
                continue
            current = seen.get(sid)
            if current is None or created_at < float(current.get("created_at") or 0):
                seen[sid] = it
        return list(seen.items())

    def _execute_claimed(
        self,
        runner: Any,
        sid: str,
        claimed: dict[str, Any],
        expected_workspace_epoch: int | None = None,
    ) -> int:
        qid = str(claimed.get("queue_id") or "")
        message = str(claimed.get("message") or "")

        def _terminal(status: str, run_error: str | None) -> None:
            try:
                self._hq.mark_terminal(sid, qid, status, run_error)
            except Exception:  # noqa: BLE001 - 回写失败只记日志
                logger.exception(
                    "queue fallback terminal 回写失败: sid=%s qid=%s status=%s",
                    sid[:8], qid, status,
                )

        # P1-1：冻结 attachment_facts（含 realtime 视觉证据 evidence_refs）必须
        # 进入 run 输入（runner.start → run_stream user_metadata，与
        # /chat/stream 同构契约）；否则兜底派发的视觉 turn 会静默丢失证据。
        frozen_facts = list(claimed.get("attachment_facts") or [])
        user_metadata: dict[str, Any] | None = None
        if qid:
            user_metadata = {"human_turn_queue_id": qid}
            if frozen_facts:
                user_metadata["attachments"] = frozen_facts

        try:
            from llm_loop.core.trace_leak.ingress_token import issue_ingress

            # expected_workspace_epoch（M0 绑定）：None 时 runner 既有守卫缺省
            # 跳过（测试注入/无代次概念的引擎不受影响）。
            handle, _q = runner.start(
                sid,
                message,
                model=claimed.get("model"),
                reasoning_effort=claimed.get("reasoning_effort"),
                reasoning_mode=str(claimed.get("reasoning_mode") or "auto"),
                ingress=issue_ingress("web"),
                terminal_callback=_terminal,
                user_metadata=user_metadata,
                expected_workspace_epoch=expected_workspace_epoch,
            )
        except WorkspaceChangedError:
            # 工作区切换竞态：环境级回滚，不计入目标失败退避（A05 语义分离）
            logger.info(
                "queue fallback workspace changed, requeued: sid=%s qid=%s",
                sid[:8],
                qid,
            )
            self._hq.release(sid, qid)
            return 0
        except Exception:  # noqa: BLE001 - 启动异常回滚保持 FIFO
            logger.exception("queue fallback start failed: sid=%s qid=%s", sid[:8], qid)
            self._hq.release(sid, qid)
            self._record_start_failure(sid)
            return 0
        if handle is None:
            # 二审 P2-2（SA-REVIEW-FIX-20261125）：session_busy 竞态与不明失败
            # 分离——start 前置 liveness probe 已挡住常态 busy；此处 handle=None
            # 若复核仍明确 busy（probe 后竞态窗口），属竞态不是目标故障：不计入
            # A05 失败退避（否则该目标自身 run 终态唤醒会在退避窗口被 defer
            # 吞掉，60s→600s 内条目滞留），条目回滚留队等终态事件/tick 兜底。
            # probe 异常或复核不 busy=不明失败：保留既有退避语义（fail-closed）。
            self._hq.release(sid, qid)
            try:
                busy_now = bool(runner.is_running(sid)) or bool(
                    runner.is_sync_active(sid)
                )
            except Exception:  # noqa: BLE001 - 复核不了按不明失败处理
                busy_now = False
            if not busy_now:
                self._record_start_failure(sid)
            else:
                logger.info(
                    "queue fallback session_busy race, requeued without backoff: "
                    "sid=%s qid=%s",
                    sid[:8],
                    qid,
                )
            return 0
        # 派发成功：解除该目标的失败退避（A05 隔离随成功收敛）
        self._fail_streak.pop(sid, None)
        self._defer_until.pop(sid, None)
        logger.info(
            "queue server-fallback dispatched: sid=%s qid=%s", sid[:8], qid
        )
        return 1
