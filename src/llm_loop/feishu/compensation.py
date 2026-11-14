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
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from llm_loop.runtime.feishu_compensation_reader import (
    CRASH,
    INTERRUPT_CAUSES,
    REPLY_TYPES,
    legacy_interrupted_path,
    read_compensation_records,
)
from llm_loop.runtime.feishu_compensation_reader import (
    DRAIN_TIMEOUT as DRAIN_TIMEOUT,
)
from llm_loop.runtime.feishu_compensation_reader import (
    PROCESS_TIMEOUT as PROCESS_TIMEOUT,
)
from llm_loop.runtime.feishu_compensation_reader import (
    QUEUE_FULL as QUEUE_FULL,
)
from llm_loop.runtime.feishu_compensation_reader import (
    WATCHDOG_EXIT as WATCHDOG_EXIT,
)
from llm_loop.runtime.feishu_compensation_reader import (
    compensation_path as compensation_path,
)
from llm_loop.runtime.resolver import business_config_snapshot
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

_COMPENSATION_CONFIG = business_config_snapshot("feishu_compensation")

# 结构化中断原因五类与路径解析事实（FTR-DFX-08）的单一事实源已下沉 kernel 侧
# llm_loop.runtime.feishu_compensation_reader（M2-2 runtime→feishu 架构边偿还：
# service_control 不得函数内 import 本 capability 模块）；此处 re-export 保持
# 既有公共 API（bridge/tests 引用）不变。InterruptCause 类型别名与 kernel 侧
# 校验枚举语义一致。
InterruptCause = Literal[
    "watchdog_exit", "queue_full", "drain_timeout", "process_timeout", "crash"
]

_REPLY_TYPES = REPLY_TYPES

_NOTIFY_TIMEOUT_S = float(_COMPENSATION_CONFIG.get("FEISHU_INTERRUPT_NOTIFY_TIMEOUT_S", "1"))


def read_only_compensation_records(
    runtime_root: str | Path | None = None,
) -> list[InterruptionCompensationRecord] | None:
    """纯只读补偿记录读取（M2-2；供 service_control 空闲判定，零写副作用）.

    解析与校验事实在 kernel 侧 ``llm_loop.runtime.feishu_compensation_reader``
    （M2-2 runtime→feishu 架构边偿还）；本层把 immutable DTO 包装为
    InterruptionCompensationRecord，公共 API 与行为保持不变：绝不调用
    ``_ensure_migrated()``（迁移会改写 JSONL 并删除 legacy 单文件——只读判定
    不得有写副作用，spec M2-2 安全边界 4）；单行损坏整体失败返回 None
    （fail-closed：无法排除目标 msg_id 恰在损坏行中，“跳过”会把证据不足
    误判为无补偿）。

    校验等价性说明（R9 审查修订）：kernel reader 已同序复刻 dataclass
    ``__post_init__`` 的三项 raise 校验（receive_id 非空 / reply_type 枚举 /
    cause 枚举）并前置拦截空 interrupted_at（历史注释提到的 msg_id↔cause
    组合校验在 dataclass 中实际不存在，勿臆造）；包装构造仍置于
    try/except 内——与下沉前原实现结构一致，dataclass 未来新增校验时
    依旧 fail-closed None，而不是向 service_control 逃逸未捕获异常。

    Args:
        runtime_root: 桥运行根目录（相对路径解析基准，与 bridge cwd=runtime_root
            语义一致）；绝对路径配置不受影响；相对路径且 runtime_root=None → None。

    Returns:
        解析成功：记录列表（JSONL 与 legacy 均缺失/空 = []，不创建任何文件）；
        读取/解析失败：None（调用方必须按证据不足处理，不得视作“无补偿”）。
    """
    data = read_compensation_records(runtime_root)
    if data is None:
        return None
    try:
        return [
            InterruptionCompensationRecord(
                receive_id=item.receive_id,
                reply_type=item.reply_type,
                interrupt_cause=item.interrupt_cause,
                interrupted_at=item.interrupted_at,
                context_ref=item.context_ref,
                msg_id=item.msg_id,
            )
            for item in data
        ]
    except (OSError, ValueError) as exc:
        # 与下沉前原实现等价的构造期 fail-closed（防 dataclass 校验演进）
        logger.warning("补偿记录包装构造失败（fail-closed，按证据不足处理）: %s", exc)
        return None


def _now_iso() -> str:
    return system_local_now().isoformat(timespec="seconds")


@dataclass(kw_only=True)
class InterruptionCompensationRecord:
    """中断补偿记录（对齐 spec 6.1；六字段，后两字段可空如实标注）."""

    receive_id: str          # 补偿回复目标会话（chat_id / open_id）
    reply_type: str          # "chat_id" | "open_id"
    interrupt_cause: str     # 五类结构化原因（FTR-DFX-08）
    interrupted_at: str = ""  # 中断落盘时点（ISo；空则自动填当前）
    context_ref: str = ""    # "session_id" 或 "goal_id:<session_id>"；空标注待确认
    msg_id: str = ""         # 触发中断原始消息 id（可能为空）

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
        self._legacy_path = Path(legacy_path) if legacy_path is not None else Path(legacy_interrupted_path())
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
            logger.warning(
                "中断补偿已落盘: cause=%s → %s", rec.interrupt_cause, rec.receive_id
            )
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
                        logger.warning("补偿记录字段非法已隔离（%s:%d）: %s", self._path, line_no, exc)
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
