"""会话持久化 SessionStore（design.md §2.2.2.3 / P1 批次1 FR-P1-SES）.

- 唯一 session_id（UUID）；消息完整序列 JSON 落盘 data/sessions/<session_id>.json
- T24: SessionMeta + Session 元数据字段（title/updated_at/status，version 2 向后兼容）
- T25: 多会话方法 list_sessions/get_meta/search/archive/unarchive/delete
- 删除不销毁已沉淀记忆/压缩档案/审计（来源可溯仍指向 session_id）
"""

from __future__ import annotations

import errno
import json
import logging
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.session_types import (  # noqa: F401 — SessionIdConflictError 为 R9-P3-02 re-export（历史导入路径兼容）
    BranchSeed,
    SessionIdConflictError,
)

logger = logging.getLogger(__name__)

_IDENTITY_FALLBACK_GUARD = threading.Lock()
_IDENTITY_FALLBACK_LOCKS: dict[str, threading.Lock] = {}

_ACTIVE = "active"
_ARCHIVED = "archived"

# 会话元数据缓存（2026-09-07 CPU 修复）：绝对路径 → ((mtime_ns, size), SessionMeta)。
# 供 _list_sessions_in 复用未变化文件的解析结果；文件落盘 mtime 必变，天然失效。
_SESSION_META_CACHE: dict[Path, tuple[tuple[int, int], SessionMeta]] = {}
_SESSION_META_CACHE_LOCK = threading.Lock()


def _validate_session_id(session_id: str) -> str:
    """会话ID必须是单个文件名组件；保留legacy非UUID ID但禁止路径穿越。"""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("非法 session_id: 不能为空")
    if session_id in {".", ".."} or "/" in session_id or "\\" in session_id or "\x00" in session_id:
        raise ValueError("非法 session_id: 不得包含路径分隔符、NUL 或目录跳转")
    return session_id


class SessionMutationBusyError(RuntimeError):
    """目标会话正被 whole-run lease 占用，管理写必须 fail-fast。"""


class SessionDeletedError(SessionIdConflictError):
    """session_id 已物理删除且不可恢复/复用。"""


class _LeakWriteDeniedError(RuntimeError):
    """agent_trace_leak 3.6: user 身份写入被通道白名单拒绝（enforce 模式）."""


class _FallbackRunGate:
    """无 fcntl 平台的进程内读写门：run=独占，管理事务=共享，全部非阻塞。"""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._readers = 0
        self._writer = False

    def acquire_exclusive(self) -> bool:
        with self._guard:
            if self._writer or self._readers:
                return False
            self._writer = True
            return True

    def release_exclusive(self) -> None:
        with self._guard:
            self._writer = False

    def acquire_shared(self) -> bool:
        with self._guard:
            if self._writer:
                return False
            self._readers += 1
            return True

    def release_shared(self) -> None:
        with self._guard:
            if self._readers:
                self._readers -= 1

# D1: session.created 事件承载的顶层字段（与 Session.to_dict() 对齐，缺失如实置空）
_EVENT_TOP_FIELDS = (
    "version",
    "title",
    "created_at",
    "updated_at",
    "status",
    "parent_id",
    "branch_id",
    "branch_summary",
    "model_override",
    "pinned",
    "channel",
    "fixed_summary",
    "summary_chain",
    "working_state_checkpoint",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SessionMeta:
    """会话元数据（FR-P1-SES-01: 不含完整消息内容）."""

    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    status: Literal["active", "archived"]
    last_message_preview: str
    # M56（Web/飞书会话同步）: 缺省向后兼容
    pinned: bool = False   # 置顶
    channel: str = "web"   # 来源通道

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Session:
    """会话聚合（数据约束 6.4）: 保序持有完整消息序列."""

    session_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    title: str = ""  # T24: 默认标题（确定性生成，不调 LLM）
    updated_at: str = field(default_factory=_now)
    status: Literal["active", "archived"] = _ACTIVE  # T24: 活跃/归档
    # version 3 分支字段（EVO-20260810-3188682f：会话分支；缺省向后兼容 version 1/2）
    parent_id: str | None = None  # 父会话 id（根会话为 None；fork 时指向来源会话）
    branch_id: str = ""           # 分支标识（根会话为空；fork 生成唯一短 id）
    branch_summary: str = ""      # 分支摘要（fork 时从父会话分叉点后提炼，跨分支情报传递）
    # M48（design §5.3）：会话级模型覆盖（switch_model 工具写入；None = 用装配默认）
    # 旧会话 JSON 缺省 → None（向后兼容，向前兼容 version 1/2/3 三套字段）
    model_override: str | None = None
    # M56（Web/飞书会话同步）：version 4 字段，缺省向后兼容
    pinned: bool = False      # 置顶（Web 端会话列表置顶优先）
    channel: str = "web"      # 来源通道: "web" / "feishu:p2p:{open_id}" / "feishu:group:{chat_id}"
    # P1-10（窗口锚定）: 各 provider 的历史窗口锚点（provider_id → sess.messages 索引）。
    # 锚定后历史起点固定（只追加不挤旧, 超预算优先降级中段）, system+历史前缀稳定 →
    # 引擎/服务端前缀缓存命中; 缺省向后兼容（旧 JSON 无键 → {}）
    history_anchors: dict[str, int] = field(default_factory=dict)
    # P4: anchor 的生成 contract（provider_id → {version, model, effective_budget}）。
    # 旧会话没有 provenance 时，当前 build 会把非零 legacy anchor 视为 stale 并按
    # 当前模型/预算重算一次，避免 80K/100K 时代的锚点永久压制后续 1M 模型。
    history_anchor_scopes: dict[str, dict] = field(default_factory=dict)
    # EVO-20260817-b6554376: 投影一致性门闸缓存行（provider_id → {ver, seq, built_hash, ts}）。
    # 精确水印哨兵：ver+seq 匹配而 built_hash 不同 = 非确定性构建/历史被改 → 告警。
    # 缺省向后兼容（旧 JSON 无键 → {}）
    projection_guard: dict[str, dict] = field(default_factory=dict)
    # 2026-08-21 (追加式压缩, version 5): 摘要链——压缩时归档旧历史, 增量摘要尾部追加。
    # 前缀稳定原则（12 实验）: fixed_summary 生成后程序强制不可变; summary_chain 只尾部追加
    # （新摘要追加, 旧摘要不动）→ system+固定摘要+保留历史字节稳定 → 服务端缓存命中。
    # 缺省向后兼容（旧 JSON 无键 → 空）
    fixed_summary: str = ""                       # 核心固定摘要（首次压缩生成, 永不更新）
    summary_chain: list[str] = field(default_factory=list)  # 增量摘要链（尾部追加, 低频合并）
    # S1 selective-evidence canary: internal model-authored fold state. It is
    # persisted out-of-band from messages so it cannot masquerade as a normal
    # assistant turn or trigger tool-consumer retirement. None = zero behavior.
    working_state_checkpoint: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "version": 5,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "title": self.title,
            "updated_at": self.updated_at,
            "status": self.status,
            "parent_id": self.parent_id,
            "branch_id": self.branch_id,
            "branch_summary": self.branch_summary,
            "model_override": self.model_override,
            "pinned": self.pinned,
            "channel": self.channel,
            "history_anchors": self.history_anchors,
            "history_anchor_scopes": self.history_anchor_scopes,
            "projection_guard": self.projection_guard,  # EVO-20260817-b6554376 投影门闸缓存行
            "fixed_summary": self.fixed_summary,        # 2026-08-21 追加式压缩: 核心固定摘要
            "summary_chain": self.summary_chain,        # 2026-08-21 追加式压缩: 增量摘要链
            "working_state_checkpoint": self.working_state_checkpoint,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "source": m.source.value,
                    "tool_call_id": m.tool_call_id,
                    "status": m.status.value if m.status else None,
                    "tool_name": m.tool_name,
                    "error_detail": m.error_detail,
                    "tool_calls": m.tool_calls,
                    "reasoning_content": m.reasoning_content,  # M20 THK-04: 思考链持久化同步
                    "ts": m.ts,  # 2026-08-17: 消息时间戳持久化（web 时间显示数据源）
                    "model_used": m.model_used,  # M51: 模型标签持久化（页脚数据源）
                    "tokens_in": m.tokens_in,  # M52: prompt tokens 持久化
                    "tokens_out": m.tokens_out,  # M52: completion tokens 持久化
                    "tokens_cache_hit": m.tokens_cache_hit,  # M58: 缓存命中持久化
                    "llm_ms": m.llm_ms,  # M59: LLM 耗时持久化
                    "ttft_ms": m.ttft_ms,  # M59: 首 token 延迟持久化
                    "duration_ms": m.duration_ms,  # M59: 工具耗时持久化
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
        }


