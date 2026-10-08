"""备份归档数据模型与备份存储组件（design §2.3.2.4/§2.3.2.5 / spec §4.4/§6）.

BackupArchive：备份归档数据模型（spec §6.1/§6.2 字段统一），payload 原文存储不改写。
BackupStore：备份存储（写入/读取/列出/标记/清理/状态统计 + 文件名 sanitize + 路径安全），
操作 data/.recovery/ 目录。

DRC T2（Fleet 批次1，2026-10-08）：写路径全部迁移为 store flock 内
tmp(O_EXCL)→file fsync→os.link/os.replace→目录 fsync，消除裸 write_text；
失败分型 definitely_not_committed / commit_outcome_uncertain（uncertain 必 readback）。
设计：docs/DESIGN-20261007-durable-run-contract.md rev9。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from llm_loop.recovery.policy import RetryPolicy
from llm_loop.timekeeping import system_local_now

try:
    import fcntl
except ImportError:  # pragma: no cover — 非 POSIX 运行时退化
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_DIR_FSYNC_ATTEMPTS = 3
_LOCK_FILE_NAME = ".__backup_store.lock"
_PROCESS_LOCK = threading.RLock()


class BackupPersistError(OSError):
    """definitely_not_committed：备份写入未到达提交点（锁不可用 / tmp / link / replace 前失败）.

    未改变任何既有可见状态；同一 payload 可安全重试。
    """


class BackupCommitUncertainError(OSError):
    """commit_outcome_uncertain：link/replace 已生效但目录 fsync 有界重试耗尽.

    禁止盲重放：先按 backup_id/expected_sha256 做逐字 readback 核对可见状态再决定。
    """

    def __init__(
        self,
        message: str,
        *,
        backup_id: str,
        expected_sha256: str,
        visible_state: str,
    ) -> None:
        super().__init__(message)
        self.backup_id = backup_id
        self.expected_sha256 = expected_sha256
        self.visible_state = visible_state


@contextlib.contextmanager
def _store_lock(lock_path: Path):
    """跨进程单写者锁（POSIX flock LOCK_EX）；无 fcntl 运行时退化进程内 RLock.

    仅锁获取失败映射为 BackupPersistError（fail-closed，确定未提交）；
    临界区内抛出的异常原样穿透，不做二次分类。
    锁文件与备份数据同目录，不匹配 *.pending.json 扫描面。
    """
    if fcntl is None:  # pragma: no cover — 非 POSIX 退化路径
        with _PROCESS_LOCK:
            yield
        return
    fd: int | None = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as exc:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise BackupPersistError(f"备份存储锁获取失败(确定未提交): {lock_path}: {exc}") from exc
    try:
        with _PROCESS_LOCK:
            yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(fd)


def _write_temp_exclusive(temp_path: Path, content: str) -> None:
    """O_CREAT|O_EXCL 写临时文件 + file fsync；任一失败清理 tmp 不留残骸."""
    fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _payload_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _visible_state(path: Path, expected: str) -> str:
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError:
        return "unreadable"
    return "matches" if actual == expected else "mismatch"


@dataclass
class BackupArchive:
    """备份归档数据模型（spec §6.1/§6.2 字段统一）.

    - source_id：来源标识（session_id 或 "memory"）。
    - backup_at：ISO 时间戳。
    - target_type："session" | "memory_stats"。
    - payload：待写入原文（不摘要/改写/压缩，spec §4.2.2 规则 3）。
    - retry_count：转备份前已重试次数。
    - trigger_point："initial_save" | "loop_end_save" | "memory_flush"。
    - recovered：恢复状态（默认 False）。
    """

    source_id: str
    backup_at: str
    target_type: str
    payload: str
    retry_count: int
    trigger_point: str
    recovered: bool = False

    @property
    def backup_id(self) -> str:
        """生成文件名 <source_id>.<YYYYMMDDHHMMSS>.<target_type>.pending.json."""
        safe_id = BackupStore.sanitize_source_id(self.source_id)
        ts = datetime.fromisoformat(self.backup_at).strftime("%Y%m%d%H%M%S")
        return f"{safe_id}.{ts}.{self.target_type}.pending.json"

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "backup_at": self.backup_at,
            "target_type": self.target_type,
            "payload": self.payload,
            "retry_count": self.retry_count,
            "trigger_point": self.trigger_point,
            "recovered": self.recovered,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BackupArchive:
        return cls(
            source_id=data["source_id"],
            backup_at=data["backup_at"],
            target_type=data["target_type"],
            payload=data["payload"],
            retry_count=data["retry_count"],
            trigger_point=data["trigger_point"],
            recovered=data.get("recovered", False),
        )


class BackupStore:
    """备份存储组件，操作 data/.recovery/ 目录.

    - save_archive：写入 .pending.json（文件名 sanitize + 路径安全）。
    - get_archive：读取并解析（损坏返回 None）。
    - list_pending：列出待恢复备份（recovered=False，按时间排序）。
    - mark_recovered：标记已恢复（不删除文件）。
    - cleanup：清理超期超量（删最旧 + action_trace 留痕）。
    - status_summary：供 architecture_status 感知。
    """

    _MAX_SOURCE_ID_LEN = 128
    _BACKUP_ID_RE = re.compile(
        r"^(?P<source>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\."
        r"(?P<ts>\d{14})\.(?P<target>session|memory_stats)\.pending\.json$"
    )

    def __init__(self, recovery_dir: str | Path) -> None:
        self._dir = Path(recovery_dir)

    @classmethod
    def is_safe_backup_id(cls, backup_id: str) -> bool:
        """backup_id 必须是规范pending备份basename；读取/标记同样禁止路径穿越。"""
        if not isinstance(backup_id, str) or not backup_id:
            return False
        if backup_id in {".", ".."} or "/" in backup_id or "\\" in backup_id or "\x00" in backup_id:
            return False
        match = cls._BACKUP_ID_RE.fullmatch(backup_id)
        if match is None:
            return False
        source = match.group("source")
        return cls.sanitize_source_id(source) == source

    @staticmethod
    def sanitize_source_id(source_id: str) -> str:
        """kebab-case + 拒绝路径穿越 + 截断长度（spec §4.3.1）."""
        s = re.sub(r"[^a-zA-Z0-9._-]", "-", source_id)
        s = re.sub(r"-+", "-", s).strip("-_.")
        if not s:
            s = "unnamed"
        s = s[: BackupStore._MAX_SOURCE_ID_LEN]
        return s

    def save_archive(self, archive: BackupArchive) -> str:
        """写入备份归档文件，返回 backup_id（durable create-if-absent，绝不静默覆盖）.

        DRC T2：store flock 内 tmp(O_EXCL)→file fsync→os.link 原子 create-if-absent
        →目录 fsync。同 backup_id 同 payload 幂等返回；不同 payload 抛 FileExistsError
        （先到的备份保留——恢复路径的最后一道保险不做 last-writer-wins）。
        replace/link 前失败=BackupPersistError（确定未提交，同 payload 重试安全）；
        link 已生效但目录 fsync 耗尽=BackupCommitUncertainError（禁止盲重放，先 readback）。
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        backup_id = archive.backup_id
        if not self.is_safe_backup_id(backup_id):
            raise ValueError(f"非法 backup_id: {backup_id!r}")
        path = self._dir / backup_id
        content = json.dumps(archive.to_dict(), ensure_ascii=False, indent=2)
        with _store_lock(self._dir / _LOCK_FILE_NAME):
            if path.exists():
                self._assert_idempotent_or_conflict(path, backup_id, content)
                return backup_id
            temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
            try:
                _write_temp_exclusive(temp, content)
                try:
                    os.link(temp, path)  # 原子 create-if-absent：绝不覆盖任何已存在文件
                except FileExistsError:
                    # 并发竞态另一方先到（绕过锁的写者）：持锁 readback 判定幂等或冲突
                    self._assert_idempotent_or_conflict(path, backup_id, content)
                    return backup_id
                except OSError as exc:
                    raise BackupPersistError(
                        f"备份写入失败(确定未提交): {backup_id}: {exc}"
                    ) from exc
            finally:
                with contextlib.suppress(OSError):
                    temp.unlink(missing_ok=True)
            self._fsync_dir_or_uncertain(path, content, backup_id)
        return backup_id

    def _assert_idempotent_or_conflict(self, path: Path, backup_id: str, content: str) -> None:
        """同 backup_id 已存在时：逐字 readback——同 payload 幂等放行，否则冲突拒绝."""
        state = _visible_state(path, content)
        if state == "matches":
            logger.info("[BackupStore] 同 payload 重复保存，幂等视为已提交: %s", backup_id)
            return
        raise FileExistsError(
            f"备份已存在且内容不同(拒绝覆盖，先到备份保留): {backup_id} (readback={state})"
        )

    def _fsync_dir_or_uncertain(self, path: Path, content: str, backup_id: str) -> None:
        """link/replace 已生效后的目录 fsync：有界重试，耗尽→typed uncertain + readback.

        持 store flock 时逐字 readback 最终文件（单写者下 readback 可信）；
        调用方必须仍处于 _store_lock 临界区内。
        """
        last_exc: OSError | None = None
        for _ in range(_DIR_FSYNC_ATTEMPTS):
            try:
                _fsync_directory(self._dir)
                return
            except OSError as exc:
                last_exc = exc
        raise BackupCommitUncertainError(
            f"备份已原子可见但目录 fsync 失败(提交结果不确定): {backup_id}: {last_exc}",
            backup_id=backup_id,
            expected_sha256=_payload_sha256(content),
            visible_state=_visible_state(path, content),
        )

    def get_archive(self, backup_id: str) -> BackupArchive | None:
        """读取并解析备份归档（不存在/损坏/非法ID返回 None）."""
        if not self.is_safe_backup_id(backup_id):
            return None
        path = self._dir / backup_id
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BackupArchive.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def list_pending(self, target_type: str | None = None) -> list[BackupArchive]:
        """列出待恢复备份（recovered=False，按 backup_at 排序）."""
        if not self._dir.exists():
            return []
        result: list[BackupArchive] = []
        for p in self._dir.glob("*.pending.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                archive = BackupArchive.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            if archive.recovered:
                continue
            if target_type is not None and archive.target_type != target_type:
                continue
            result.append(archive)
        result.sort(key=lambda a: a.backup_at)
        return result

    def mark_recovered(self, backup_id: str) -> bool:
        """标记备份为已恢复（更新文件内 recovered=True，不删除文件）.

        DRC T2：store flock 内单写者 RMW——tmp(O_EXCL)→file fsync→os.replace→目录
        fsync，最终文件只可能整体旧或整体新，无撕裂中间态。保持 bool 契约不抛穿调用方：
        - replace 前失败/缺失/损坏/锁不可用 → False（确定未提交；语义动作是幂等设置
          recovered=True，重试不会叠加第二份语义动作）；
        - replace 后目录 fsync 耗尽 → 持锁 readback reconcile：逐字匹配 → True
          （已可见，不重放）；mismatch/unreadable → False + warning（提交结果不确定，
          禁止盲重放，由调用方以 readback 结果裁决）。
        """
        if not self.is_safe_backup_id(backup_id):
            return False
        path = self._dir / backup_id
        if not path.exists():
            return False
        try:
            with _store_lock(self._dir / _LOCK_FILE_NAME):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, KeyError, ValueError, OSError):
                    return False  # 损坏/不可读：fail-open 不改写原文件
                if data.get("recovered") is True:
                    return True  # 已标记：幂等，不产生新写入
                data["recovered"] = True
                content = json.dumps(data, ensure_ascii=False, indent=2)
                temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
                try:
                    _write_temp_exclusive(temp, content)
                    os.replace(temp, path)  # 原子换档：整体旧或整体新
                except OSError as exc:
                    with contextlib.suppress(OSError):
                        temp.unlink(missing_ok=True)
                    logger.warning(
                        "[BackupStore] mark_recovered 确定未提交: %s (%s)", backup_id, exc
                    )
                    return False
                uncertain_exc: OSError | None = None
                for _ in range(_DIR_FSYNC_ATTEMPTS):
                    try:
                        _fsync_directory(self._dir)
                        return True
                    except OSError as exc:
                        uncertain_exc = exc
                state = _visible_state(path, content)
                if state == "matches":
                    logger.warning(
                        "[BackupStore] mark_recovered 提交结果不确定→readback 匹配，视为已提交: %s",
                        backup_id,
                    )
                    return True
                logger.warning(
                    "[BackupStore] mark_recovered 提交结果不确定，visible_state=%s: %s (%s)",
                    state,
                    backup_id,
                    uncertain_exc,
                )
                return False
        except BackupPersistError as exc:
            logger.warning(
                "[BackupStore] mark_recovered 锁不可用 fail-closed(确定未提交): %s (%s)",
                backup_id,
                exc,
            )
            return False

    def delete_source(self, source_id: str, *, target_type: str = "session") -> int:
        """物理删除精确source_id备份；sanitize碰撞只按文件内容原始source判定。

        若同sanitize命名空间存在损坏文件，无法证明其不属于目标source，fail-closed。
        DRC T2：删除与 save/mark 共用 store flock（写者互斥）；锁不可用=
        BackupPersistError（确定未提交，什么都没删）。删除后 best-effort 目录 fsync——
        删除即使未 durable 也属保守面（最坏=已删备份复活，由恢复侧幂等裁决）。
        """
        if target_type not in {"session", "memory_stats"}:
            raise ValueError(f"非法 target_type: {target_type!r}")
        if not self._dir.exists():
            return 0
        safe_source = self.sanitize_source_id(source_id)
        removed = 0
        with _store_lock(self._dir / _LOCK_FILE_NAME):
            for path in self._dir.glob("*.pending.json"):
                match = self._BACKUP_ID_RE.fullmatch(path.name)
                if match is None or match.group("source") != safe_source:
                    continue
                try:
                    archive = BackupArchive.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                    raise OSError(
                        f"无法判定恢复备份归属，拒绝物理删除: {path.name}"
                    ) from exc
                if archive.source_id != source_id or archive.target_type != target_type:
                    continue
                path.unlink()
                removed += 1
            if removed:
                with contextlib.suppress(OSError):
                    _fsync_directory(self._dir)
        return removed

    def status_summary(self) -> dict:
        """返回 {pending_count, oldest_backup_at, by_type}（如实，不伪造）."""
        if not self._dir.exists():
            return {"pending_count": 0, "oldest_backup_at": None, "by_type": {"session": 0, "memory_stats": 0}}
        pending = self.list_pending()
        by_type: dict[str, int] = {"session": 0, "memory_stats": 0}
        for a in pending:
            by_type[a.target_type] = by_type.get(a.target_type, 0) + 1
        oldest = pending[0].backup_at if pending else None
        return {"pending_count": len(pending), "oldest_backup_at": oldest, "by_type": by_type}

    def cleanup(self) -> dict:
        """清理超期超量备份（删最旧 + action_trace 留痕，不静默删除）.

        返回 {"pruned": N}。
        DRC T2：与 save/mark/delete 共用 store flock（写者互斥）；锁不可用=
        BackupPersistError（确定未提交，什么都没删，由调用方 fail-open 吸收）。
        """
        if not self._dir.exists():
            return {"pruned": 0}
        now = system_local_now()
        cutoff = now.timestamp() - RetryPolicy.RETENTION_PERIOD_DAYS * 86400
        pruned = 0

        with _store_lock(self._dir / _LOCK_FILE_NAME):
            # 按文件分组（source_id + target_type）
            groups: dict[str, list[tuple[Path, BackupArchive]]] = {}
            for p in self._dir.glob("*.pending.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    archive = BackupArchive.from_dict(data)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
                key = f"{archive.source_id}.{archive.target_type}"
                groups.setdefault(key, []).append((p, archive))

            for _key, items in groups.items():
                items.sort(key=lambda x: x[1].backup_at)
                # 超期清理
                for path, archive in list(items):
                    try:
                        ts = datetime.fromisoformat(archive.backup_at).timestamp()
                    except ValueError:
                        continue
                    if ts < cutoff:
                        try:
                            path.unlink()
                            pruned += 1
                            items.remove((path, archive))
                        except OSError:
                            pass  # 清理失败如实跳过（fail-open，不中断主循环）
                # 超量清理（保留 MAX_PER_TARGET 份最旧）
                while len(items) > RetryPolicy.MAX_PER_TARGET:
                    path, _archive = items.pop(0)
                    try:
                        path.unlink()
                        pruned += 1
                    except OSError:
                        pass  # 清理失败如实跳过（fail-open，不中断主循环）

            if pruned:
                with contextlib.suppress(OSError):
                    _fsync_directory(self._dir)

        return {"pruned": pruned}
