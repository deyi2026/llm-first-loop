"""企微智能机器人 WS 桥（M0-4，SDK 连接生命周期 + 线程模型）.

线程模型（平移飞书桥实测结论，设计文档 §4.4）：
- SDK 的 asyncio 事件循环跑在独立线程（new_event_loop + run_forever）；
- SDK 事件回调（_on_sdk_message/_on_sdk_event，运行在 SDK loop 线程）
  只做 marshal + put_nowait 立即返回——绝不在回调内跑推理（飞书桥实测：
  分钟级推理阻塞 loop → 心跳停发 → 服务端断开）；
- 单 worker 线程（_worker_loop）从有界队列取消息 → dispatcher 解包 →
  handler.handle（engine.run 在此执行）→ 回复；
- 回复（send_text，worker 线程调用）经 asyncio.run_coroutine_threadsafe
  投递回 SDK loop 执行，绑定同一次回调的 req_id（企微协议硬要求）。

单连接独占（设计文档 §6 高风险项）：同一机器人同时只能一个长连接，
新连接会踢掉旧连接（LFL 主进程与 DSH 子代理互踢事故场景）——
_SingleInstanceLock 本地文件锁（fcntl.flock 非阻塞独占）拒绝第二个实例。

断线感知（SDK EventType 缺 disconnected_event 的仓库侧补齐）：
- 连接层：SDK "disconnected" 客户端事件（ws.py:205-206 ConnectionClosed 触发），
  本侧记日志更新状态；非人为退出时 SDK 内部自动重连；
- 事件帧层：aibot_event_callback 帧 eventtype=="disconnected_event"
  （dispatcher.is_disconnected_event，官方协议描述被踢时推送；实际触发
  时机未实测——设计文档 §七.3）→ 记 ERROR 告警。
"""

import asyncio
import fcntl
import logging
import os
import queue
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from .config import WeComConfig
from .dispatcher import is_disconnected_event, parse_event_frame, parse_message_frame
from .messages import WeComMessage

logger = logging.getLogger(__name__)

# 有界队列容量：对齐飞书桥 _MAX_MSG_QUEUE=64（设计文档 §4.4）
_MAX_MSG_QUEUE = 64
# worker join / 回复投递 / 断开收尾的时间预算（秒；对齐飞书桥 drain 预算量级）
_WORKER_JOIN_TIMEOUT_S = 4.0
_REPLY_TIMEOUT_S = 15.0
_DISCONNECT_TIMEOUT_S = 10.0
_CONNECT_TIMEOUT_S = 30.0
# 单实例锁文件名（锁文件目录默认 {DATA_DIR}，可经 lock_path 注入）
_LOCK_FILENAME = "wecom_bridge.lock"


class _SdkLoggerAdapter:
    """SDK Logger 协议（debug/info/warn/error）→ logging.Logger 适配器."""

    def __init__(self, target: logging.Logger) -> None:
        self._target = target

    def debug(self, message: str, *args: Any) -> None:
        self._target.debug(message, *args)

    def info(self, message: str, *args: Any) -> None:
        self._target.info(message, *args)

    def warn(self, message: str, *args: Any) -> None:
        # SDK 协议是 warn（logging.Logger 是 warning）
        self._target.warning(message, *args)

    def error(self, message: str, *args: Any) -> None:
        self._target.error(message, *args)


class _SingleInstanceLock:
    """单实例文件锁（fcntl.flock 非阻塞独占；同机第二实例 acquire 失败）.

    flock 锁随文件描述符生命周期释放（进程退出自动释放，无陈旧锁问题）；
    release 幂等。
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        """尝试独占（非阻塞）。成功 True；已被占用 False（记告警，含持有信息）."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fh = open(self._path, "a+", encoding="utf-8")  # noqa: SIM115 — 锁文件需长期持有 fd（flock 生命周期=fd 生命周期，with 即释放）
        except OSError as exc:
            logger.warning("企微桥单实例锁文件不可写（fail-open 放行单实例检查）: %s", exc)
            return True
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            logger.warning(
                "企微桥单实例锁被占用（%s）：同机器人同时只能一个长连接，"
                "新连接会踢掉旧连接；本实例拒绝启动以避免互踢",
                self._path,
            )
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()}\n")
        fh.flush()
        self._fh = fh
        return True

    def release(self) -> None:
        """释放（幂等；未持有直接返回）."""
        if self._fh is None:
            return
        with suppress(OSError):  # 解锁失败 fail-open（fd 关闭即释放）
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        with suppress(OSError):
            self._fh.close()
        self._fh = None


