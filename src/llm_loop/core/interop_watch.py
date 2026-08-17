"""协调通道 inbox 主动感知（EVO-20260817-6efeb7a0，2026-08-17）.

背景: RULE-AI-14 自动注入仅在 run 构建消息时扫描一次 inbox（interop.py）——
run 之间到达的 DSH 消息/后台通知静默躺 pending，无人感知（用户 2026-08-17
反馈"查收"轮实证: 028 与 2 条 job 通知在 run 构建后写入，未注入）。本模块
提供常驻 daemon 线程主动监视:

- A（必做）: 轮询 LFL_DATA_DIR/interop/lfl_to_dsh/pending（与 interop.py 同基准），
  检测到新 pending 消息 → on_notify(files) 回调（装配方注入: 审计事件/日志/推送）。
- B（可选, INBOX_WAKEUP=1 默认关）: 对 topic=coordinate 的新消息额外触发
  wakeup_fn(files)（轻量 run 处理——run 的注入机制自动带上全部 pending 消息，
  无需解析内容）；job/notify 类永不触发（防后台任务风暴）；限频
  wakeup_min_interval_s（默认 300s）。

设计约束（RULE-AI-14）: 监视器只做"感知/提醒"，不写 pending、不改协议、
不额外触发 run（除非 INBOX_WAKEUP 显式开启且为 coordinate 消息）。
幂等: 已提示文件名集合内存去重（进程内一次；重启后重新提示一次，可接受）。
fail-open: 任何异常仅日志，不阻断主流程/桥。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

_INTEROP_INBOX_REL = Path("interop") / "lfl_to_dsh" / "pending"
_POLL_S = float(os.environ.get("INBOX_WATCH_POLL_S", "10"))
_WAKEUP_ENABLED = os.environ.get("INBOX_WAKEUP", "0").strip().lower() in {
    "1", "true", "yes", "on",
}
_WAKEUP_MIN_INTERVAL_S = float(os.environ.get("INBOX_WAKEUP_MIN_INTERVAL_S", "300"))


class InboxWatcher:
    """协调通道 inbox 监视线程（start/stop 生命周期，装配进 factory）.

    回调（duck typing，可空）:
    - on_notify(files: Sequence[str]): 新 pending 消息通知（必做路径，默认写审计事件）
    - wakeup_fn(files: Sequence[str]): INBOX_WAKEUP=1 且含 coordinate 消息时调用（限频）
    """

    def __init__(
        self,
        *,
        inbox_dir: str | Path | None = None,
        poll_s: float = _POLL_S,
        on_notify: Callable[[Sequence[str]], None] | None = None,
        wakeup_fn: Callable[[Sequence[str]], None] | None = None,
        wakeup_enabled: bool | None = None,
        wakeup_min_interval_s: float = _WAKEUP_MIN_INTERVAL_S,
    ) -> None:
        self._inbox_dir = Path(inbox_dir) if inbox_dir else (
            Path(os.environ.get("LFL_DATA_DIR", "data")) / _INTEROP_INBOX_REL
        )
        self._poll_s = poll_s
        self._on_notify = on_notify
        self._wakeup_fn = wakeup_fn
        self._wakeup_enabled = (
            _WAKEUP_ENABLED if wakeup_enabled is None else wakeup_enabled
        )
        self._wakeup_min_interval = wakeup_min_interval_s
        self._seen: set[str] = set()  # 已提示文件名（去重）
        self._baselined = False  # 首轮只建基线（启动不刷屏，对齐 cross_sync）
        self._last_wakeup = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── 生命周期 ──
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="interop-inbox-watch", daemon=True
        )
        self._thread.start()
        logger.info("协调 inbox 监视已启动（%.1fs，wakeup=%s）", self._poll_s, self._wakeup_enabled)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ── 核心 ──
    def poll_once(self) -> None:
        """扫描一次 inbox；新 pending 消息 → 通知（+可选 wakeup）.

        幂等: 已通知过的文件名跳过；文件被归档（移走）后重名新文件
        （同秒序号递增）会正常作为新消息通知。fail-open: 读失败仅日志。
        """
        try:
            files = sorted(self._inbox_dir.glob("*.json"))
        except OSError as exc:  # noqa: BLE001 — 目录缺失/权限 → fail-open
            logger.debug("协调 inbox 扫描失败（fail-open）: %s", exc)
            return
        if not self._baselined:
            # 首轮建基线: 存量不触发 wakeup（防启动风暴），但通知一次——
            # 2026-08-17 修复: 此前存量静默吞入基线，重启后启动前到达的
            # 消息（如 031）永不感知。低频协调场景下通知一次成本可忽略。
            if files and self._on_notify is not None:
                try:
                    self._on_notify([f.name for f in files])
                except Exception:  # noqa: BLE001 — 通知失败 fail-open
                    logger.warning("协调 inbox 存量通知失败（fail-open）", exc_info=True)
            self._seen = {f.name for f in files}
            self._baselined = True
            return
        new_files = [f for f in files if f.name not in self._seen]
        if not new_files:
            return
        self._seen.update(f.name for f in new_files)
        names = [f.name for f in new_files]
        logger.info("协调 inbox 新消息 %d 条: %s", len(names), ", ".join(names))
        # A: 必做通知（审计/日志/推送）
        if self._on_notify is not None:
            try:
                self._on_notify(names)
            except Exception:  # noqa: BLE001 — 通知失败 fail-open
                logger.warning("协调 inbox on_notify 失败（fail-open）", exc_info=True)
        # B: 可选 wakeup（仅 coordinate，限频）
        if self._wakeup_enabled and self._wakeup_fn is not None:
            now = time.monotonic()
            if now - self._last_wakeup >= self._wakeup_min_interval:
                topics = self._topics_of(new_files)
                if "coordinate" in topics:
                    self._last_wakeup = now
                    try:
                        self._wakeup_fn(names)
                    except Exception:  # noqa: BLE001 — wakeup 失败 fail-open
                        logger.warning("协调 inbox wakeup 失败（fail-open）", exc_info=True)

    @staticmethod
    def _topics_of(files: Sequence[Path]) -> set[str]:
        """读取各文件 topic（读失败跳过；status!=pending 不计入）."""
        topics: set[str] = set()
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if d.get("status") != "pending":
                continue
            topics.add(str(d.get("topic", "")))
        return topics

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_s):
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 — 轮询异常 fail-open（线程自愈）
                logger.debug("协调 inbox 轮询异常（fail-open）: %s", exc_info=True)