def _message_from_dict(d: dict) -> Message:
    status_raw = d.get("status")
    status = None
    if status_raw:
        try:
            status = ToolResultStatus(status_raw)
        except ValueError:
            status = None
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        source=MessageSource(d.get("source", "user")),
        tool_call_id=d.get("tool_call_id"),
        status=status,
        tool_name=d.get("tool_name"),
        error_detail=d.get("error_detail"),
        tool_calls=d.get("tool_calls"),
        reasoning_content=d.get("reasoning_content"),  # M20 THK-04: 旧 JSON 无键 → None 向后兼容
        model_used=d.get("model_used", ""),  # M51: 旧 JSON 无键 → "" 向后兼容
        tokens_in=int(d.get("tokens_in") or 0),  # M52: 旧 JSON 无键 → 0
        tokens_out=int(d.get("tokens_out") or 0),  # M52
        tokens_cache_hit=int(d.get("tokens_cache_hit") or 0),  # M58: 旧 JSON 无键 → 0
        llm_ms=float(d.get("llm_ms") or 0.0),  # M59: 旧 JSON 无键 → 0
        ttft_ms=float(d.get("ttft_ms") or 0.0),  # M59
        duration_ms=float(d.get("duration_ms") or 0.0),  # M59
        ts=float(d.get("ts") or 0.0),  # 时间戳: 旧 JSON 无键 → 0（web 端时间显示兜底）
        metadata=d.get("metadata") or {},
    )


def _make_title(first_user_content: str) -> str:
    """默认标题: 首条用户消息前 30 字符（确定性规则，不调 LLM）."""
    text = first_user_content.strip()
    if not text:
        return ""
    return text[:30]


