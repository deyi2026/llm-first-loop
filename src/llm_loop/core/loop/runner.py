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
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class SessionBusyError(RuntimeError):
    """同会话已有进行中的后台 run（跨入口互斥，设计 B5/B7）.

    engine.run_stream 入口检查抛出；调用方（web /chat、飞书、CLI）捕获转友好提示。
    """


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

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class EventBus:
    """每 run 事件总线：订阅者队列集合 + 广播（thread-safe）.

    emit 对当前订阅者逐一 put（快照副本，避免遍历中变更）；订阅者退出 unsubscribe
    后不再接收；单个订阅者 put 失败不影响其余（fail-open）。
    """

    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._guard = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._guard:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._guard:
            self._subs.discard(q)

    def emit(self, event: dict) -> None:
        with self._guard:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put(event)
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

    # ── 查询 ──
    def is_running(self, session_id: str) -> bool:
        """同会话是否有进行中 run（B5 跨入口互斥查询用）."""
        with self._guard:
            return session_id in self._registry

    def is_worker(self) -> bool:
        """当前线程是否为后台 run 工作线程（engine 入口自调用放行）."""
        return threading.get_ident() in self._worker_idents

    def get_handle(self, session_id: str) -> dict | None:
        """只读快照（B1：不暴露裸可变 handle）."""
        with self._guard:
            h = self._registry.get(session_id)
            return h.snapshot() if h else None

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
        self, session_id: str, user_text: str, model: str | None = None
    ) -> tuple[RunHandle | None, queue.Queue | None]:
        """注册 + 起后台线程；返回 (handle, queue)，调用方订阅消费.

        同会话已有 running → (None, None)（调用方按 session_busy 处理）；
        disabled → (None, None)。
        """
        if not self.enabled:
            return None, None
        with self._guard:
            if session_id in self._registry:
                return None, None
            handle = RunHandle(session_id=session_id)
            self._registry[session_id] = handle
        bus = EventBus()
        handle._bus = bus  # unsubscribe 用（内部引用）
        q = bus.subscribe()  # 先订阅再起线程（保证不丢 start 后首个事件）
        t = threading.Thread(
            target=self._consume,
            args=(session_id, user_text, model, handle, bus),
            name=f"bg-run-{session_id[:8]}",
            daemon=True,  # B4: 进程退出不阻塞
        )
        t.start()
        return handle, q

    # ── 后台消费 ──
    def _consume(
        self,
        session_id: str,
        user_text: str,
        model: str | None,
        handle: RunHandle,
        bus: EventBus,
    ) -> None:
        """后台线程体：copy_context 传播（P0-5 模式）→ 迭代 run_stream → 广播终态."""
        self._worker_idents.add(threading.get_ident())
        try:
            ctx = contextvars.copy_context()

            def _run() -> Any:
                it = self._engine.run_stream(session_id, user_text, model)
                while True:
                    try:
                        delta = next(it)
                    except StopIteration as exc:
                        return exc.value
                    bus.emit({"type": "delta", "delta": delta})

            result = ctx.run(_run)
            bus.emit({"type": "done", "result": result})
            with self._guard:
                handle.status = "done"
                handle.finished_at = time.time()
                self._registry.pop(session_id, None)
        except Exception as exc:  # noqa: BLE001 — 后台异常如实广播，不泄漏线程
            logger.exception("后台 run 失败: session=%s", session_id)
            err = f"{type(exc).__name__}: {exc}"
            bus.emit({"type": "error", "error": err})
            with self._guard:
                handle.status = "error"
                handle.error = err
                handle.finished_at = time.time()
                self._registry.pop(session_id, None)
        finally:
            self._worker_idents.discard(threading.get_ident())


__all__ = ["SessionBusyError", "RunHandle", "EventBus", "BackgroundRunner"]
