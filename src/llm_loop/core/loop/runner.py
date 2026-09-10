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
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# EVO-20260825（任务12 §5.12）: 残留 run 巡检/清理配置（spec §6.11）
_STALE_RUN_INSPECT_HOURS = float(os.environ.get("STALE_RUN_INSPECT_HOURS", "24"))
_RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC = float(
    os.environ.get("RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC", "10.0")
)
_RUN_CLEANUP_CONFIRMATION_REQUIRED = bool(
    int(os.environ.get("RUN_CLEANUP_CONFIRMATION_REQUIRED", "1"))
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


@dataclass
class RunHandle:
    """一次后台 run 的句柄（状态仅 registry 锁内变更；对外用 snapshot 只读快照）.

    _bus 内部引用（unsubscribe 用，不对外暴露）.
    """

    session_id: str
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

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "cancelled": self.cancelled,
            "last_active_ts": self.last_active_ts,
            "current_round": self.current_round,
        }


class EventBus:
    """每 run 事件总线：订阅者队列集合 + 广播（thread-safe）+ 重放缓冲.

    emit 对当前订阅者逐一 put（快照副本，避免遍历中变更）；订阅者退出 unsubscribe
    后不再接收；单个订阅者 put 失败不影响其余（fail-open）。

    EVO-20260818（DSH 014 REFRESH-LIVE-CONTENT）: 重放缓冲——run 期间保留有界 delta
    历史（_history，上限 _HISTORY_MAX 条），subscribe 时先回放历史再实时。刷新/切回
    场景：新订阅者先收到已生成内容（中间状态可见），再收实时 delta。
    缓存影响：重放只进响应不落盘、不改历史序列 → 前缀缓存零影响。
    """

    _HISTORY_MAX = 500  # 重放历史上限
    _SUBSCRIBER_MAX = 1024  # 单慢消费者上限；done 含完整终态，可安全丢最旧 delta

    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._guard = threading.Lock()
        self._history: list[dict] = []

    @staticmethod
    def _put_latest(q: queue.Queue, event: dict) -> None:
        """非阻塞写队列；满时丢最旧，保证最新事件（尤其 done/error）可进入。"""
        try:
            q.put_nowait(event)
            return
        except queue.Full:
            logger.debug("事件总线订阅者队列已满，准备淘汰最旧事件")
        try:
            q.get_nowait()
        except queue.Empty:
            logger.debug("事件总线满队列在淘汰前已被消费者取空")
        try:
            q.put_nowait(event)
        except queue.Full:
            # 极窄并发窗口：消费者/生产者同时竞争时 fail-open，不能阻塞后台 run。
            logger.warning("事件总线慢消费者队列持续满，丢弃最新非关键事件")

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._SUBSCRIBER_MAX)
        with self._guard:
            self._subs.add(q)
            # 重放历史最大 500 < subscriber 1024，不会在初始回放阶段截断。
            for evt in self._history:
                self._put_latest(q, evt)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._guard:
            self._subs.discard(q)

    def emit(self, event: dict) -> None:
        with self._guard:
            # 缓冲写入（有界：超限丢弃最旧）
            self._history.append(event)
            if len(self._history) > self._HISTORY_MAX:
                self._history = self._history[-self._HISTORY_MAX:]
            subs = list(self._subs)
        for q in subs:
            try:
                self._put_latest(q, event)
            except Exception:  # noqa: BLE001 — 单订阅者失败不影响其余
                logger.warning("事件总线 put 失败（忽略）", exc_info=True)


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
        with self._guard:
            h = self._registry.get(session_id)
            if h is not None:
                h.cancelled = True
                h.cancel_reason = reason
            elif self.is_sync_active(session_id):
                self._sync_cancelled[session_id] = reason
            else:
                return False
        registry = getattr(self._engine, "registry", None)
        cancel_session = getattr(registry, "cancel_session", None)
        if callable(cancel_session):
            try:
                cancel_session(session_id)
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
                self._registry.pop(run_id, None)

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
        before_start: Callable[[Any], None] | None = None,
        expected_workspace_epoch: int | None = None,
        ingress: object | None = None,
        user_metadata: dict[str, Any] | None = None,
        terminal_callback: Callable[[str, str | None], None] | None = None,
    ) -> tuple[RunHandle | None, queue.Queue | None]:
        """注册 + 起后台线程；返回 (handle, queue)，调用方订阅消费.

        - resume=False（默认）: 同会话已有 running → (None, None)（调用方按 session_busy 处理）
        - resume=True: 同会话已有 running → 返回 (None, 新订阅队列)（重连订阅已有 run，
          刷新/切回会话场景；done 后 handle 已移除 → 返回 (None, None)）
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
                run_kwargs: dict[str, Any] = {}
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

            result = ctx.run(_run)
            # The run itself owns terminal side effects. Subscribers may disconnect at any
            # point and therefore cannot be the sole owner of durable terminal callbacks.
            self._notify_terminal(terminal_callback, "completed", None)
            bus.emit({"type": "done", "result": result})
            with self._guard:
                handle.status = "done"
                handle.finished_at = time.time()
                self._registry.pop(session_id, None)
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
        finally:
            self._worker_idents.discard(threading.get_ident())


__all__ = [
    "SessionBusyError",
    "QueuedIngressDurabilityError",
    "RunHandle",
    "EventBus",
    "BackgroundRunner",
]
