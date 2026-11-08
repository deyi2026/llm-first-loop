"""监督通道票据（DESIGN-20261108 §2.2/§2.4）。

票据是"有人在本机 TTY 逐次确认"的物证：

- 绑定 ``task_id + params_digest + kind + node_id``：参数一改就失效；
- 一次性：``consume`` 用 ``os.replace`` 原子认领，第二个消费者必然找不到源文件；
- TTL：签发时取配置的监督 TTL（``--supervision-ttl``，缺省 300s），过期不可用；
- 属主：数据目录必须属于当前 uid，避免别人替你批准。

HTTP 面没有签发票据的入口（D3）；票据只能由本机 CLI 产生。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import iso, now_local, parse_ts

TICKET_DIRNAME = "supervision"
_FIELDS = (
    "task_id",
    "node_id",
    "kind",
    "params_digest",
    "issued_by",
    "issued_at",
    "expires_at",
)


@dataclass(frozen=True)
class SupervisionTicket:
    task_id: str
    node_id: str
    kind: str
    params_digest: str
    issued_by: str
    issued_at: str
    expires_at: str

    def to_dict(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in _FIELDS}

    @classmethod
    def from_dict(cls, raw: Any) -> SupervisionTicket:
        if not isinstance(raw, dict):
            raise PeerError("supervision_ticket_missing", "票据不是对象")
        values: dict[str, str] = {}
        for field in _FIELDS:
            value = raw.get(field)
            if not isinstance(value, str) or not value.strip():
                raise PeerError("supervision_ticket_missing", f"票据缺少字段: {field}")
            values[field] = value.strip()
        return cls(**values)


class OperatorChannel:
    """``<peer-data>/supervision/<task_id>.json`` 的签发、校验与一次性消费。"""

    def __init__(
        self, root: Path | str, *, clock: Callable[[], datetime] = now_local
    ) -> None:
        self._root = Path(root) / TICKET_DIRNAME
        self._clock = clock

    @property
    def root(self) -> Path:
        return self._root

    def available(self) -> bool:
        """目录可写且属主是当前用户，才算监督通道在线（D5 条件③）。"""
        try:
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
            # mkdir 的 mode 受 umask 影响；票据目录显式收紧到 0o700。
            os.chmod(self._root, 0o700)
            getuid = getattr(os, "getuid", None)
            if getuid is not None and self._root.stat().st_uid != getuid():
                return False
            probe = self._root / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False

    def _path(self, task_id: str) -> Path:
        if not task_id or len(task_id) > 128 or "/" in task_id or task_id in {".", ".."}:
            raise PeerError("params_schema_invalid", f"非法 task_id: {task_id!r}")
        return self._root / f"{task_id}.json"

    def _consumed_path(self, task_id: str) -> Path:
        return self._root / f"{task_id}.consumed.json"

    def issue(
        self,
        *,
        task_id: str,
        node_id: str,
        kind: str,
        params_digest: str,
        issued_by: str,
        ttl_s: int,
    ) -> SupervisionTicket:
        if not params_digest:
            raise PeerError("supervision_ticket_missing", "任务缺少 params_digest，拒绝签票")
        if not issued_by.strip():
            raise PeerError("supervision_ticket_missing", "缺少确认人")
        if not self.available():
            raise PeerError("supervision_channel_unavailable", str(self._root))
        path = self._path(task_id)
        if path.exists() or self._consumed_path(task_id).exists():
            raise PeerError("idempotency_conflict", f"任务 {task_id} 已有票据记录")
        now = self._clock()
        ticket = SupervisionTicket(
            task_id=task_id,
            node_id=node_id,
            kind=kind,
            params_digest=params_digest,
            issued_by=issued_by,
            issued_at=iso(now),
            expires_at=iso(now + timedelta(seconds=max(1, int(ttl_s)))),
        )
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(ticket.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                # 票据是"一次性"的唯一凭据：落盘即视为已签发，不能只靠页缓存
                # （掉电后"票在内存里签发过、盘上没有"会让确认与审计对不上）。
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            path.unlink(missing_ok=True)
            raise
        self._fsync_dir()
        return ticket

    def _fsync_dir(self) -> None:
        """目录项也要落盘：O_EXCL 建文件 + rename 的可见性靠父目录 fsync。"""
        try:
            dir_fd = os.open(self._root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    def load(self, task_id: str, *, params_digest: str) -> SupervisionTicket:
        path = self._path(task_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PeerError("supervision_ticket_missing", f"任务 {task_id} 无票据") from exc
        except (OSError, ValueError) as exc:
            raise PeerError("supervision_ticket_missing", f"票据不可读: {exc}") from exc
        ticket = SupervisionTicket.from_dict(raw)
        if ticket.task_id != task_id:
            raise PeerError("supervision_ticket_mismatch", "票据 task_id 不符")
        if not params_digest or ticket.params_digest != params_digest:
            raise PeerError("supervision_ticket_mismatch", "票据绑定的参数摘要与任务不符")
        if parse_ts(ticket.expires_at) <= self._clock():
            raise PeerError("supervision_ticket_expired", ticket.expires_at)
        return ticket

    def consume(self, task_id: str, *, params_digest: str) -> SupervisionTicket:
        if self._consumed_path(task_id).exists():
            raise PeerError("supervision_ticket_consumed", f"任务 {task_id} 票据已被使用")
        ticket = self.load(task_id, params_digest=params_digest)
        try:
            os.replace(self._path(task_id), self._consumed_path(task_id))
        except FileNotFoundError as exc:
            raise PeerError("supervision_ticket_consumed", f"任务 {task_id} 票据已被使用") from exc
        self._fsync_dir()
        return ticket

    def discard(self, task_id: str) -> None:
        for path in (self._path(task_id), self._consumed_path(task_id)):
            path.unlink(missing_ok=True)
