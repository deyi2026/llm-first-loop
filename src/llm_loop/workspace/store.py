"""工作区注册表（对齐 DSH Workspace：目录绑定、会话按工作区分区隔离）.

- 注册表文件: data/workspaces.json（version + workspaces[{id, path, created_at}]）
- workspace key（会话目录名）: DSH 式路径编码 `--Users-yyj-Project-llm-first-loop--`
  （绝对路径 / → -，剥前导 /，首尾 --）
- 会话存储: data/sessions/<key>/<session_id>.json（按工作区分区）
- 迁移: 首次装配把 data/sessions 下旧会话（非目录文件）移入默认工作区目录（幂等）
- 安全: create 校验路径为存在的目录 + 绝对路径规范化；remove 仅注销注册不删数据
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback only
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_REGISTRY_NAME = "workspaces.json"
_REGISTRY_VERSION = 2
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class WorkspacePersistenceError(RuntimeError):
    """工作区注册表持久化失败；调用方不得把仅内存变更宣称为成功。"""


class WorkspaceMigrationConflictError(RuntimeError):
    """旧会话迁移存在两份不同内容，程序不能安全自动裁决。"""


class WorkspacePathUnavailableError(RuntimeError):
    """工作区已注册，但目录当前不存在/不可访问。"""


class WorkspaceBusyError(RuntimeError):
    """存在进行中的run或workspace transition，当前不能安全切换全局工作区根。"""


class WorkspaceChangedError(RuntimeError):
    """请求解析session后workspace已变化；旧session归属不能安全沿用。"""


def _process_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


def workspace_key(path: str | Path) -> str:
    """绝对路径 → DSH 兼容 legacy key（非单射，仅保留外部兼容，不再视为唯一ID）."""
    p = Path(path).resolve()
    return "--" + str(p).lstrip("/").replace("/", "-") + "--"


def _validate_workspace_id(workspace_id: str) -> str:
    """内部workspace id必须是单个安全目录名。"""
    if not isinstance(workspace_id, str) or not workspace_id:
        raise ValueError("非法 workspace id: 不能为空")
    if (
        workspace_id in {".", ".."}
        or "/" in workspace_id
        or "\\" in workspace_id
        or "\x00" in workspace_id
    ):
        raise ValueError("非法 workspace id: 不得包含路径分隔符、NUL 或目录跳转")
    return workspace_id


def _collision_workspace_id(legacy_key: str, path: str, digest_len: int = 12) -> str:
    """legacy key碰撞时生成稳定内部ID；不改变workspace_key外部兼容编码。"""
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:digest_len]
    prefix = legacy_key[:-2] if legacy_key.endswith("--") else legacy_key
    if not prefix or any(ch in prefix for ch in ("/", "\\", "\x00")):
        prefix = "--workspace"
    return _validate_workspace_id(f"{prefix}~{digest}--")


@dataclass
class Workspace:
    """一个工作区条目（目录绑定；id 为安全内部唯一分区键）."""

    path: str  # 规范化绝对路径
    created_at: str = ""
    id: str = ""  # 默认沿用legacy workspace_key；碰撞时由store分配稳定后缀ID

    def __post_init__(self) -> None:
        if not self.id:
            self.id = workspace_key(self.path)


class WorkspaceStore:
    """工作区注册表（fail-open 加载；原子写保存）."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / _REGISTRY_NAME
        self._lock_file = self._data_dir / "workspaces.lock"
        self._guard = _process_lock_for(self._file)
        self._workspaces: dict[str, Workspace] = {}
        self._retired_by_path: dict[str, Workspace] = {}
        self._current_id: str = ""
        self._load()

    # ── 读取 ──
    def _parse_registry(
        self,
    ) -> tuple[dict[str, Workspace], str, dict[str, Workspace]]:
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        workspaces: dict[str, Workspace] = {}
        for w in raw.get("workspaces", []):
            path = str(w.get("path", "")).strip()
            if not path:
                continue
            ws_id = str(w.get("id", "")).strip() or workspace_key(path)
            try:
                ws_id = _validate_workspace_id(ws_id)
            except ValueError as exc:
                logger.warning("工作区注册表跳过不安全ID（fail-closed）: %s", exc)
                continue
            ws = Workspace(path=path, created_at=str(w.get("created_at", "")), id=ws_id)
            existed = workspaces.get(ws.id)
            if existed is not None and existed.path != ws.path:
                logger.warning(
                    "工作区注册表跳过重复ID冲突: id=%s path=%s existing=%s",
                    ws.id, ws.path, existed.path,
                )
                continue
            workspaces[ws.id] = ws

        retired_by_path: dict[str, Workspace] = {}
        raw_retired = raw.get("retired", [])
        if isinstance(raw_retired, dict):
            raw_retired = [
                {"path": path, "id": ws_id, "created_at": ""}
                for path, ws_id in raw_retired.items()
            ]
        if isinstance(raw_retired, list):
            active_paths = {w.path for w in workspaces.values()}
            active_ids = set(workspaces)
            for item in raw_retired:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", "")).strip()
                ws_id = str(item.get("id", "")).strip()
                if not path or not ws_id or path in active_paths:
                    continue
                try:
                    ws_id = _validate_workspace_id(ws_id)
                except ValueError as exc:
                    logger.warning("工作区注册表跳过不安全retired ID: %s", exc)
                    continue
                if ws_id in active_ids or any(w.id == ws_id for w in retired_by_path.values()):
                    logger.warning("工作区注册表跳过retired ID冲突: id=%s path=%s", ws_id, path)
                    continue
                retired_by_path[path] = Workspace(
                    path=path, created_at=str(item.get("created_at", "")), id=ws_id
                )

        current = str(raw.get("current", "")).strip()
        if current:
            try:
                current = _validate_workspace_id(current)
            except ValueError as exc:
                logger.warning("工作区注册表忽略不安全current ID: %s", exc)
                current = ""
        return workspaces, current, retired_by_path

    def _load(self, *, strict: bool = False) -> bool:
        """原子替换内存快照；初始化fail-open，变更前strict拒绝覆盖损坏registry。"""
        try:
            workspaces, current, retired_by_path = self._parse_registry()
        except FileNotFoundError:
            workspaces, current, retired_by_path = {}, "", {}
        except Exception as exc:  # noqa: BLE001 — 初始化兼容fail-open；mutation用strict
            if strict:
                raise ValueError(f"工作区注册表损坏，拒绝覆盖: {exc}") from exc
            logger.warning("工作区注册表加载失败（fail-open）: %s", exc)
            return False
        self._workspaces = workspaces
        self._retired_by_path = retired_by_path
        self._current_id = current
        return True

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """跨实例/跨进程稳定锁；POSIX flock 不可用时至少保留进程内共享RLock。"""
        with self._guard:
            fd = os.open(self._lock_file, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _save(self) -> bool:
        payload = {
            "version": _REGISTRY_VERSION,
            "current": self._current_id,
            "workspaces": [
                {"id": w.id, "path": w.path, "created_at": w.created_at}
                for w in self._workspaces.values()
            ],
            "retired": [
                {"id": w.id, "path": w.path, "created_at": w.created_at}
                for w in self._retired_by_path.values()
            ],
        }
        tmp = self._file.with_name(
            f"{self._file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        dir_fd: int | None = None
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._file)
            try:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                dir_fd = os.open(self._data_dir, flags)
                os.fsync(dir_fd)
            except OSError:
                logger.warning(
                    "工作区注册表目录 fsync 失败（写入已完成，耐久性降级）: %s",
                    self._data_dir,
                    exc_info=True,
                )
            return True
        except OSError as exc:
            logger.warning("工作区注册表保存失败（fail-open）: %s", exc)
            return False
        finally:
            if dir_fd is not None:
                os.close(dir_fd)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.debug("工作区注册表临时文件清理失败: %s", tmp, exc_info=True)

    def _save_or_rollback(
        self,
        before_workspaces: dict[str, Workspace],
        before_current: str,
        before_retired: dict[str, Workspace],
    ) -> None:
        if self._save():
            return
        self._workspaces = before_workspaces
        self._retired_by_path = before_retired
        self._current_id = before_current
        raise WorkspacePersistenceError("工作区注册表持久化失败，内存变更已回滚")

    def list(self) -> list[Workspace]:
        with self._guard:
            return list(self._workspaces.values())

    def get(self, ws_id: str) -> Workspace | None:
        with self._guard:
            return self._workspaces.get(ws_id)

    def get_by_path(self, path: str | Path) -> Workspace | None:
        """按规范化绝对路径精确查询，不依赖可能碰撞的legacy key。"""
        normalized = str(Path(path).expanduser().resolve())
        with self._guard:
            return next(
                (w for w in self._workspaces.values() if w.path == normalized), None
            )

    def get_current(self) -> Workspace | None:
        with self._guard:
            return self._workspaces.get(self._current_id)

    def sessions_root(self, data_dir: str | Path) -> Path:
        """当前工作区会话目录（data/sessions/<workspace-id>）."""
        base = Path(data_dir) / "sessions"
        current = self.get_current()
        if current is None:
            return base
        return base / current.id

    # ── 变更 ──
    def _id_owner_path(self, ws_id: str) -> str | None:
        active = self._workspaces.get(ws_id)
        if active is not None:
            return active.path
        for retired in self._retired_by_path.values():
            if retired.id == ws_id:
                return retired.path
        return None

    def _ensure_registered_in_memory(self, p: Path) -> tuple[Workspace, bool]:
        """在已加载快照上确保path存在；retired tombstone保证注销后ID/会话分区稳定。"""
        normalized = str(p)
        by_path = self.get_by_path(p)
        if by_path is not None:
            return by_path, False

        retired = self._retired_by_path.pop(normalized, None)
        if retired is not None:
            owner = self._id_owner_path(retired.id)
            if owner is not None and owner != normalized:
                self._retired_by_path[normalized] = retired
                raise ValueError(
                    f"历史工作区ID已被其它路径占用: id={retired.id} owner={owner}"
                )
            self._workspaces[retired.id] = retired
            return retired, True

        legacy_key = workspace_key(p)
        owner = self._id_owner_path(legacy_key)
        if owner is None:
            try:
                ws_id = _validate_workspace_id(legacy_key)
            except ValueError:
                ws_id = _collision_workspace_id(legacy_key, normalized)
        else:
            # active/retired ID都算保留：注销不能让别的碰撞路径抢走旧session分区。
            digest_len = 12
            while True:
                ws_id = _collision_workspace_id(legacy_key, normalized, digest_len)
                collision_owner = self._id_owner_path(ws_id)
                if collision_owner is None:
                    break
                if digest_len >= 64:
                    raise ValueError("工作区ID哈希碰撞，无法安全注册")
                digest_len = min(64, digest_len + 4)
        ws = Workspace(
            path=normalized,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            id=ws_id,
        )
        self._workspaces[ws.id] = ws
        return ws, True

    def register(self, path: str | Path) -> Workspace:
        """注册工作区；锁内重载磁盘再RMW，避免多进程stale覆盖。"""
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"工作区路径不是存在的目录: {p}")
        with self._file_lock():
            self._load(strict=True)
            before_workspaces = self._workspaces.copy()
            before_retired = self._retired_by_path.copy()
            before_current = self._current_id
            ws, created = self._ensure_registered_in_memory(p)
            if created:
                self._save_or_rollback(before_workspaces, before_current, before_retired)
        if created:
            logger.info("工作区注册: %s", ws.path)
        return ws

    def register_and_switch(
        self,
        path: str | Path,
        *,
        precommit: Callable[[Workspace], None] | None = None,
    ) -> Workspace:
        """原子“注册并切换”：runtime预检成功后再单次持久化。

        ``precommit`` 在最终 workspace id 已确定、registry 尚未保存时执行。
        它只应做可能失败但无 registry 副作用的准备工作；若失败，本方法恢复
        锁内加载后的 workspaces/retired/current 快照并原样抛出。
        """
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"工作区路径不是存在的目录: {p}")
        with self._file_lock():
            self._load(strict=True)
            before_workspaces = self._workspaces.copy()
            before_retired = self._retired_by_path.copy()
            before_current = self._current_id
            ws, created = self._ensure_registered_in_memory(p)
            switched = self._current_id != ws.id
            try:
                if precommit is not None:
                    precommit(ws)
            except Exception:
                self._workspaces = before_workspaces
                self._retired_by_path = before_retired
                self._current_id = before_current
                raise
            self._current_id = ws.id
            if created or switched:
                self._save_or_rollback(before_workspaces, before_current, before_retired)
        if created:
            logger.info("工作区注册: %s", ws.path)
        return ws

    def switch(
        self,
        ws_id: str,
        *,
        precommit: Callable[[Workspace], None] | None = None,
    ) -> Workspace:
        """切换当前工作区；runtime预检成功后才提交current。"""
        ws_id = _validate_workspace_id(ws_id)
        with self._file_lock():
            self._load(strict=True)
            before_workspaces = self._workspaces.copy()
            before_retired = self._retired_by_path.copy()
            before_current = self._current_id
            ws = self._workspaces.get(ws_id)
            if ws is None:
                raise ValueError(f"工作区未注册: {ws_id}")
            if not Path(ws.path).is_dir():
                raise WorkspacePathUnavailableError(
                    f"工作区目录当前不可用: {ws.path}"
                )
            if precommit is not None:
                precommit(ws)
            self._current_id = ws_id
            self._save_or_rollback(before_workspaces, before_current, before_retired)
            return ws

    def remove(self, ws_id: str) -> bool:
        """注销工作区（不删会话数据；当前工作区不可注销）."""
        try:
            ws_id = _validate_workspace_id(ws_id)
        except ValueError:
            return False
        with self._file_lock():
            try:
                self._load(strict=True)
            except ValueError as exc:
                logger.warning("工作区注册表损坏，拒绝注销: %s", exc)
                return False
            before_workspaces = self._workspaces.copy()
            before_retired = self._retired_by_path.copy()
            before_current = self._current_id
            if ws_id == self._current_id:
                return False
            ws = self._workspaces.get(ws_id)
            if ws is None:
                return False
            self._retired_by_path[ws.path] = ws
            del self._workspaces[ws_id]
            self._save_or_rollback(before_workspaces, before_current, before_retired)
            return True

    # ── 迁移（旧单根会话 → 默认工作区）──
    def migrate_legacy_sessions(self, data_dir: str | Path, default_workspace: Workspace) -> int:
        """把 data/sessions/ 下旧版单根会话文件移入默认工作区目录（幂等）.

        同名 JSON 若内容不同，视为部分迁移冲突并显式拒绝，避免静默搁置旧根数据。
        锁文件不承载业务内容，同名时可安全保留旧锁（不删除可能仍被旧进程持有的 inode）。
        """
        base = Path(data_dir) / "sessions"
        if not base.is_dir():
            return 0
        workspace_id = _validate_workspace_id(default_workspace.id)
        target = base / workspace_id
        moved = 0
        with self._file_lock():
            target.mkdir(parents=True, exist_ok=True)
            for p in sorted(base.iterdir()):
                if p.is_dir() or p.suffix not in (".json", ".lock"):
                    continue
                dest = target / p.name
                if dest.exists():
                    if p.suffix == ".json":
                        try:
                            if p.read_bytes() != dest.read_bytes():
                                raise WorkspaceMigrationConflictError(
                                    f"会话迁移冲突: 旧根与目标存在不同内容的同名文件 {p.name}"
                                )
                        except OSError as exc:
                            raise WorkspaceMigrationConflictError(
                                f"会话迁移冲突检查失败: {p} ↔ {dest}: {exc}"
                            ) from exc
                    continue
                try:
                    shutil.move(str(p), str(dest))
                    moved += 1
                except OSError as exc:
                    logger.warning("会话迁移失败（fail-open）: %s → %s: %s", p, dest, exc)
        if moved:
            logger.info("工作区迁移: %d 个旧会话移入 %s", moved, target)
        return moved