class SessionStore:
    """会话持久化（JSON 文件，P0 + P1 多会话方法）.

    D1 事件源化: 可选注入 `event_store`（默认 None 零行为）。注入时:
    - save() 内兜底（事件日志不存在则生成 session.created + 全部消息事件，防御层 fail-open）
    - rename/set_pinned/set_channel/archive/unarchive 挂 session.meta_changed
    """

    def __init__(
        self,
        sessions_dir: str | Path,
        *,
        event_store: Any | None = None,
        read_path_source: str = "session_json",
        identity_root: str | Path | None = None,
        identity_history_exists_fn: Callable[[str], bool] | None = None,
        delete_sidecars_fn: Callable[[str], object] | None = None,
    ) -> None:
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._identity_root_pinned = identity_root is not None
        self._identity_root = Path(identity_root) if identity_root is not None else self._dir
        self._identity_root.mkdir(parents=True, exist_ok=True)
        self._identity_verified: set[str] = set()
        self._identity_history_exists_fn = identity_history_exists_fn
        self._delete_sidecars_fn = delete_sidecars_fn
        self._event_store = event_store
        self._read_path_source = read_path_source
        # P0-4(2026-08-15): 非 POSIX 平台 flock 不可得时的进程内回退锁表
        self._fallback_locks: dict[str, threading.Lock] = {}
        self._fallback_run_gates: dict[str, _FallbackRunGate] = {}
        self._fallback_locks_guard = threading.Lock()
        # run 内 save 的显式所有权：仅绑定到本轮 load 出来的 Session 对象。
        # 不依赖 ContextVar（ASGI 生成器可跨 Context resume），也不会序列化到 JSON。
        self._run_save_tokens: dict[str, object] = {}
        self._run_save_tokens_guard = threading.Lock()

    @property
    def root(self) -> Path:
        """当前会话持久化根；workspace切换时原子更新。"""
        return self._dir

    def prepare_root(self, sessions_dir: str | Path) -> Path:
        """预创建/验证会话根；失败时不改变当前SessionStore状态。"""
        target = Path(sessions_dir)
        target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise OSError(f"会话根不可用: {target}")
        return target

    def activate_prepared_root(self, sessions_dir: str | Path) -> None:
        """激活已准备好的会话根；不执行文件系统I/O。"""
        self._dir = Path(sessions_dir)
        if not self._identity_root_pinned:
            self._identity_root = self._dir
        self._identity_verified.clear()
        self._fallback_locks.clear()
        self._fallback_run_gates.clear()
        self._fallback_locks_guard = threading.Lock()
        with self._run_save_tokens_guard:
            self._run_save_tokens.clear()

    def set_root(self, sessions_dir: str | Path) -> None:
        """切换会话根目录；先准备成功再原子更新内存根。"""
        target = self.prepare_root(sessions_dir)
        self.activate_prepared_root(target)

    @property
    def identity_root(self) -> Path:
        """跨workspace session_id 全局归属根（Event/Archive共享键空间）。"""
        return self._identity_root

    def _identity_owner_key(self) -> str:
        base = self._identity_root.resolve()
        current = self._dir.resolve()
        try:
            rel = current.relative_to(base)
        except ValueError as exc:
            raise SessionIdConflictError(
                f"当前会话根 {current} 越出 identity_root {base}，拒绝声明 session_id"
            ) from exc
        return "." if rel == Path(".") else rel.as_posix()

    def _identity_history_in_use(self, session_id: str) -> bool:
        """无session JSON时检查全局Event/Archive历史是否已占用该sid；探针异常fail-closed。"""
        try:
            if self._event_store is not None and self._event_store.exists(session_id):
                return True
            if self._identity_history_exists_fn is not None:
                return bool(self._identity_history_exists_fn(session_id))
            return False
        except Exception as exc:  # noqa: BLE001 — 无法证明未使用时禁止重新claim
            raise SessionIdConflictError(
                f"无法验证 session_id {session_id} 的历史全局占用，拒绝重新分配"
            ) from exc

    def _legacy_identity_owners(self, session_id: str) -> list[str]:
        """首次引入owner tombstone时从现有session JSON推断历史归属。"""
        session_id = _validate_session_id(session_id)
        base = self._identity_root.resolve()
        owners: list[str] = []
        base_file = base / f"{session_id}.json"
        if base_file.is_file():
            owners.append(".")
        try:
            children = list(base.iterdir())
        except OSError as exc:
            raise SessionIdConflictError(f"无法扫描session_id全局归属: {exc}") from exc
        for child in children:
            if child.name == ".identity":
                continue
            try:
                resolved = child.resolve()
                resolved.relative_to(base)
            except (OSError, ValueError):
                continue
            if not resolved.is_dir():
                continue
            if (resolved / f"{session_id}.json").is_file():
                owners.append(resolved.relative_to(base).as_posix())
        return sorted(set(owners))

    @contextmanager
    def _identity_lock(self, session_id: str) -> Iterator[None]:
        """跨workspace/跨进程稳定per-sid锁；owner claim不可fail-open。"""
        session_id = _validate_session_id(session_id)
        identity_dir = self._identity_root / ".identity"
        try:
            identity_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionIdConflictError(f"session_id归属锁目录不可用: {exc}") from exc
        lock_path = identity_dir / f"{session_id}.lock"
        try:
            import fcntl
        except ImportError:
            key = f"{self._identity_root.resolve()}::{session_id}"
            with _IDENTITY_FALLBACK_GUARD:
                lock = _IDENTITY_FALLBACK_LOCKS.setdefault(key, threading.Lock())
            with lock:
                yield
            return
        lock_file = None
        try:
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            raise SessionIdConflictError(f"session_id全局归属锁不可用: {exc}") from exc

        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("session_id全局归属锁释放失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()

    def _durable_replace_text(self, path: Path, content: str) -> None:
        """durable原子替换：文件fsync + rename + 父目录fsync；任一步失败均向上抛。"""
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        dir_fd: int | None = None
        try:
            with tmp.open("w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            try:
                dir_fd = os.open(path.parent, flags)
                os.fsync(dir_fd)
            except OSError as exc:
                # 目录fsync并非所有平台/文件系统可用；文件本体已fsync+replace，
                # 此处只降级崩溃耐久性，不能让明确支持的非POSIX fallback完全不可用。
                logger.warning(
                    "durable replace父目录fsync不可用（写入已完成，耐久性降级）: %s: %s",
                    path.parent,
                    exc,
                )
        finally:
            if dir_fd is not None:
                os.close(dir_fd)
            with suppress(OSError):
                tmp.unlink(missing_ok=True)

    def _check_identity_read(self, session_id: str) -> None:
        """只读验证现有全局归属；不存在于任何workspace的sid不得因读取被claim。"""
        session_id = _validate_session_id(session_id)
        if session_id in self._identity_verified:
            return
        with self._identity_lock(session_id):
            identity_dir = self._identity_root / ".identity"
            owner_path = identity_dir / f"{session_id}.json"
            current_owner = self._identity_owner_key()
            if owner_path.exists():
                try:
                    record = json.loads(owner_path.read_text(encoding="utf-8"))
                    owner = str(record["owner"])
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise SessionIdConflictError(
                        f"session_id {session_id} 的全局归属记录损坏，拒绝猜测"
                    ) from exc
                if record.get("deleted_at"):
                    raise SessionDeletedError(
                        f"session_id {session_id} 已删除且不可恢复/复用"
                    )
                if owner != current_owner:
                    raise SessionIdConflictError(
                        f"session_id {session_id} 已被其他工作区占用（owner={owner}）"
                    )
                self._identity_verified.add(session_id)
                return

            owners = self._legacy_identity_owners(session_id)
            if len(owners) > 1:
                raise SessionIdConflictError(
                    f"session_id {session_id} 已存在于多个历史工作区，拒绝继续读取"
                )
            if not owners:
                if self._identity_history_in_use(session_id):
                    raise SessionIdConflictError(
                        f"session_id {session_id} 存在历史Event/Archive但workspace归属不可确定"
                    )
                return  # 纯读取全局未使用sid：不claim，不产生owner副作用

            owner = owners[0]
            self._durable_replace_text(
                owner_path,
                json.dumps({"owner": owner, "claimed_at": _now()}, ensure_ascii=False),
            )
            if owner != current_owner:
                raise SessionIdConflictError(
                    f"session_id {session_id} 已被其他工作区占用（owner={owner}）"
                )
            self._identity_verified.add(session_id)

    def _ensure_identity_owner(self, session_id: str, *, allow_deleted: bool = False) -> None:
        """声明/验证session_id的稳定workspace归属；删除session也不释放全局ID。"""
        session_id = _validate_session_id(session_id)
        if session_id in self._identity_verified:
            return
        with self._identity_lock(session_id):
            identity_dir = self._identity_root / ".identity"
            owner_path = identity_dir / f"{session_id}.json"
            current_owner = self._identity_owner_key()
            if owner_path.exists():
                try:
                    record = json.loads(owner_path.read_text(encoding="utf-8"))
                    owner = str(record["owner"])
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise SessionIdConflictError(
                        f"session_id {session_id} 的全局归属记录损坏，拒绝猜测"
                    ) from exc
                if record.get("deleted_at"):
                    if allow_deleted and owner == current_owner:
                        self._identity_verified.discard(session_id)
                        return
                    raise SessionDeletedError(
                        f"session_id {session_id} 已删除且不可恢复/复用"
                    )
                if owner != current_owner:
                    raise SessionIdConflictError(
                        f"session_id {session_id} 已被其他工作区占用（owner={owner}）"
                    )
            else:
                owners = self._legacy_identity_owners(session_id)
                if len(owners) > 1:
                    raise SessionIdConflictError(
                        f"session_id {session_id} 已存在于多个历史工作区，拒绝继续写入"
                    )
                if not owners and self._identity_history_in_use(session_id):
                    raise SessionIdConflictError(
                        f"session_id {session_id} 存在历史Event/Archive但workspace归属不可确定"
                    )
                owner = owners[0] if owners else current_owner
                self._durable_replace_text(
                    owner_path,
                    json.dumps({"owner": owner, "claimed_at": _now()}, ensure_ascii=False),
                )
                if owner != current_owner:
                    raise SessionIdConflictError(
                        f"session_id {session_id} 已被其他工作区占用（owner={owner}）"
                    )
            self._identity_verified.add(session_id)

    def _mark_identity_deleted(self, session_id: str) -> None:
        """durable写删除tombstone；幂等，且删除后所有read/save/restore均fail-closed。"""
        session_id = _validate_session_id(session_id)
        self._identity_verified.discard(session_id)
        self._ensure_identity_owner(session_id, allow_deleted=True)
        with self._identity_lock(session_id):
            owner_path = self._identity_root / ".identity" / f"{session_id}.json"
            current_owner = self._identity_owner_key()
            try:
                record = json.loads(owner_path.read_text(encoding="utf-8"))
                owner = str(record["owner"])
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                raise SessionIdConflictError(
                    f"session_id {session_id} 的全局归属记录损坏，无法标记删除"
                ) from exc
            if owner != current_owner:
                raise SessionIdConflictError(
                    f"session_id {session_id} 已被其他工作区占用（owner={owner}）"
                )
            if not record.get("deleted_at"):
                record["deleted_at"] = _now()
                self._durable_replace_text(
                    owner_path, json.dumps(record, ensure_ascii=False)
                )
            self._identity_verified.discard(session_id)

    def claim_session_id(self, session_id: str) -> None:
        """显式声明新session的全局ID归属；供fork在写child EventStore前建立不变量。"""
        self._ensure_identity_owner(session_id)

    def restore_payload(
        self, session_id: str, payload: bytes | str, *, overwrite: bool = False
    ) -> None:
        """安全恢复原始session JSON：校验ID、全局claim、管理锁、原子替换。"""
        session_id = _validate_session_id(session_id)
        content = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("恢复session payload不是合法JSON") from exc
        payload_sid = str(data.get("session_id", session_id))
        if payload_sid != session_id:
            raise ValueError(
                f"恢复session payload id不匹配: {payload_sid!r} != {session_id!r}"
            )
        self._ensure_identity_owner(session_id)
        with self.management_lease(session_id), self._session_lock(session_id):
            p = self._path(session_id)
            if p.exists() and not overwrite:
                raise FileExistsError(f"正式位置已有会话: {session_id}")
            self._durable_replace_text(p, content)

    # ── P0-4(2026-08-15): 跨进程会话写锁（审计发现 #8 lost update 修复）──
    # Web 与飞书为独立进程共享同一 data/ 目录；load→modify→save 全程加 flock
    # （锁文件 <sid>.lock，对齐 EventStore 跨进程原子写约定）。锁文件不参与
    # 会话列表（list_sessions glob *.json 不匹配），delete 时一并清理。
    @contextmanager
    def _session_lock(self, session_id: str) -> Iterator[None]:
        """per-session 跨进程写锁（flock LOCK_EX；非 POSIX 回退进程内锁）.

        注意不可重入：同一线程对同一 sid 嵌套 acquire 会自死锁（flock 按
        打开文件描述符互斥）。持锁路径内部必须走 ``_save_locked``。
        """
        session_id = _validate_session_id(session_id)
        lock_path = self._dir / f"{session_id}.lock"
        try:
            import fcntl
        except ImportError:
            with self._fallback_locks_guard:
                lk = self._fallback_locks.setdefault(session_id, threading.Lock())
            with lk:
                yield
            return
        lock_file = None
        try:
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            # 锁文件不可写：如实记录后放行（不阻断主链路；并发保护降级）。
            logger.warning("会话锁不可用（fail-open，并发保护降级）: %s: %s", lock_path, exc)
            yield
            return
        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("会话锁释放失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()

    @contextmanager
    def run_lease(self, session_id: str) -> Iterator[bool]:
        """同会话 whole-run 跨进程非阻塞 lease（``<sid>.run.lock``）.

        与 ``_session_lock`` 使用独立锁文件：run 内部会多次 save/append 事件，若复用
        不可重入的写锁会自死锁。返回 True 表示本进程取得整轮所有权；False 表示
        已被其他进程占用或锁设施不可用。数据完整性优先，后者 fail-closed，调用方
        应映射为 session_busy 而不是无锁继续造成 last-writer-wins。
        """
        session_id = _validate_session_id(session_id)
        session_id = _validate_session_id(session_id)
        lock_path = self._dir / f"{session_id}.run.lock"
        try:
            import fcntl
        except ImportError:
            with self._fallback_locks_guard:
                gate = self._fallback_run_gates.setdefault(session_id, _FallbackRunGate())
            if not gate.acquire_exclusive():
                yield False
                return
            try:
                yield True
            finally:
                gate.release_exclusive()
            return

        try:
            with lock_path.open("a", encoding="utf-8") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        logger.warning("会话整轮锁获取失败（fail-closed）: %s: %s", lock_path, exc)
                    yield False
                    return
                try:
                    yield True
                finally:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except OSError as exc:
                        logger.warning("会话整轮锁释放失败: %s: %s", lock_path, exc)
        except OSError as exc:
            logger.warning("会话整轮锁文件不可用（fail-closed）: %s: %s", lock_path, exc)
            yield False

    def _activate_run_save_token(self, session_id: str) -> object:
        """为已取得 whole-run lease 的本轮创建 opaque save token。"""
        token = object()
        with self._run_save_tokens_guard:
            self._run_save_tokens[session_id] = token
        return token

    def _bind_run_save_token(self, session: Session, token: object) -> None:
        """把 token 绑定到本轮内存 Session；动态属性不参与 dataclass/asdict/to_dict。"""
        session.__dict__["_run_save_token"] = token

    def _deactivate_run_save_token(self, session_id: str, token: object) -> None:
        """run 结束后仅按 identity 注销，防迟到清理误删下一轮 token。"""
        with self._run_save_tokens_guard:
            if self._run_save_tokens.get(session_id) is token:
                self._run_save_tokens.pop(session_id, None)

    def _is_run_owned_session(self, session: Session) -> bool:
        token = getattr(session, "_run_save_token", None)
        if token is None:
            return False
        with self._run_save_tokens_guard:
            return self._run_save_tokens.get(session.session_id) is token

    @contextmanager
    def management_lease(self, session_id: str) -> Iterator[None]:
        """run 外管理事务共享门；多个管理写可并存，由 `_session_lock` 串行实际 RMW。

        POSIX 用 `<sid>.run.lock` 的 `LOCK_SH|LOCK_NB`：任一 whole-run 独占锁存在时
        立即报 busy；管理事务之间共享该门，因此不会把正常 append/rename 并发误判为
        run busy。真正 load→modify→write 仍由 `<sid>.lock` 的排他锁保证顺序一致。
        """
        session_id = _validate_session_id(session_id)
        lock_path = self._dir / f"{session_id}.run.lock"
        try:
            import fcntl
        except ImportError:
            with self._fallback_locks_guard:
                gate = self._fallback_run_gates.setdefault(session_id, _FallbackRunGate())
            if not gate.acquire_shared():
                raise SessionMutationBusyError(
                    f"会话 {session_id} 正在运行，管理操作已拒绝；请在本轮结束后重试"
                ) from None
            try:
                yield
            finally:
                gate.release_shared()
            return

        try:
            with lock_path.open("a", encoding="utf-8") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        logger.warning("会话管理门获取失败（fail-closed）: %s: %s", lock_path, exc)
                    raise SessionMutationBusyError(
                        f"会话 {session_id} 正在运行，管理操作已拒绝；请在本轮结束后重试"
                    ) from exc
                try:
                    yield
                finally:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except OSError as exc:
                        logger.warning("会话管理门释放失败: %s: %s", lock_path, exc)
        except SessionMutationBusyError:
            raise
        except OSError as exc:
            logger.warning("会话管理门锁文件不可用（fail-closed）: %s: %s", lock_path, exc)
            raise SessionMutationBusyError(
                f"会话 {session_id} 的并发保护不可用，管理操作已拒绝；请稍后重试"
            ) from exc

    @contextmanager
    def _shared_file_lock(self, name: str) -> Iterator[None]:
        """data/ 根级共享文件锁（如 shared_current_session；语义同 _session_lock）."""
        lock_path = self._dir.parent / f"{name}.lock"
        try:
            import fcntl
        except ImportError:
            with self._fallback_locks_guard:
                lk = self._fallback_locks.setdefault(name, threading.Lock())
            with lk:
                yield
            return
        try:
            with lock_path.open("a", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            logger.warning("共享文件锁不可用（fail-open）: %s: %s", lock_path, exc)
            yield

    def _event_append(self, session_id: str, event_type: str, payload: dict) -> None:
        """D1 事件写入（fail-open：未注入/禁用/异常均如实记录，不抛穿调用方）."""
        store = self._event_store
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            store.append(session_id, event_type, payload)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("事件写入失败（fail-open）: %s", exc)

    def _event_backfill(self, session: Session) -> None:
        """save 兜底（防御层）: 对比已落事件数与消息长度，缺失消息事件才补（tasks §7.3）.

        主事件路径在 engine 落库点；本兜底防御引擎遗漏点/手动改会话，
        保证事件日志与 session 最终一致（缺什么补什么，零重复开销）。
        - 事件日志不存在 → 生成 session.created + 全部消息事件
        - 已存在但消息事件数 < 消息长度（如迁移后引擎继续追加）→ 补缺失 index 的消息事件
        """
        store = self._event_store
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            if not store.exists(session.session_id):
                payload = {k: getattr(session, k, None) for k in _EVENT_TOP_FIELDS}
                payload["version"] = session.to_dict().get("version", 4)
                store.append(session.session_id, "session.created", payload)
                existing: set[int] = set()
            else:
                events = store.read(session.session_id)
                existing = {
                    e.payload.get("index")
                    for e in events
                    if e.type == "message.appended" and isinstance(e.payload.get("index"), int)
                }
                # version 5 摘要链是在 session.created 之后才产生/增长的。只补消息会让
                # event_log 读路径永远看到空摘要；用已有 meta_changed 事件表达完整当前值。
                from llm_loop.event_log.replay import replay_session

                view = replay_session(events)
                changes = {}
                for field_name in ("fixed_summary", "summary_chain", "working_state_checkpoint"):
                    current = getattr(session, field_name)
                    if field_name == "fixed_summary":
                        fallback = ""
                    elif field_name == "summary_chain":
                        fallback = []
                    else:
                        fallback = None
                    previous = view.get(field_name, fallback)
                    if previous != current:
                        changes[field_name] = {"from": previous, "to": current}
                if changes:
                    store.append(
                        session.session_id,
                        "session.meta_changed",
                        {"field": "summary_state", "changes": changes},
                    )
            for i, m in enumerate(session.messages):
                if i in existing:
                    continue  # 已落库消息事件跳过（零重复）
                store.append(
                    session.session_id,
                    "message.appended",
                    build_message_payload(
                        index=i,
                        role=m.role,
                        content=m.content,
                        source=m.source.value,
                        tool_call_id=m.tool_call_id,
                        status=m.status.value if m.status else None,
                        tool_name=m.tool_name,
                        error_detail=m.error_detail,
                        tool_calls=m.tool_calls,
                        reasoning_content=m.reasoning_content,
                        metadata=m.metadata,
                    ),
                )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("事件兜底写入失败（fail-open）: %s", exc)

    def create(self, model_override: str | None = None) -> str:
        """生成唯一 session_id 并初始化会话文件.

        model_override: 可选模型覆盖（M52）。/new·/clear 新建会话时传入当前会话的
        override，使新会话继承用户所选模型而非回落装配默认（M52-fix）。
        """
        sid = str(uuid.uuid4())
        session = Session(session_id=sid, model_override=model_override)
        self.save(session)
        return sid

    # ── 跨端共享当前会话（Web/飞书同一上下文）──
    # 工作区管理（2026-08-16）：共享文件按工作区分区（_dir 内），避免跨工作区互踩指针——
    # 否则 web 切工作区后 owner 跨端共享会反复失效/覆盖（各工作区独立"当前会话"）。
    _SHARED_SESSION_FILE = "shared_current_session.json"

    def get_shared_current(self) -> str | None:
        """读跨端共享当前会话（Web/飞书对称复用，fail-open）.

        Returns:
            共享当前 session_id（会话文件有效时）；无共享或会话已删返回 None。
        """
        p = self._dir / self._SHARED_SESSION_FILE
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sid = str(data.get("current", ""))
            if sid and self.exists(sid):
                return sid
        except (OSError, json.JSONDecodeError, ValueError) as exc:  # fail-open：读共享会话失败视为无
            logger.debug("读共享当前会话失败（fail-open）: %s", exc)
        return None

    def set_shared_current(self, session_id: str) -> None:
        """写跨端共享当前会话（原子写 + P0-4 跨进程文件锁，fail-open 不阻断主链路）."""
        session_id = _validate_session_id(session_id)
        p = self._dir / self._SHARED_SESSION_FILE
        try:
            with self._shared_file_lock("shared_current_session"):
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps({"current": session_id, "updated_at": _now()}, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(p)
        except OSError:
            pass  # fail-open（共享会话写入失败不阻断 Web/飞书主链路）

    def _path(self, session_id: str) -> Path:
        session_id = _validate_session_id(session_id)
        return self._dir / f"{session_id}.json"

    def save(self, session: Session) -> None:
        """保存会话；本轮显式 run-owned 快照复用独占 lease，其余写先取管理门。

        ASGI/生成器可能跨 ``contextvars.Context`` 驱动，因此不能用
        ``current_session_id`` 判断“是否 run 内”。LoopEngine 在取得 whole-run lease 后
        为本轮 load 出来的 Session 绑定 opaque token；只有该对象且 token 仍 active 时
        才可绕过 management shared gate。外部重新 load 的 Session 没有 token，仍会
        fail-fast，避免长 run 最终 save 覆盖并发管理写。
        """
        self._ensure_identity_owner(session.session_id)
        if self._is_run_owned_session(session):
            with self._session_lock(session.session_id):
                self._save_locked(session)
            return

        with self.management_lease(session.session_id), self._session_lock(session.session_id):
            self._save_locked(session)

    def _save_locked(self, session: Session) -> None:
        """save 的持锁内层（调用方必须已持有 _session_lock，否则并发保护不成立）."""
        checkpoint = session.working_state_checkpoint
        if isinstance(checkpoint, dict):
            boundary = checkpoint.get("boundary_message_count")
            try:
                boundary_count = int(boundary) if isinstance(boundary, int | str) else -1
            except ValueError:
                boundary_count = -1
            if boundary_count != len(session.messages):
                # S1 checkpoint is valid only for the exact transcript snapshot on
                # which selection occurred. Any later user/model/tool message makes
                # it mechanically stale; clear rather than carrying hidden old state.
                session.working_state_checkpoint = None
        session.updated_at = _now()
        if not session.title:
            first_user = next((m for m in session.messages if m.role == "user"), None)
            if first_user is not None:
                session.title = _make_title(first_user.content)
        # 原子写（tmp+rename）：Web/飞书跨进程共享会话时防半写损坏/交错覆盖
        p = self._path(session.session_id)
        try:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(p)
        except OSError as exc:
            # P0-4: 原子写失败回退直写（持锁内，无并发写者撕裂面；读者仍有瞬时窗口，
            # 如实 warning 不再静默——该路径现实不可达，仅跨设备 rename 等极端场景）
            logger.warning("会话原子写失败，回退直写（fail-open）: %s: %s", p, exc)
            p.write_text(
                json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        # D1 兜底（防御层）: 事件日志缺失时生成 session.created + 消息事件（fail-open）
        self._event_backfill(session)

    def rename(self, session_id: str, new_title: str) -> bool:
        """重命名会话标题；运行中会话 fail-fast，避免被 run 末旧快照覆盖。"""
        title = (new_title or "").strip()
        if not title or not self.exists(session_id):
            return False
        with self.management_lease(session_id):
            if not self.exists(session_id):
                return False
            with self._session_lock(session_id):
                session = self.load(session_id)
                old_title = session.title
                session.title = title
                self._save_locked(session)
            self._event_append(
                session_id,
                "session.meta_changed",
                {"field": "title", "changes": {"title": {"from": old_title, "to": title}}},
            )
        return True

    def load(self, session_id: str) -> Session:
        """加载会话；不存在则返回新会话（fail-open 恢复）.

        D1 后续批次 2：按 ``read_path_source`` 分派——
        ``session_json``（默认）读 session JSON（零回归）；
        ``event_log`` 从事件日志 replay 重建（退役后切换），replay 异常 fail-open 回退。
        """
        session_id = _validate_session_id(session_id)
        self._check_identity_read(session_id)
        if self._read_path_source == "event_log" and self._event_store is not None:
            session = self._load_from_event_log(session_id)
            if session is not None:
                return session
            logger.warning(
                "event_log 读路径 replay 失败，回退 session JSON（fail-open）: %s",
                session_id,
            )
        return self._load_from_json(session_id)

    def _load_from_event_log(self, session_id: str) -> Session | None:
        """从事件日志 replay 重建 Session（失败返回 None，由调用方回退）."""
        store = self._event_store
        if store is None or getattr(store, "enabled", False) is False:
            return None
        try:
            if not store.exists(session_id):
                return None
            events = store.read(session_id)
            if not events:
                return None
            from llm_loop.event_log.replay import replay_session

            view = replay_session(events)
            if not view or view.get("exists") is False:
                return None
            messages = [
                _message_from_dict(m) for m in view.get("messages", [])
            ]
            return Session(
                session_id=view.get("session_id", session_id),
                messages=messages,
                created_at=view.get("created_at", _now()),
                title=view.get("title", ""),
                updated_at=view.get("updated_at", _now()),
                status=view.get("status", _ACTIVE),
                parent_id=view.get("parent_id"),
                branch_id=view.get("branch_id", ""),
                branch_summary=view.get("branch_summary", ""),
                model_override=view.get("model_override"),
                pinned=bool(view.get("pinned", False)),
                channel=view.get("channel", "web"),
                # 2026-08-21 (追加式压缩, version 5): 摘要链缺省向后兼容
                fixed_summary=view.get("fixed_summary", ""),
                summary_chain=list(view.get("summary_chain") or []),
                working_state_checkpoint=(
                    dict(view["working_state_checkpoint"])
                    if isinstance(view.get("working_state_checkpoint"), dict)
                    else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("event_log replay 重建异常（fail-open）: %s: %s", session_id, exc)
            return None

    def _load_from_json(self, session_id: str) -> Session:
        """从 session JSON 加载会话（既有 load 逻辑，零回归）."""
        p = self._path(session_id)
        if not p.exists():
            return Session(session_id=session_id)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            messages = [_message_from_dict(m) for m in data.get("messages", [])]
            return Session(
                session_id=data.get("session_id", session_id),
                messages=messages,
                created_at=data.get("created_at", _now()),
                title=data.get("title", ""),  # version 1 缺省补默认（向后兼容）
                updated_at=data.get("updated_at", _now()),
                status=data.get("status", _ACTIVE),
                parent_id=data.get("parent_id"),  # version 3: 分支字段缺省向后兼容
                branch_id=data.get("branch_id", ""),
                branch_summary=data.get("branch_summary", ""),
                # M48: model_override 缺省向后兼容（旧 JSON 无键 → None）
                model_override=data.get("model_override"),
                # M56: pinned/channel 缺省向后兼容（旧 JSON 无键 → 默认值）
                pinned=bool(data.get("pinned", False)),
                channel=data.get("channel", "web"),
                # P1-10: history_anchors 缺省向后兼容（旧 JSON 无键 → {}）
                history_anchors=data.get("history_anchors") or {},
                # P4: legacy JSON 无 scope → 非零旧 anchor 在首次当前-contract build 重算。
                history_anchor_scopes=data.get("history_anchor_scopes") or {},
                # EVO-20260817-b6554376: projection_guard 缺省向后兼容（旧 JSON 无键 → {}）
                projection_guard=data.get("projection_guard") or {},
                # 2026-08-21 (追加式压缩, version 5): 摘要链缺省向后兼容（旧 JSON 无键 → 空）
                fixed_summary=data.get("fixed_summary", ""),
                summary_chain=list(data.get("summary_chain") or []),
                working_state_checkpoint=(
                    dict(data["working_state_checkpoint"])
                    if isinstance(data.get("working_state_checkpoint"), dict)
                    else None
                ),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            # 如实降级：文件损坏时备份原始文件（不覆盖丢数据），返回新会话（不伪造恢复）
            try:
                backup = p.with_suffix(".corrupt.json")
                backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass  # 备份失败尽力而为
            return Session(session_id=session_id)

    def append(self, session_id: str, message: Message, *, ingress: object | None = None) -> None:
        """追加消息；run 外 append 与 whole-run 互斥，避免长 run 覆盖追加内容。

        agent_trace_leak 2.3/3.6: user-role 消息先经恒等式校验与通道守卫
        （白名单外拒绝/降级 + 审计事件；guard 异常 fail-open；仅作用新写入，
        spec 4.5-1）。非 user-role 消息零影响；测试直调可传 issue_test_ingress()
        显式凭据（spec 5.3.3-4a 测试专用隔离标记）。
        """
        with self.management_lease(session_id), self._session_lock(session_id):
            session = self.load(session_id)
            if message.role == "user":
                message = self._leak_guard_and_invariant(session, message, ingress)
            session.messages.append(message)
            session.updated_at = _now()
            if not session.title and message.role == "user":
                session.title = _make_title(message.content)
            self._save_locked(session)

    def _leak_guard_and_invariant(
        self, session: Session, message: Message, ingress: object | None
    ) -> Message:
        """user 写入守卫 + 落盘恒等式校验（fail-open；异常放行 + 告警）."""
        session_id = session.session_id
        try:
            from llm_loop.core.trace_leak.user_ingress_guard import (
                GuardAction,
                guard_user_write,
            )

            verdict = guard_user_write(
                session, message, ingress, entry="SessionStore.append"
            )
            if verdict.action is GuardAction.DENY:
                # enforce 拒绝：不追加（事件与隔离记录已由 guard 留痕）
                raise _LeakWriteDeniedError(
                    f"user 写入被通道白名单拒绝（会话 {session_id}；"
                    "leak.channel_denied 事件已留痕）"
                )
            message = verdict.message
        except _LeakWriteDeniedError:
            raise
        except Exception:  # noqa: BLE001 — fail-open（spec 4.2-1）
            logging.getLogger(__name__).warning(
                "append 通道守卫异常（fail-open 放行）", exc_info=True
            )
        return self._leak_invariant_check(session_id, message)

    def _leak_invariant_check(self, session_id: str, message: Message) -> Message:
        """落盘恒等式校验（agent_trace_leak 2.3；异常 fail-open 放行 + 告警）."""
        try:
            from llm_loop.core.trace_leak import leak_events
            from llm_loop.core.trace_leak.invariant import (
                correct_mislabeled_metadata,
                metadata_satisfies_invariant,
            )

            if metadata_satisfies_invariant(message.metadata) is False:
                leak_events.emit_leak_event(
                    leak_events.LEAK_MISLABEL_DETECTED,
                    entry="SessionStore.append",
                    session_id=session_id,
                    content=message.content,
                    basis="恒等式违反: program_origin != (origin_layer != user_instruction)",

                )
                message.metadata = correct_mislabeled_metadata(message.metadata)
        except Exception:  # noqa: BLE001 — fail-open（spec 4.2-1）
            logging.getLogger(__name__).warning(
                "append 恒等式校验异常（fail-open 放行）", exc_info=True
            )
        return message

    # ── EVO-20260814: 会话瘦身（保留近期 + 早期摘要到压缩档案，可逆）──
    def trim_session(
        self,
        session_id: str,
        *,
        keep_recent: int = 200,
        archived_dir: str | Path | None = None,
    ) -> dict | None:
        """会话瘦身；与 whole-run lease 互斥，防运行中旧快照覆盖/备份漂移。"""
        if not self.exists(session_id):
            return None
        with self.management_lease(session_id):
            return self._trim_session_unleased(
                session_id, keep_recent=keep_recent, archived_dir=archived_dir
            )

    def _trim_session_unleased(
        self,
        session_id: str,
        *,
        keep_recent: int = 200,
        archived_dir: str | Path | None = None,
    ) -> dict | None:
        """会话瘦身：保留近期 N 条完整消息 + 早期消息摘要到压缩档案.

        设计原则（节 token 不损信息）:
        - keep_recent 范围内的消息完整保留（user/assistant/system/tool 全部）
        - 早期 user/assistant 消息：摘要保留（头 200 字符）
        - 早期 tool 消息：截断为 1 行摘要（"工具名: 状态" + 头 100 字符）
        - 原 session 备份到 archived_dir/<session_id>_<ts>.json（可逆）

        Returns: {"before", "after", "trimmed", "archived_to", "summary_path"}
        会话不存在 → None；已足够短 → 0 瘦身 noop.
        """
        if not self.exists(session_id):
            return None
        # P0-4: load→modify→save 整段持锁（单锁包全身，瘦身期间并发 append 不丢失）
        with self._session_lock(session_id):
            session = self.load(session_id)
            original_count = len(session.messages)
            if original_count <= keep_recent:
                return {"before": original_count, "after": original_count, "trimmed": 0,
                        "archived_to": None, "note": "已足够短，无需瘦身"}

            # 摘要时转 dict（保留原 Message 列表以便 save 序列化）
            msg_dicts = [asdict(m) for m in session.messages]
            keep = list(session.messages[-keep_recent:])  # 完整保留近期（Message 对象）
            early_messages = list(session.messages[:-keep_recent])
            early = list(msg_dicts[:-keep_recent])        # 早期用 dict 摘要

            # INJECTION-GOVERNANCE R5: legacy trim 的 summary JSONL 也是长期摘要面。
            # raw backup 仍保留完整消息；仅派生 summary 将所有 identity episodes 聚合
            # 为一条计数占位，避免模型身份/自我介绍压过主体任务。
            from llm_loop.core.identity_summary import (
                identity_episode_map,
                render_identity_summary_placeholder,
            )

            _identity_map = identity_episode_map(early_messages)
            _identity_starts = sorted(set(_identity_map.values()))
            _identity_first = _identity_starts[0] if _identity_starts else None

            def _summarize(m: dict) -> str:
                role = m.get("role", "")
                content = (m.get("content") or "").strip()
                ts = (m.get("metadata") or {}).get("ts", "")[:19]
                if role == "tool":
                    tname = m.get("tool_name") or "?"
                    return f"[{ts}] tool:{tname} | {content[:100]}"
                if role == "assistant":
                    return f"[{ts}] assistant: {content[:200]}"
                if role == "user":
                    return f"[{ts}] user: {content[:200]}"
                return f"[{role}] {content[:200]}"

            archive_root = Path(archived_dir) if archived_dir else (self._dir / "_trimmed")
            archive_root.mkdir(parents=True, exist_ok=True)
            ts_slug = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            backup_path = archive_root / f"{session_id}_{ts_slug}.json"
            backup_path.write_text(
                json.dumps(asdict(session), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary_path = archive_root / f"{session_id}_{ts_slug}_summary.jsonl"
            with summary_path.open("w", encoding="utf-8") as f:
                for _idx, _message in enumerate(early):
                    if _idx in _identity_map:
                        if _idx == _identity_first:
                            _summary = render_identity_summary_placeholder(len(_identity_starts))
                        else:
                            continue
                    else:
                        _summary = _summarize(_message)
                    f.write(
                        json.dumps({"ts": _now(), "content": _summary}, ensure_ascii=False)
                        + "\n"
                    )

            session.messages = list(keep)
            session.updated_at = _now()
            self._save_locked(session)

            return {
                "before": original_count,
                "after": len(keep),
                "trimmed": len(early),
                "archived_to": str(backup_path),
                "summary_path": str(summary_path),
            }

    def exists(self, session_id: str) -> bool:
        try:
            return self._path(session_id).exists()
        except ValueError:
            return False

    # ── P1 多会话方法（FR-P1-SES 系列）──
    def _to_meta(self, session: Session) -> SessionMeta:
        preview = session.messages[-1].content[:80] if session.messages else ""
        return SessionMeta(
            session_id=session.session_id,
            title=session.title or "未命名",
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
            status=session.status,
            last_message_preview=preview,
            # M56: pinned/channel 透传
            pinned=session.pinned,
            channel=session.channel,
        )

    def list_sessions(self, include_archived: bool = False) -> list[SessionMeta]:
        """列出全部会话元数据（M56: 置顶优先，再按 updated_at 降序；归档默认隐藏）."""
        return self._list_sessions_in(self._dir, include_archived=include_archived)

    def list_sessions_in(self, sessions_dir: str | Path, include_archived: bool = False) -> list[SessionMeta]:
        """按指定目录列出会话元数据（工作区管理：按工作区分区展示，不改变当前根）."""
        return self._list_sessions_in(Path(sessions_dir), include_archived=include_archived)

    def _list_sessions_in(self, target: Path, include_archived: bool = False) -> list[SessionMeta]:
        """list_sessions 实现体（目录参数化；M56 排序语义不变）.

        2026-09-07 CPU 修复：按 (mtime_ns, size) 缓存单文件解析结果——
        跨端同步每 1.5s 轮询一次 list_sessions，此前每轮全量 json.loads
        全部会话文件（275 个/108MB），持续占用 ~20% CPU。文件未变化时
        复用缓存元数据；mtime/size 变化即失效重解析（语义与全量解析一致，
        save 落盘必然更新 mtime）。本轮回收未出现文件对应条目，防删文件泄漏。
        """
        metas: list[SessionMeta] = []
        new_cache: dict[Path, tuple[tuple[int, int], SessionMeta]] = {}
        seen_paths: set[Path] = set()
        for p in sorted(target.glob("*.json")):
            if p.name == self._SHARED_SESSION_FILE:
                continue  # 工作区分区后共享会话文件在会话目录内，排除（非会话文件）
            seen_paths.add(p)
            try:
                st = p.stat()
                fkey = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            with _SESSION_META_CACHE_LOCK:
                cached = _SESSION_META_CACHE.get(p)
            if cached is not None and cached[0] == fkey:
                meta = cached[1]
                new_cache[p] = cached
            else:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                status = data.get("status", _ACTIVE)
                messages = data.get("messages", [])
                preview = messages[-1].get("content", "")[:80] if messages else ""
                meta = SessionMeta(
                    session_id=data.get("session_id", p.stem),
                    title=data.get("title") or "未命名",
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", data.get("created_at", "")),
                    message_count=len(messages),
                    status=status,
                    last_message_preview=preview,
                    # M56: pinned/channel 透传（缺省向后兼容）
                    pinned=bool(data.get("pinned", False)),
                    channel=data.get("channel", "web"),
                )
                new_cache[p] = (fkey, meta)
            if meta.status == _ARCHIVED and not include_archived:
                continue
            metas.append(meta)
        with _SESSION_META_CACHE_LOCK:
            for cached_path in list(_SESSION_META_CACHE):
                if cached_path.parent == target and cached_path not in seen_paths:
                    _SESSION_META_CACHE.pop(cached_path, None)
            _SESSION_META_CACHE.update(new_cache)
        # M56: 置顶会话优先（同置顶级别内保持 updated_at 降序；稳定排序保证相对序不变）
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        metas.sort(key=lambda m: not m.pinned)
        return metas

    def get_meta(self, session_id: str) -> SessionMeta | None:
        """单会话元数据；不存在返回 None（如实标注，不伪造）."""
        if not self.exists(session_id):
            return None
        return self._to_meta(self.load(session_id))

    # ── M56（Web/飞书会话同步）：置顶 + 来源通道 ──
    def set_pinned(self, session_id: str, pinned: bool) -> bool:
        """置顶/取消置顶；运行中会话拒绝管理写。"""
        if not self.exists(session_id):
            return False
        with self.management_lease(session_id):
            if not self.exists(session_id):
                return False
            with self._session_lock(session_id):
                session = self.load(session_id)
                old_pinned = session.pinned
                session.pinned = bool(pinned)
                self._save_locked(session)
            self._event_append(
                session_id,
                "session.meta_changed",
                {
                    "field": "pinned",
                    "changes": {"pinned": {"from": old_pinned, "to": bool(pinned)}},
                },
            )
        return True

    def set_channel(self, session_id: str, channel: str) -> bool:
        """标记会话来源通道；运行中会话拒绝覆盖元数据。"""
        if not self.exists(session_id):
            return False
        with self.management_lease(session_id):
            if not self.exists(session_id):
                return False
            with self._session_lock(session_id):
                session = self.load(session_id)
                if session.channel != "web" and session.channel:
                    return True
                old_channel = session.channel
                session.channel = channel or "web"
                self._save_locked(session)
            self._event_append(
                session_id,
                "session.meta_changed",
                {
                    "field": "channel",
                    "changes": {"channel": {"from": old_channel, "to": session.channel}},
                },
            )
        return True

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """按元数据标题 + 内容关键词检索会话（FR-P1-SES-06）.

        Returns:
            [{"meta": SessionMeta, "summary": 命中摘要, "location": 命中位置}]
        """
        from llm_loop.memory.retrieve import extract_keywords

        keywords = extract_keywords(query)
        hits: list[dict] = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            session = Session(
                session_id=data.get("session_id", p.stem),
                messages=[_message_from_dict(m) for m in data.get("messages", [])],
                created_at=data.get("created_at", _now()),
                title=data.get("title", ""),
                updated_at=data.get("updated_at", _now()),
                status=data.get("status", _ACTIVE),
                # M56: pinned/channel 缺省向后兼容
                pinned=bool(data.get("pinned", False)),
                channel=data.get("channel", "web"),
            )
            meta = self._to_meta(session)
            # 标题命中
            title_hit = query.lower() in (meta.title or "").lower()
            # 内容命中
            content_hit_loc = -1
            content_summary = ""
            for i, m in enumerate(session.messages):
                hay = f"{m.content} {m.tool_name or ''}".lower()
                if any(k in hay for k in keywords):
                    content_hit_loc = i
                    content_summary = m.content[:120]
                    break
            if title_hit or content_hit_loc >= 0:
                hits.append(
                    {
                        "meta": meta,
                        "summary": content_summary
                        if content_hit_loc >= 0
                        else (meta.title or "未命名"),
                        "location": "标题" if title_hit else f"消息#{content_hit_loc}",
                    }
                )
            if len(hits) >= top_k:
                break
        return hits

    def archive(self, session_id: str) -> bool:
        """归档会话；运行中会话拒绝管理写。"""
        if not self.exists(session_id):
            return False
        with self.management_lease(session_id):
            if not self.exists(session_id):
                return False
            with self._session_lock(session_id):
                session = self.load(session_id)
                old_status = session.status
                session.status = _ARCHIVED
                self._save_locked(session)
            self._event_append(
                session_id,
                "session.meta_changed",
                {
                    "field": "status",
                    "changes": {"status": {"from": old_status, "to": _ARCHIVED}},
                },
            )
        return True

    def unarchive(self, session_id: str) -> bool:
        """取消归档；运行中会话拒绝管理写。"""
        if not self.exists(session_id):
            return False
        with self.management_lease(session_id):
            if not self.exists(session_id):
                return False
            with self._session_lock(session_id):
                session = self.load(session_id)
                old_status = session.status
                session.status = _ACTIVE
                self._save_locked(session)
            self._event_append(
                session_id,
                "session.meta_changed",
                {
                    "field": "status",
                    "changes": {"status": {"from": old_status, "to": _ACTIVE}},
                },
            )
        return True

    def delete(self, session_id: str) -> bool:
        """物理删除主会话 + Event/Archive sidecar；任一清理失败不得误报成功。"""
        if not self.exists(session_id):
            return False
        with self.management_lease(session_id):
            p = self._path(session_id)
            if not p.exists():
                return False
            try:
                with self._session_lock(session_id):
                    # 先durable标记不可恢复；崩溃/部分清理后也绝不允许旧sid重新活跃。
                    self._mark_identity_deleted(session_id)
                    if self._delete_sidecars_fn is not None:
                        self._delete_sidecars_fn(session_id)
                    event_delete = getattr(self._event_store, "delete_session", None)
                    if callable(event_delete):
                        event_delete(session_id)
                    p.unlink()
                # owner tombstone与稳定lock/run.lock故意保留：旧sid不可跨workspace重新分配。
                return True
            except Exception:  # noqa: BLE001 — destructive cleanup失败必须如实返回false
                logger.exception("物理删除会话失败（可能已部分清理sidecar）: sid=%s", session_id)
                return False

    # ── EVO-20260810-3188682f: 会话分支 ──
    def create_branch(self, seed: BranchSeed) -> Session:
        """分支会话重建入口（R9-P3-03：Session 构造知识收归 SessionStore 侧）.

        自 fork.py:149-160 纯 move——构造字段序（seed 快照已求值）、fail-open
        try-except + logger.warning 语义原样；fork 侧只负责 BranchSeed 组装
        （design T4-C 切分线：数据生成 ↔ 持久化分界）。
        """
        branch = Session(
            session_id=seed.new_session_id,
            messages=seed.messages_prefix,
            created_at=seed.created_at,
            title=seed.title,
            parent_id=seed.parent_id,
            branch_id=seed.branch_id,
            branch_summary=seed.branch_summary,
            channel=seed.channel,
        )
        try:
            self.save(branch)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("fork session JSON 保存失败（fail-open）: %s", exc)
        return branch

    def fork(
        self,
        session_id: str,
        branch_point_index: int | None = None,
        branch_summary: str = "",
    ) -> str:
        """从稳定父快照分叉；父会话运行中时 fail-fast，避免分到旧持久化状态。"""
        from llm_loop.event_log.fork import fork_session

        if not self.exists(session_id):
            raise ValueError(f"源会话不存在: {session_id}")
        with self.management_lease(session_id):
            report = fork_session(
                self._event_store,
                self,
                session_id,
                fork_point=branch_point_index,
                branch_summary=branch_summary,
            )
        if not report.success:
            raise ValueError(report.error)
        return report.new_session_id

    @staticmethod
    def _default_branch_summary(parent: Session, branch_point_index: int) -> str:
        """分支摘要（确定性，不调 LLM）：分叉点后最近一条 assistant 消息前 200 字符."""
        for m in reversed(parent.messages[branch_point_index:]):
            if m.role == "assistant" and m.content:
                return m.content[:200]
        return ""

    def branches(self, session_id: str) -> list[SessionMeta]:
        """列出以 session_id 为父的全部分支会话元数据（不含父自身；按 updated_at 降序）.

        父会话自身可用 get_meta 查询；分支会话经 get_meta/fork 后可继续探索。
        """
        metas: list[SessionMeta] = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("parent_id") != session_id:
                continue
            messages = data.get("messages", [])
            preview = messages[-1].get("content", "")[:80] if messages else ""
            metas.append(
                SessionMeta(
                    session_id=data.get("session_id", p.stem),
                    title=data.get("title") or "未命名",
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", data.get("created_at", "")),
                    message_count=len(messages),
                    status=data.get("status", _ACTIVE),
                    last_message_preview=preview,
                )
            )
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        return metas
