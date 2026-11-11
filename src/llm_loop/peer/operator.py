"""监督通道票据（DESIGN-20261108 §2.2/§2.4）。

票据是"有人在本机 TTY 逐次确认"的物证：

- 绑定 ``task_id + params_digest + kind + node_id``：参数一改就失效；
- 一次性：``consume`` 用 ``os.replace`` 原子认领，第二个消费者必然找不到源文件；
- 覆盖确认快照（R37，LFL_Peer_Requirements_Implementation_Design_2026-11-11 §6.3/A05）：
  ``issue(target=...)`` 在预览时捕获目标文件字节摘要与权限位并持久化进票据；
  ``consume`` 认领前重查，摘要或权限位任一不符（或存在性翻转）即以
  ``supervision_ticket_mismatch`` 报冲突，不静默沿用变化后的权限。快照只协调遵守
  它的 Peer 写入者，stat 与读文件之间仍有残余窗口，不构成通用文件 CAS；
- TTL：任务进入等待态时持久化绝对 ``supervision_expires_at``；服务与 CLI 共用同一截止时间；
- 属主：数据目录必须属于当前 uid，避免别人替你批准。

HTTP 面没有签发票据的入口（D3）；票据只能由本机 CLI 产生。
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
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
class TargetSnapshot:
    """覆盖确认快照（R37）：预览时捕获的目标文件字节摘要与权限位。

    ``exists=False`` 是"预览时目标不存在（新建）"的绑定形态；确认前目标出现
    同样算冲突（执行语义已从新建变成覆盖）。快照随票据落盘，跨进程重查。
    """

    path: str
    exists: bool
    sha256: str = ""
    mode: int = 0
    size: int = 0

    @classmethod
    def capture(cls, path: str | os.PathLike[str]) -> TargetSnapshot:
        """读取目标当前状态。目录/符号链接/不可读目标 fail-closed 拒绝。

        用 ``lstat``：符号链接本身不是可绑定的普通文件（含悬空链接），拒绝而不是
        跟随——跟随会把"链接目标的内容"静默当成"目标路径的内容"绑进确认。
        """
        real = os.fspath(path)
        try:
            st = os.lstat(real)
        except FileNotFoundError:
            return cls(path=real, exists=False)
        except OSError as exc:
            raise PeerError("sandbox_denied", f"cannot snapshot target: {exc}") from None
        if not stat.S_ISREG(st.st_mode):
            raise PeerError("params_schema_invalid", f"target is not a regular file: {real!r}")
        digest = hashlib.sha256()
        size = 0
        try:
            with open(real, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
                    size += len(chunk)
        except OSError as exc:
            raise PeerError("sandbox_denied", f"cannot read target: {exc}") from None
        return cls(
            path=real,
            exists=True,
            sha256=digest.hexdigest(),
            mode=st.st_mode & 0o777,
            size=size,
        )

    def diff(self, current: TargetSnapshot) -> str | None:
        """与重查结果比对；一致返回 ``None``，否则返回人可读的差异描述。"""
        if self.exists and not current.exists:
            return f"目标已消失（预览时存在，size={self.size}）"
        if not self.exists and current.exists:
            return f"目标已出现（预览时不存在，现 size={current.size}）"
        changes: list[str] = []
        if self.sha256 != current.sha256:
            changes.append(f"内容摘要 {self.sha256[:12]}… → {current.sha256[:12]}…")
        if self.mode != current.mode:
            changes.append(f"权限位 {self.mode:0o} → {current.mode:0o}")
        return "；".join(changes) if changes else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "mode": self.mode,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> TargetSnapshot:
        """解析落盘快照；损坏即拒绝（``supervision_ticket_mismatch``），不补默认值。"""
        if not isinstance(raw, dict):
            raise PeerError("supervision_ticket_mismatch", "票据目标快照不是对象")
        path = raw.get("path")
        exists = raw.get("exists")
        if not isinstance(path, str) or not path.strip() or not isinstance(exists, bool):
            raise PeerError("supervision_ticket_mismatch", "票据目标快照缺少 path/exists")
        sha256 = raw.get("sha256", "")
        mode = raw.get("mode", 0)
        size = raw.get("size", 0)
        if exists and (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or not isinstance(mode, int)
            or not 0 <= mode <= 0o777
            or not isinstance(size, int)
            or size < 0
        ):
            raise PeerError("supervision_ticket_mismatch", "票据目标快照字段损坏")
        return cls(path=path, exists=exists, sha256=sha256, mode=mode, size=size)


@dataclass(frozen=True)
class SupervisionTicket:
    task_id: str
    node_id: str
    kind: str
    params_digest: str
    issued_by: str
    issued_at: str
    expires_at: str
    # 覆盖确认快照（R37）。None = 未绑定目标（旧票据/非写任务），保持现行为。
    target_snapshot: TargetSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {field: getattr(self, field) for field in _FIELDS}
        if self.target_snapshot is not None:
            data["target_snapshot"] = self.target_snapshot.to_dict()
        return data

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
        snapshot_raw = raw.get("target_snapshot")
        snapshot = None if snapshot_raw is None else TargetSnapshot.from_dict(snapshot_raw)
        return cls(**values, target_snapshot=snapshot)


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
        ttl_s: int | None = None,
        expires_at: str | None = None,
        target: str | None = None,
    ) -> SupervisionTicket:
        if not params_digest:
            raise PeerError("supervision_ticket_missing", "任务缺少 params_digest，拒绝签票")
        if not issued_by.strip():
            raise PeerError("supervision_ticket_missing", "缺少确认人")
        if target is not None and not target.strip():
            raise PeerError("params_schema_invalid", "target 必须是非空路径")
        snapshot = TargetSnapshot.capture(target) if target is not None else None
        if not self.available():
            raise PeerError("supervision_channel_unavailable", str(self._root))
        path = self._path(task_id)
        if path.exists() or self._consumed_path(task_id).exists():
            raise PeerError("idempotency_conflict", f"任务 {task_id} 已有票据记录")
        now = self._clock()
        if expires_at is not None and ttl_s is not None:
            raise PeerError("supervision_ticket_missing", "只能指定 expires_at 或 ttl_s 之一")
        if expires_at is None:
            if ttl_s is None:
                raise PeerError("supervision_ticket_missing", "缺少权威票据截止时间")
            expiry = now + timedelta(seconds=max(1, int(ttl_s)))
        else:
            expiry = parse_ts(expires_at)
            if expiry <= now:
                raise PeerError("supervision_ticket_expired", expires_at)
        ticket = SupervisionTicket(
            task_id=task_id,
            node_id=node_id,
            kind=kind,
            params_digest=params_digest,
            issued_by=issued_by,
            issued_at=iso(now),
            expires_at=iso(expiry),
            target_snapshot=snapshot,
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
        # R37：认领前重查覆盖确认快照——摘要或权限位任一不符即冲突，且不烧票
        # （票据保留为批准物证，由 reject/超时路径统一 discard）。
        self._verify_target_snapshot(ticket)
        try:
            os.replace(self._path(task_id), self._consumed_path(task_id))
        except FileNotFoundError as exc:
            raise PeerError("supervision_ticket_consumed", f"任务 {task_id} 票据已被使用") from exc
        self._fsync_dir()
        return ticket

    def _verify_target_snapshot(self, ticket: SupervisionTicket) -> None:
        snapshot = ticket.target_snapshot
        if snapshot is None:
            return
        try:
            current = TargetSnapshot.capture(snapshot.path)
        except PeerError as exc:
            raise PeerError(
                "supervision_ticket_mismatch", f"目标快照重查失败（{exc.reason_code}: {exc.detail}）"
            ) from exc
        changes = snapshot.diff(current)
        if changes:
            raise PeerError(
                "supervision_ticket_mismatch",
                f"覆盖确认快照冲突：{changes}；原确认失效，请重新预览确认",
            )

    def discard(self, task_id: str) -> None:
        for path in (self._path(task_id), self._consumed_path(task_id)):
            path.unlink(missing_ok=True)
