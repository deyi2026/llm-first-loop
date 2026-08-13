"""恢复通道编排（design §2.3.2.1/§2.3.2.2 / spec §5.1/§5.3）.

RecoveryChannel：
- persist_with_recovery：重试→备份→回执（供 engine 三个 fail-open 写失败点接入）。
- recover：从备份恢复到正式位置 + 冲突检测 + action_trace 留痕（供 recover_from_backup 工具调用）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from llm_loop.recovery.backup import BackupArchive, BackupStore
from llm_loop.recovery.retry import retry_write

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReceipt:
    """persist_with_recovery 回执.

    - status: "retried_ok" | "backed_up" | "backup_failed"
    - retries: 重试次数（含首次）
    - elapsed_s: 重试耗时
    - backup_id: 备份标识（status="backed_up" 时有值）
    - error: 错误信息（status="backup_failed" 时有值）
    """

    status: str
    retries: int
    elapsed_s: float
    backup_id: str | None = None
    error: str | None = None


@dataclass
class RecoveryResult:
    """recover 回执.

    - status: "recovered" | "conflict" | "not_found" | "corrupt" | "failed"
    - affected: 受影响对象标识（恢复成功时）
    - error: 错误信息
    """

    status: str
    affected: str | None = None
    error: str | None = None


class RecoveryChannel:
    """恢复通道编排组件.

    persist_with_recovery：编排重试→备份→回执。
    recover：从备份恢复到正式位置 + 冲突检测 + action_trace 留痕。
    """

    def __init__(
        self,
        *,
        backup_store: BackupStore,
        action_trace_fn: Callable[[str, str], None] | None = None,
    ) -> None:
        self._backup_store = backup_store
        self._action_trace_fn = action_trace_fn

    def _trace(self, action_type: str, detail: str) -> None:
        if self._action_trace_fn is not None:
            try:
                self._action_trace_fn(action_type, detail)
            except Exception:  # noqa: BLE001 — 留痕失败不中断
                logger.warning("action_trace 留痕失败（fail-open）", exc_info=True)

    def persist_with_recovery(
        self,
        *,
        target_type: str,
        source_id: str,
        write_fn: Callable[[], None],
        payload: bytes | str,
        trigger_point: str = "",
    ) -> RecoveryReceipt:
        """编排重试→备份→回执（design §2.3.2.1）.

        重试成功返回 retried_ok（不备份）；
        重试耗尽转备份成功返回 backed_up；
        备份失败返回 backup_failed（不二次抛穿）。
        """
        payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else payload

        result = retry_write(write_fn)
        if result.success:
            return RecoveryReceipt(status="retried_ok", retries=result.attempts, elapsed_s=result.elapsed_s)

        # 重试耗尽，转备份
        archive = BackupArchive(
            source_id=source_id,
            backup_at=datetime.now().astimezone().isoformat(),
            target_type=target_type,
            payload=payload_str,
            retry_count=result.attempts,
            trigger_point=trigger_point,
            recovered=False,
        )
        try:
            backup_id = self._backup_store.save_archive(archive)
            self._trace(
                "recovery.backup",
                f"backup_id={backup_id} source_id={source_id} target_type={target_type} "
                f"trigger={trigger_point} retries={result.attempts}",
            )
            return RecoveryReceipt(
                status="backed_up",
                retries=result.attempts,
                elapsed_s=result.elapsed_s,
                backup_id=backup_id,
            )
        except Exception as exc:  # noqa: BLE001 — 备份失败不二次抛穿
            error = f"{type(exc).__name__}: {exc}"
            self._trace(
                "recovery.backup_failed",
                f"source_id={source_id} target_type={target_type} error={error}",
            )
            return RecoveryReceipt(
                status="backup_failed",
                retries=result.attempts,
                elapsed_s=result.elapsed_s,
                error=error,
            )

    def recover(
        self,
        *,
        backup_id: str,
        target_write_fn: Callable[[bytes | str], None],
        target_exists_fn: Callable[[], bool],
        on_conflict: str = "abort",
    ) -> RecoveryResult:
        """从备份恢复数据到正式位置（design §2.3.2.2）.

        冲突时默认 abort（不覆盖），AI 可显式 overwrite。
        恢复成功标记 recovered=True + action_trace 留痕。
        恢复写入失败保留备份不删除。
        """
        archive = self._backup_store.get_archive(backup_id)
        if archive is None:
            return RecoveryResult(status="not_found", error=f"备份不存在: {backup_id}")

        # 检查备份是否损坏（get_archive 已处理 JSON 解析，此处 payload 为空视为损坏）
        if not archive.payload:
            return RecoveryResult(status="corrupt", error=f"备份内容为空: {backup_id}")

        # 冲突检测
        if target_exists_fn() and on_conflict != "overwrite":
            return RecoveryResult(status="conflict", error="正式位置已有数据，未覆盖")

        # 恢复写入
        try:
            target_write_fn(archive.payload)
        except Exception as exc:  # noqa: BLE001 — 恢复写入失败保留备份
            error = f"{type(exc).__name__}: {exc}"
            self._trace("recovery.recover_failed", f"backup_id={backup_id} error={error}")
            return RecoveryResult(status="failed", error=error)

        # 标记已恢复 + 留痕
        self._backup_store.mark_recovered(backup_id)
        affected = f"{archive.source_id} ({archive.target_type})"
        self._trace(
            "recovery.recovered",
            f"backup_id={backup_id} affected={affected} on_conflict={on_conflict}",
        )
        return RecoveryResult(status="recovered", affected=affected)
