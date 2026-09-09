"""飞书桥中断补偿底座（COMP）.

面向终端用户的长时任务中断可感知/可补偿：任何非用户主动中断都必须落
补偿记录（JSONL 多记录，append-only）或主动提示，禁止「静默消失」。

- ``InterruptionCompensationRecord``：六字段补偿记录（interrupt_cause 五类收紧）。
- ``CompensationStore``：JSONL append 原子追加 + 逐行读取（单行损坏隔离）+ 幂等剔除 + 旧单文件迁移。
- ``InterruptionNotifier``：三要素提示（处理未完成 + 原因类别 + 恢复动作），
  单次 1s 上限尽力发送，失败落补偿兜底（FTR-DFX-02）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# 结构化中断原因五类（FTR-DFX-08：禁止脆弱文本匹配分类）
WATCHDOG_EXIT = "watchdog_exit"
QUEUE_FULL = "queue_full"
DRAIN_TIMEOUT = "drain_timeout"
PROCESS_TIMEOUT = "process_timeout"
CRASH = "crash"
InterruptCause = Literal["watchdog_exit", "queue_full", "drain_timeout", "process_timeout", "crash"]
INTERRUPT_CAUSES: tuple[str, ...] = (
    WATCHDOG_EXIT,
    QUEUE_FULL,
    DRAIN_TIMEOUT,
    PROCESS_TIMEOUT,
    CRASH,
)

_REPLY_TYPES = frozenset({"chat_id", "open_id"})

_COMPENSATION_PATH_ENV = "FEISHU_COMPENSATION_PATH"
_DEFAULT_COMPENSATION_PATH = "data/feishu_compensation.jsonl"
_LEGACY_INTERRUPTED_PATH_ENV = "FEISHU_INTERRUPTED_PATH"
_DEFAULT_LEGACY_INTERRUPTED_PATH = "data/feishu_interrupted.json"

_NOTIFY_TIMEOUT_S = float(os.environ.get("FEISHU_INTERRUPT_NOTIFY_TIMEOUT_S", "1"))


def compensation_path() -> str:
    """补偿记录 JSONL 路径（默认 data/feishu_compensation.jsonl，可经 env 配置）."""
    return os.environ.get(_COMPENSATION_PATH_ENV, "") or _DEFAULT_COMPENSATION_PATH


def legacy_interrupted_path() -> str:
    """旧单文件补偿路径（默认 data/feishu_interrupted.json，启动迁移数据源）."""
    return os.environ.get(_LEGACY_INTERRUPTED_PATH_ENV, "") or _DEFAULT_LEGACY_INTERRUPTED_PATH


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass(kw_only=True)
class InterruptionCompensationRecord:
    """中断补偿记录（对齐 spec 6.1；六字段，后两字段可空如实标注）."""

    receive_id: str  # 补偿回复目标会话（chat_id / open_id）
    reply_type: str  # "chat_id" | "open_id"
    interrupt_cause: str  # 五类结构化原因（FTR-DFX-08）
    interrupted_at: str = ""  # 中断落盘时点（ISo；空则自动填当前）
    context_ref: str = ""  # "session_id" 或 "goal_id:<session_id>"；空标注待确认
    msg_id: str = ""  # 触发中断原始消息 id（可能为空）

    def __post_init__(self) -> None:
        if not self.receive_id:
            raise ValueError("receive_id 必填非空（补偿回复目标会话）")
        if self.reply_type not in _REPLY_TYPES:
            raise ValueError(f"reply_type 非法: {self.reply_type!r}（仅 chat_id/open_id）")
        if self.interrupt_cause not in INTERRUPT_CAUSES:
            raise ValueError(f"interrupt_cause 非法: {self.interrupt_cause!r}")
        if not self.interrupted_at:
            self.interrupted_at = _now_iso()

    def to_dict(self) -> dict:
        return asdict(self)

    def key(self) -> str:
        """幂等键：receive_id + msg_id（msg_id 空时用原因+时点兜底）."""
        if self.msg_id:
            return f"{self.receive_id}:{self.msg_id}"
        return f"{self.receive_id}:{self.interrupt_cause}:{self.interrupted_at}"


class CompensationStore:
    """补偿记录 JSONL 存储（append-only + 单行损坏隔离 + 幂等剔除 + 旧文件迁移）."""

    def __init__(self, path: str | Path, *, legacy_path: str | Path | None = None) -> None:
        self._path = Path(path)
        self._legacy_path = (
            Path(legacy_path) if legacy_path is not None else Path(legacy_interrupted_path())
        )
        self._lock = threading.Lock()
        self._migrated = False

    @property
    def path(self) -> Path:
        return self._path

    def append(self, rec: InterruptionCompensationRecord) -> Path:
        """追加一条补偿记录（原子 append；OSError fail-open 仅告警不阻断）."""
        self._ensure_migrated()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            logger.warning("中断补偿已落盘: cause=%s → %s", rec.interrupt_cause, rec.receive_id)
        except OSError as exc:
            logger.warning("中断补偿落盘失败（fail-open，补偿可能丢失）: %s", exc)
        return self._path

    def read_all(self) -> list[InterruptionCompensationRecord]:
        """读全量（逐行解析；单行 JSONDecodeError 跳过隔离并告警，不阻断其余）."""
        self._ensure_migrated()
        out: list[InterruptionCompensationRecord] = []
        if not self._path.exists():
            return out
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line_no, raw in enumerate(f, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "补偿记录单行损坏已隔离（%s:%d），不阻断其余记录",
                            self._path,
                            line_no,
                        )
                        continue
                    try:
                        out.append(
                            InterruptionCompensationRecord(
                                receive_id=str(data.get("receive_id", "")),
                                reply_type=str(data.get("reply_type", "chat_id")),
                                interrupt_cause=str(data.get("interrupt_cause", CRASH)),
                                interrupted_at=str(data.get("interrupted_at", "")),
                                context_ref=str(data.get("context_ref", "")),
                                msg_id=str(data.get("msg_id", "")),
                            )
                        )
                    except ValueError as exc:
                        logger.warning(
                            "补偿记录字段非法已隔离（%s:%d）: %s", self._path, line_no, exc
                        )
                        continue
        except OSError as exc:
            logger.warning("补偿记录读取失败（fail-open）: %s", exc)
        return out

    def remove_entry(self, key: str) -> None:
        """按幂等键 rewrite 剔除已成功补偿的记录（幂等；OSError fail-open）."""
        remaining: list[InterruptionCompensationRecord] = [
            rec for rec in self.read_all() if rec.key() != key
        ]
        if len(remaining) == len(self.read_all()):
            return  # 无命中，零重写
        self._rewrite(remaining)

    def _rewrite(self, records: list[InterruptionCompensationRecord]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("补偿记录剔除写入失败（fail-open）: %s", exc)

    def _ensure_migrated(self) -> None:
        if self._migrated:
            return
        with self._lock:
            if self._migrated:
                return
            self._migrated = True
            self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        """旧单文件 feishu_interrupted.json → 迁移为一条补偿记录后删除（无损）."""
        p = self._legacy_path
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            rec = InterruptionCompensationRecord(
                receive_id=str(data.get("reply_id", "")),
                reply_type=str(data.get("reply_type", "chat_id") or "chat_id"),
                interrupt_cause=CRASH,
                interrupted_at=str(data.get("interrupted_at", "")),
                msg_id=str(data.get("msg_id", "")),
            )
            self._append_raw(rec)
            p.unlink(missing_ok=True)
            logger.warning("旧单文件补偿记录已迁移至 JSONL 并删除旧文件: %s", p)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("旧单文件补偿记录迁移失败（fail-open，保留旧文件）: %s", exc)

    def _append_raw(self, rec: InterruptionCompensationRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")


class InterruptionNotifier:
    """中断三要素提示发送器（1s 上限尽力 + 失败落补偿兜底）."""

    def __init__(
        self,
        send_fn: Callable[[str, str, str], bool] | None,
        store: CompensationStore | None = None,
        *,
        timeout_s: float = _NOTIFY_TIMEOUT_S,
    ) -> None:
        self._send_fn = send_fn
        self._store = store
        self._timeout_s = timeout_s

    def notify(
        self,
        receive_id: str,
        reply_type: str,
        cause: str,
        text: str,
        *,
        fallback: bool = True,
    ) -> bool:
        """尽力发送三要素中断提示；发送失败/超时落补偿记录兜底（至少一次可感知）.

        Args:
            fallback: 失败时是否落补偿兜底；调用方已先行落盘完整补偿记录时传
                False，避免双重落盘（bridge._emit_interruption 模式）。
        Returns:
            True=即时送达；False=失败（fallback=True 时已落补偿兜底）。
        """
        if not receive_id:
            return False
        if self._send_fn is None:
            self._fallback(receive_id, reply_type, cause)
            return False
        result: list[bool | BaseException] = [False]

        def _send() -> None:
            try:
                result[0] = bool(self._send_fn(receive_id, text, reply_type))  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001 — 发送异常按失败兜底
                result[0] = exc

        worker = threading.Thread(target=_send, name="feishu-interrupt-notify", daemon=True)
        worker.start()
        worker.join(self._timeout_s)
        if worker.is_alive() or result[0] is not True:
            # 超时或发送失败 → 落补偿兜底（FTR-DFX-02）
            if worker.is_alive():
                logger.warning("中断提示发送超时（%.1fs 上限）", self._timeout_s)
            else:
                logger.warning("中断提示发送失败: %s", result[0])
            if fallback:
                self._fallback(receive_id, reply_type, cause)
            return False
        logger.info("中断提示已发送: cause=%s → %s", cause, receive_id)
        return True

    def _fallback(self, receive_id: str, reply_type: str, cause: str) -> None:
        if self._store is None:
            return  # 未装配存储 → 仅发送不兜底（降级）
        if cause not in INTERRUPT_CAUSES:
            cause = CRASH
        try:
            self._store.append(
                InterruptionCompensationRecord(
                    receive_id=receive_id,
                    reply_type=reply_type,
                    interrupt_cause=cause,
                )
            )
        except (ValueError, OSError) as exc:
            logger.warning("中断补偿兜底落盘失败（fail-open）: %s", exc)
