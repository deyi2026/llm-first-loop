"""记忆条目存取 MemoryStore（design.md §2.2.2.5 / FR-MEM 系列）.

边界说明（M11）: 本模块负责记忆条目（index.json）;压缩档案存取（JSONL）在 memory/archive.py，二者存储对象与文件格式不同，不合并。

JSON 文件存储（P0），条目含 id/type/content/keywords/source_session_id/
source_message_id/created_at（数据约束 6.3: 可检索、来源可溯）。
失败不阻塞主循环（FR-MEM-03），由调用方捕获并如实标注。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class MemoryEntry:
    """记忆条目（数据约束 6.3 / P1 字段扩展 §3.5.1）."""

    id: str
    type: str  # fact | decision | convention
    content: str
    keywords: list[str] = field(default_factory=list)
    source_session_id: str = ""
    source_message_id: str = ""
    created_at: str = ""
    summary: str = ""  # P1: 摘要（可选）
    summary_source: str = "deterministic"  # P1: llm/deterministic
    deposit_path: str = "inline"  # P1: inline（即时沉淀）/ extract（独立提取）
    content_fingerprint: str = ""  # P1: 内容规范化 SHA-256（去重）

    def to_dict(self) -> dict:
        return asdict(self)


class MemoryStore:
    """记忆条目存取（JSON 单文件索引，P0）."""

    def __init__(self, memory_dir: str | Path) -> None:
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"
        self._entries: list[MemoryEntry] = []
        self._load()

    def _load(self) -> None:
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                self._entries = [MemoryEntry(**e) for e in data]
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                # T39: 损坏如实记录（不静默降级），fail-open 继续
                import logging

                logging.getLogger(__name__).warning("记忆索引损坏，已重置为空索引（原因: %s）", exc)
                self._entries = []

    def _save(self) -> None:
        self._index_path.write_text(
            json.dumps([e.to_dict() for e in self._entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_entry(self, entry: MemoryEntry) -> MemoryEntry:
        if not entry.id:
            entry.id = f"MEM-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
        if not entry.created_at:
            entry.created_at = datetime.now(UTC).isoformat()
        self._entries.append(entry)
        self._save()
        return entry

    def search(self, keywords: list[str], top_k: int = 5) -> list[MemoryEntry]:
        """关键词检索（P0: 简单重叠匹配 + 条数上限）."""
        if not keywords:
            return []
        scored: list[tuple[int, MemoryEntry]] = []
        for e in self._entries:
            hay = " ".join([e.content, *e.keywords]).lower()
            score = sum(1 for k in keywords if k.lower() in hay)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], x[1].created_at))
        return [e for _, e in scored[:top_k]]

    def all(self) -> list[MemoryEntry]:
        return list(self._entries)

    def _by_id(self, entry_id: str) -> MemoryEntry | None:
        """按 id 取条目（语义检索融合用）."""
        for e in self._entries:
            if e.id == entry_id:
                return e
        return None

    def count(self) -> int:
        return len(self._entries)
