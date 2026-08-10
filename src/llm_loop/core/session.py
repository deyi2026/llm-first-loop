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

    def to_dict(self) -> dict:
        return {
            "version": 2,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "title": self.title,
            "updated_at": self.updated_at,
            "status": self.status,
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
        self._path(session.session_id).write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
        )

    def list_sessions(self, include_archived: bool = False) -> list[SessionMeta]:
        """列出全部会话元数据（按 updated_at 降序；归档会话默认隐藏）."""
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
                )
            )
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        return metas

    def get_meta(self, session_id: str) -> SessionMeta | None:
        """单会话元数据；不存在返回 None（如实标注，不伪造）."""
        if not self.exists(session_id):
            return None
        return self._to_meta(self.load(session_id))

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
