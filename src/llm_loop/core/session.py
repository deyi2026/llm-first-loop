"""会话持久化 SessionStore（design.md §2.2.2.3 / P1 批次1 FR-P1-SES）.

- 唯一 session_id（UUID）；消息完整序列 JSON 落盘 data/sessions/<session_id>.json
- T24: SessionMeta + Session 元数据字段（title/updated_at/status，version 2 向后兼容）
- T25: 多会话方法 list_sessions/get_meta/search/archive/unarchive/delete
- 删除不销毁已沉淀记忆/压缩档案/审计（来源可溯仍指向 session_id）
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from llm_loop.core.message import Message, MessageSource, ToolResultStatus

_ACTIVE = "active"
_ARCHIVED = "archived"


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
        metadata=d.get("metadata") or {},
    )


def _make_title(first_user_content: str) -> str:
    """默认标题: 首条用户消息前 30 字符（确定性规则，不调 LLM）."""
    text = first_user_content.strip()
    if not text:
        return ""
    return text[:30]


class SessionStore:
    """会话持久化（JSON 文件，P0 + P1 多会话方法）."""

    def __init__(self, sessions_dir: str | Path) -> None:
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> str:
        """生成唯一 session_id 并初始化会话文件."""
        sid = str(uuid.uuid4())
        session = Session(session_id=sid)
        self.save(session)
        return sid

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def save(self, session: Session) -> None:
        """保存会话（统一维护 title/updated_at，覆盖 append/run/fork 全路径）.

        EVO-20260811（管理完善）: 此前仅 append() 更新 updated_at 与生成 title，
        LoopEngine.run 走 save() 导致会话列表"未命名 + 时间不更新"。现在保存即统一维护：
        - updated_at 每次保存更新为当前时间（列表排序/时间显示正确）
        - title 为空且有用户消息时补首条用户消息标题（幂等，不覆盖已有标题）
        """
        session.updated_at = _now()
        if not session.title:
            first_user = next((m for m in session.messages if m.role == "user"), None)
            if first_user is not None:
                session.title = _make_title(first_user.content)
        self._path(session.session_id).write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
        session = self.load(session_id)
        session.title = title
        self.save(session)
        return True

    def load(self, session_id: str) -> Session:
        """加载会话；不存在则返回新会话（fail-open 恢复）."""
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
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            # 如实降级：文件损坏时返回新会话（不伪造恢复）
            return Session(session_id=session_id)

    def append(self, session_id: str, message: Message) -> None:
        session = self.load(session_id)
        session.messages.append(message)
        session.updated_at = _now()
        # T24: 标题仅首条用户消息生成一次（确定性，不调 LLM）
        if not session.title and message.role == "user":
            session.title = _make_title(message.content)
        self.save(session)

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
        metas: list[SessionMeta] = []
        for p in sorted(self._dir.glob("*.json")):
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
        session = self.load(session_id)
        session.pinned = bool(pinned)
        self.save(session)
        return True

    def set_channel(self, session_id: str, channel: str) -> bool:
        """标记会话来源通道（"web" / "feishu:p2p:{open_id}" / "feishu:group:{chat_id}"）.

        幂等：已标记（非默认）则不覆盖，保留首建端来源。返回 False 表示会话不存在。
        """
        if not self.exists(session_id):
            return False
        session = self.load(session_id)
        if session.channel != "web" and session.channel:
            return True  # 已标记来源，不覆盖
        session.channel = channel or "web"
        self.save(session)
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
        session = self.load(session_id)
        session.status = _ARCHIVED
        self.save(session)
        return True

    def unarchive(self, session_id: str) -> bool:
        """取消归档（恢复活跃）."""
        if not self.exists(session_id):
            return False
        session = self.load(session_id)
        session.status = _ACTIVE
        self.save(session)
        return True

    def delete(self, session_id: str) -> bool:
        """物理删除会话 JSON 文件（须经用户确认，确认在 CLI 层 T26）.

        删除不销毁该会话已沉淀的记忆/压缩档案/审计（来源可溯仍指向 session_id）。
        """
        p = self._path(session_id)
        if not p.exists():
            return False
        try:
            p.unlink()
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
            branch_point_index: 分叉点（父会话消息索引；新分支仅保留此前消息，之后开始新探索）.
                缺省 = 父会话末尾（克隆当前状态开新分支）；传索引可从历史中间分叉.
            branch_summary: 显式分支摘要；缺省自动提炼（分叉点后最近一条 assistant 消息，
                即旧分支在分叉点后的结论，跨分支情报传递；确定性规则不调 LLM）.

        Returns:
            新分支会话 session_id.
        """
        parent = self.load(session_id)
        idx = len(parent.messages) if branch_point_index is None else branch_point_index
        idx = max(0, min(idx, len(parent.messages)))
        prefix = parent.messages[:idx]
        summary = branch_summary or self._default_branch_summary(parent, idx)
        new_id = str(uuid.uuid4())
        branch = Session(
            session_id=new_id,
            messages=list(prefix),
            created_at=_now(),
            title=(parent.title or "未命名") + "（分支）",
            parent_id=session_id,
            branch_id=str(uuid.uuid4())[:8],
            branch_summary=summary,
            # M56: 分支继承来源通道（置顶不继承，新分支默认不置顶）
            channel=parent.channel,
        )
        self.save(branch)
        return new_id

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
