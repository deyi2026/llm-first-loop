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
import threading
import time
from typing import TYPE_CHECKING, Any

from llm_loop.runtime.admission_barrier import task_admission_barrier
from llm_loop.web.human_turn_queue import HumanTurnQueue

if TYPE_CHECKING:  # pragma: no cover - 类型-only import
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

_TICK_S = 15.0
_MIN_AGE_S = 60.0
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
    ) -> None:
        self._engine = engine
        self._hq = hq
        self._tick_s = max(1.0, float(tick_s))
        self._min_age_s = max(0.0, float(min_age_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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
        while not self._stop.wait(self._tick_s):
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001 - 单次 tick 失败不退出
                logger.exception("queue server fallback tick failed")

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
        started = 0
        for sid, _oldest in self._due_sessions(now):
            if runner.is_running(sid) or runner.is_sync_active(sid):
                continue
            claimed = self._hq.dispatch_claim(sid, claimed_by="server-fallback")
            if not claimed:
                continue  # 浏览器/另一领取方赢了（正常收敛）
            started += self._execute_claimed(runner, sid, claimed)
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

    def _execute_claimed(self, runner: Any, sid: str, claimed: dict[str, Any]) -> int:
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

            handle, _q = runner.start(
                sid,
                message,
                model=claimed.get("model"),
                reasoning_effort=claimed.get("reasoning_effort"),
                reasoning_mode=str(claimed.get("reasoning_mode") or "auto"),
                ingress=issue_ingress("web"),
                terminal_callback=_terminal,
                user_metadata=user_metadata,
            )
        except Exception:  # noqa: BLE001 - 启动异常回滚保持 FIFO
            logger.exception("queue fallback start failed: sid=%s qid=%s", sid[:8], qid)
            self._hq.release(sid, qid)
            return 0
        if handle is None:
            # session_busy 等竞态：回滚 queued（与浏览器领取方义务一致）
            self._hq.release(sid, qid)
            return 0
        logger.info(
            "queue server-fallback dispatched: sid=%s qid=%s", sid[:8], qid
        )
        return 1