def _default_client_factory(config: WeComConfig) -> Any:
    """真实 aibot.WSClient 构造（测试注入 FakeClient 替换，零真实连接）."""
    from aibot import WSClient, WSClientOptions

    options = WSClientOptions(
        bot_id=config.bot_id,
        secret=config.secret,
        logger=_SdkLoggerAdapter(logging.getLogger("aibot")),
    )
    return WSClient(options)


class WeComBridge:
    """企微 WS 桥：SDK 连接生命周期 + 有界队列 + 单 worker 线程 + 单实例锁."""

    def __init__(
        self,
        config: WeComConfig,
        handler: Any | None = None,
        *,
        client_factory: Callable[[WeComConfig], Any] | None = None,
        lock_path: str | None = None,
    ) -> None:
        self._config = config
        self._handler = handler
        self._client_factory = client_factory or _default_client_factory
        self._lock = _SingleInstanceLock(
            lock_path or f"{os.environ.get('DATA_DIR', './data')}/{_LOCK_FILENAME}"
        )
        self._client: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._msg_queue: queue.Queue[dict | None] = queue.Queue(maxsize=_MAX_MSG_QUEUE)
        self._stop = False
        self._running = False
        self._ws_state = "disconnected"

    # ── 生命周期 ──
    @property
    def state(self) -> str:
        return self._ws_state

    @property
    def is_running(self) -> bool:
        return self._running

    def attach_handler(self, handler: Any) -> None:
        """装配消息处理器（build_bridge 顺序：bridge 先建 → handler 后接）."""
        self._handler = handler

    def start(self) -> bool:
        """启动桥：单实例锁 → SDK loop 线程 → connect → worker 线程."""
        if self._running:
            logger.warning("企微桥重复启动请求（已运行），忽略")
            return True
        if not self._config.has_credentials:
            logger.warning("企微桥未启用（WECHAT_BOT_ID/WECHAT_BOT_SECRET 未配置）")
            return False
        if not self._lock.acquire():
            return False  # 单实例锁被占用：拒绝启动（防互踢，设计文档 §6 高风险项）
        self._client = self._client_factory(self._config)
        self._register_callbacks(self._client)
        self._start_loop_thread()
        try:
            fut = asyncio.run_coroutine_threadsafe(self._client.connect(), self._loop)
            fut.result(timeout=_CONNECT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — 连接失败如实清理退出
            logger.error("企微桥连接失败: %s", exc)
            self._shutdown_loop()
            self._lock.release()
            return False
        self._ws_state = "connected"
        self._stop = False
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="wecom-ws-worker", daemon=True
        )
        self._worker_thread.start()
        self._running = True
        logger.info("企微桥已启动（bot_id=%s…）", self._config.bot_id[:6])
        return True

    def stop(self) -> None:
        """优雅退出：worker 哨兵+join → SDK 断开 → 停 loop 线程 → 释放锁（幂等）."""
        if not self._running and self._loop is None:
            return
        self._stop = True
        # 1) worker 线程：哨兵 + drain（队列中剩余消息尽力处理完）
        if self._worker_thread is not None:
            with suppress(queue.Full):  # 队列满：直接放弃哨兵，join 超时兜底
                self._msg_queue.put_nowait(None)
            self._worker_thread.join(timeout=_WORKER_JOIN_TIMEOUT_S)
            if self._worker_thread.is_alive():
                logger.warning("企微桥优雅退出: worker join 超时（线程仍在处理）")
            self._worker_thread = None
        # 2) SDK 断开 + loop 线程停止（无残留线程）
        self._shutdown_loop()
        self._lock.release()
        self._running = False
        self._ws_state = "disconnected"
        logger.info("企微桥已停止")

    # ── SDK 回调（运行在 SDK loop 线程：只 marshal + 入队，立即返回）──
    def _register_callbacks(self, client: Any) -> None:
        """注册 SDK 原始事件（message/event）与连接层事件回调."""
        client.on("message", self._on_sdk_message)
        client.on("event", self._on_sdk_event)
        client.on("disconnected", self._on_sdk_disconnected)
        client.on("error", self._on_sdk_error)

    def _on_sdk_message(self, frame: dict) -> None:
        """SDK "message" 回调（loop 线程内同步执行）：仅入队，零解析零推理."""
        try:
            self._msg_queue.put_nowait(frame)
        except queue.Full:
            req_id = (frame.get("headers") or {}).get("req_id", "")
            logger.warning(
                "企微消息队列已满（maxsize=%d），丢弃事件: req_id=%s（fail-open，不阻塞 loop）",
                self._msg_queue.maxsize,
                req_id,
            )

    def _on_sdk_event(self, frame: dict) -> None:
        """SDK "event" 回调（loop 线程内）：事件不入消息队列，仅断线事件告警."""
        try:
            if is_disconnected_event(frame):
                # 官方协议：被踢下线时推送（SDK EventType 枚举无此项——仓库侧补齐）
                logger.error(
                    "企微桥收到 disconnected_event（连接被服务端踢掉/另一实例已订阅）"
                )
            else:
                logger.debug("企微事件回调: eventtype=%s", parse_event_frame(frame))
        except Exception:  # noqa: BLE001 — 回调异常不向 SDK 冒泡
            logger.exception("企微事件回调处理异常")

    def _on_sdk_disconnected(self, reason: Any) -> None:
        """SDK "disconnected" 客户端事件（连接层断开；非人为退出时 SDK 自动重连）."""
        self._ws_state = "reconnecting" if not self._stop else "disconnected"
        logger.warning("企微 WS 连接断开: %s（人为退出=%s）", reason, self._stop)

    def _on_sdk_error(self, error: Any) -> None:
        """SDK "error" 客户端事件（鉴权失败等）如实记错误."""
        logger.error("企微桥 SDK 错误: %s", error)

    # ── worker 线程（推理与回复都在此线程，不碰 SDK loop）──
    def _worker_loop(self) -> None:
        """单 worker：get → dispatcher 解包 → handler.handle（engine.run 在此执行）."""
        while True:
            item = self._msg_queue.get()
            if item is None:
                break  # 哨兵：优雅退出
            try:
                msg = parse_message_frame(item)
                if msg is None:
                    continue  # compat_info 非空/结构无效：dispatcher 已记日志跳过
                if self._handler is not None:
                    self._handler.handle(msg)
            except Exception:  # noqa: BLE001 — 单条消息异常不终止 worker
                logger.exception("企微 worker 处理消息异常（req_id=%s）", (item.get("headers") or {}).get("req_id", ""))

    # ── 回复（WeComReplyFn 签名；worker 线程调用，投递回 SDK loop 执行）──
    def send_text(self, req_id: str, receive_id: str, text: str, receive_id_type: str) -> None:
        """回复文本（markdown）：绑定 req_id 透传同一次回调（企微协议硬要求）.

        client.reply 仅读取 frame["headers"]["req_id"]（SDK client.py:125-127），
        故按 req_id 重建最小 frame 即可绑定同一次回调；receive_id/receive_id_type
        已由消息路由保证（回复走回调通道，无需再指定目标）。
        从 worker 线程经 run_coroutine_threadsafe 投递到 SDK loop 执行，
        不在 SDK 回调内同步等待（防阻塞 loop——3003 断线成因）。
        """
        client = self._client
        loop = self._loop
        if client is None or loop is None or not loop.is_running():
            logger.warning("企微桥未连接，回复丢弃（req_id=%s）: %s", req_id, text[:100])
            return
        frame = {"headers": {"req_id": req_id}}
        body = {"msgtype": "markdown", "markdown": {"content": text}}
        try:
            fut = asyncio.run_coroutine_threadsafe(client.reply(frame, body), loop)
            fut.result(timeout=_REPLY_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — 回复失败如实记日志（不重试不阻塞 worker）
            logger.error("企微回复发送失败（req_id=%s）: %s", req_id, exc)

    # ── SDK loop 线程管理 ──
    def _start_loop_thread(self) -> None:
        """SDK asyncio 事件循环独立线程（设计文档 §4.4）."""
        self._loop = asyncio.new_event_loop()

        def _run() -> None:
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_run, name="wecom-ws-loop", daemon=True)
        self._loop_thread.start()

    async def _graceful_disconnect(self) -> None:
        """在 SDK loop 内优雅断开：置 manual_close + 等待连接关闭."""
        client = self._client
        if client is None:
            return
        client.disconnect()  # 同步方法：内部 ensure_future 调度异步关闭
        for _ in range(int(_DISCONNECT_TIMEOUT_S * 10)):
            if not client.is_connected:
                return
            await asyncio.sleep(0.1)

    def _shutdown_loop(self) -> None:
        """停 SDK loop 线程（先在 loop 内断开连接，再 stop+join+close）."""
        loop, thread = self._loop, self._loop_thread
        if loop is not None and loop.is_running() and thread is not None and thread.is_alive():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._graceful_disconnect(), loop)
                fut.result(timeout=_DISCONNECT_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 — 断开失败继续停 loop
                logger.warning("企微桥断开连接异常（继续停 loop）: %s", exc)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=_DISCONNECT_TIMEOUT_S)
            if thread.is_alive():
                logger.warning("企微桥 loop 线程 join 超时（daemon 兜底）")
        if loop is not None:
            loop.close()
        self._loop = None
        self._loop_thread = None

    # ── 便捷 ──
    def handle_frame_direct(self, frame: dict) -> WeComMessage | None:
        """测试/调试便捷入口：单帧解包（不经队列；生产路径走 worker）."""
        return parse_message_frame(frame)
