"""会话持久化 SessionStore（design.md §2.2.2.3 / P1 批次1 FR-P1-SES）.

- 唯一 session_id（UUID）；消息完整序列 JSON 落盘 data/sessions/<session_id>.json
- T24: SessionMeta + Session 元数据字段（title/updated_at/status，version 2 向后兼容）
- T25: 多会话方法 list_sessions/get_meta/search/archive/unarchive/delete
- 删除不销毁已沉淀记忆/压缩档案/审计（来源可溯仍指向 session_id）
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.event_log.model import build_message_payload

logger = logging.getLogger(__name__)

_ACTIVE = "active"
_ARCHIVED = "archived"

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

    def to_dict(self) -> dict:
        return {
            "version": 4,
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
                    "model_used": m.model_used,  # M51: 模型标签持久化（页脚数据源）
                    "tokens_in": m.tokens_in,  # M52: prompt tokens 持久化
                    "tokens_out": m.tokens_out,  # M52: completion tokens 持久化
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
    ) -> None:
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._event_store = event_store
        self._read_path_source = read_path_source
        # P0-4(2026-08-15): 非 POSIX 平台 flock 不可得时的进程内回退锁表
        self._fallback_locks: dict[str, threading.Lock] = {}

    def set_root(self, sessions_dir: str | Path) -> None:
        """切换会话根目录（工作区管理：按工作区分区隔离；锁表随目录重建）."""
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fallback_locks.clear()
        self._fallback_locks_guard = threading.Lock()

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
        lock_path = self._dir / f"{session_id}.lock"
        try:
            import fcntl
        except ImportError:
            with self._fallback_locks_guard:
                lk = self._fallback_locks.setdefault(session_id, threading.Lock())
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
            # 锁文件不可写：如实记录后放行（不阻断主链路；并发保护降级如实标注）
            logger.warning("会话锁不可用（fail-open，并发保护降级）: %s: %s", lock_path, exc)
            yield

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
                existing = {
                    e.payload.get("index")
                    for e in store.read(session.session_id)
                    if e.type == "message.appended" and isinstance(e.payload.get("index"), int)
                }
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
        return self._dir / f"{session_id}.json"

    def save(self, session: Session) -> None:
        """保存会话（统一维护 title/updated_at，覆盖 append/run/fork 全路径）.

        EVO-20260811（管理完善）: 此前仅 append() 更新 updated_at 与生成 title，
        LoopEngine.run 走 save() 导致会话列表"未命名 + 时间不更新"。现在保存即统一维护：
        - updated_at 每次保存更新为当前时间（列表排序/时间显示正确）
        - title 为空且有用户消息时补首条用户消息标题（幂等，不覆盖已有标题）

        P0-4(2026-08-15): 写阶段持会话锁（与 append/rename 等持锁路径互斥）。
        如实标注：本方法只保护"写"这一瞬——调用方若在锁外先 load 再 save
        （如 engine 长 run 持有内存态整轮），跨进程 lost update 残差仍在；
        完整防护须走 append/rename 等持锁的 load→modify→save 整段路径。
        """
        with self._session_lock(session.session_id):
            self._save_locked(session)

    def _save_locked(self, session: Session) -> None:
        """save 的持锁内层（调用方必须已持有 _session_lock，否则并发保护不成立）."""
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
        """重命名会话标题（管理完善：手动设置可识别标题）.

        Returns:
            True 成功；False 会话不存在或新标题为空。
        """
        if not self.exists(session_id):
            return False
        title = (new_title or "").strip()
        if not title:
            return False
        # P0-4: load→modify→save 整段持锁
        with self._session_lock(session_id):
            session = self.load(session_id)
            old_title = session.title
            session.title = title
            self._save_locked(session)
        self._event_append(
            session_id,
            "session.meta_changed",
            {
                "field": "title",
                "changes": {"title": {"from": old_title, "to": title}},
            },
        )
        return True

    def load(self, session_id: str) -> Session:
        """加载会话；不存在则返回新会话（fail-open 恢复）.

        D1 后续批次 2：按 ``read_path_source`` 分派——
        ``session_json``（默认）读 session JSON（零回归）；
        ``event_log`` 从事件日志 replay 重建（退役后切换），replay 异常 fail-open 回退。
        """
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
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            # 如实降级：文件损坏时备份原始文件（不覆盖丢数据），返回新会话（不伪造恢复）
            try:
                backup = p.with_suffix(".corrupt.json")
                backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass  # 备份失败尽力而为
            return Session(session_id=session_id)

    def append(self, session_id: str, message: Message) -> None:
        # P0-4: load→modify→save 整段持锁（跨进程 lost update 防护）
        with self._session_lock(session_id):
            session = self.load(session_id)
            session.messages.append(message)
            session.updated_at = _now()
            # T24: 标题仅首条用户消息生成一次（确定性，不调 LLM）
            if not session.title and message.role == "user":
                session.title = _make_title(message.content)
            self._save_locked(session)
    # ── EVO-20260814: 会话瘦身（保留近期 + 早期摘要到压缩档案，可逆）──
    def trim_session(
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
            early = list(msg_dicts[:-keep_recent])        # 早期用 dict 摘要

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
                for s in [_summarize(m) for m in early]:
                    f.write(json.dumps({"ts": _now(), "content": s}, ensure_ascii=False) + "\n")

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
        return self._path(session_id).exists()

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
        """list_sessions 实现体（目录参数化；M56 排序语义不变）."""
        metas: list[SessionMeta] = []
        for p in sorted(target.glob("*.json")):
            if p.name == self._SHARED_SESSION_FILE:
                continue  # 工作区分区后共享会话文件在会话目录内，排除（非会话文件）
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            status = data.get("status", _ACTIVE)
            if status == _ARCHIVED and not include_archived:
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
                    status=status,
                    last_message_preview=preview,
                    # M56: pinned/channel 透传（缺省向后兼容）
                    pinned=bool(data.get("pinned", False)),
                    channel=data.get("channel", "web"),
                )
            )
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
        """置顶/取消置顶会话（Web 端会话列表置顶优先）.

        Returns:
            True 成功；False 会话不存在。
        """
        if not self.exists(session_id):
            return False
        # P0-4: load→modify→save 整段持锁
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
        """标记会话来源通道（"web" / "feishu:p2p:{open_id}" / "feishu:group:{chat_id}"）.

        幂等：已标记（非默认）则不覆盖，保留首建端来源。返回 False 表示会话不存在。
        """
        if not self.exists(session_id):
            return False
        # P0-4: load→modify→save 整段持锁（幂等判定也须读到最新值）
        with self._session_lock(session_id):
            session = self.load(session_id)
            if session.channel != "web" and session.channel:
                return True  # 已标记来源，不覆盖
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
        """归档会话（仅改状态，内容完整保留可检索）."""
        if not self.exists(session_id):
            return False
        # P0-4: load→modify→save 整段持锁
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
        """取消归档（恢复活跃）."""
        if not self.exists(session_id):
            return False
        # P0-4: load→modify→save 整段持锁
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
        """物理删除会话 JSON 文件（须经用户确认，确认在 CLI 层 T26）.

        删除不销毁该会话已沉淀的记忆/压缩档案/审计（来源可溯仍指向 session_id）。
        P0-4: 持锁删除（防与进行中写竞态），并清理配套锁文件。
        """
        p = self._path(session_id)
        if not p.exists():
            return False
        try:
            with self._session_lock(session_id):
                p.unlink()
            # 锁文件随会话删除清理（ best-effort；锁竞争方持有的是已 unlink 的旧 fd，
            # 后续 acquire 会新建锁文件——与 EventStore 目录级语义一致的已知残差）
            (self._dir / f"{session_id}.lock").unlink(missing_ok=True)
            return True
        except OSError:
            return False

    # ── EVO-20260810-3188682f: 会话分支 ──
    def fork(
        self,
        session_id: str,
        branch_point_index: int | None = None,
        branch_summary: str = "",
    ) -> str:
        """从指定会话分叉出新分支会话（旧会话不覆盖不删除，可回溯）.

        Args:
            session_id: 父会话 id.
            branch_point_index: 分叉点（保留前 N 条消息，即 messages[:N]；None=末尾全部）.
            branch_summary: 显式分支摘要；缺省自动提炼.

        Returns:
            新分支会话 session_id.

        Raises:
            ValueError: fork 点越界或源会话事件日志不存在（spec §5.1.3，从"钳位"改为"报错"）.
        """
        from llm_loop.event_log.fork import fork_session

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
