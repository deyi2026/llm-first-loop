"""记忆条目存取 MemoryStore（design.md §2.2.2.5 / FR-MEM 系列）.

边界说明（M11）: 本模块负责记忆条目（index.json）;压缩档案存取（JSONL）在 memory/archive.py，二者存储对象与文件格式不同，不合并。

JSON 文件存储（P0），条目含 id/type/content/keywords/source_session_id/
source_message_id/created_at（数据约束 6.3: 可检索、来源可溯）。
失败不阻塞主循环（FR-MEM-03），由调用方捕获并如实标注。

版本化与去重（EVO-20260811-cbd6c52a）: 同一事实更新时覆盖旧版而非追加，
保留 version/updated_at，旧版内容沉入 version_history（不删除业务数据），
注入排序按版本新鲜度。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class MemoryEntry:
    """记忆条目（数据约束 6.3 / P1 字段扩展 §3.5.1）."""

    id: str
    type: str  # fact | decision | convention | procedure
    content: str
    keywords: list[str] = field(default_factory=list)
    source_session_id: str = ""
    source_message_id: str = ""
    created_at: str = ""
    summary: str = ""  # P1: 摘要（可选）
    summary_source: str = "deterministic"  # P1: llm/deterministic
    deposit_path: str = "inline"  # P1: inline（即时沉淀）/ extract（独立提取）
    content_fingerprint: str = ""  # P1: 内容规范化 SHA-256（去重）
    # ── Phase 2 增强（EVO-20260810-baae4016）──
    access_count: int = 0            # 检索命中次数
    last_access_at: str = ""         # 最近访问时间 ISO（空=从未被检索）
    decay_score: float = 1.0         # 衰减分（1.0=最新最活跃；随未访问天数下降）
    # SkillZip ReZip 借鉴（执行感知反馈环）:
    # guidance_used_at: 最近一次被 M41 注入使用的时间（执行感知）
    # guidance_risk: 风险标记（注入后同场景仍失败累计，>=2 提示经验可能失效）
    guidance_used_at: str = ""
    guidance_risk: int = 0
    citations: list[dict] = field(default_factory=list)  # 溯源: [{"kind","ref","note"}]
    # ── 版本化与去重（EVO-20260811-cbd6c52a）──
    version: int = 1                 # 版本号（同事实更新 +1）
    updated_at: str = ""             # 最近更新时间 ISO（空=与 created_at 同）
    version_history: list[dict] = field(default_factory=list)  # 旧版沉淀: [{"version","content","updated_at"}]

    def to_dict(self) -> dict:
        return asdict(self)


_HALF_LIFE_DAYS = 30.0  # Phase 2: 衰减半衰期（decay = 0.5 ** (未访问天数/30)）


def _normalize_content(text: str) -> str:
    """内容规范化（用于指纹/同事实判定）: 去首尾空白、折叠空白、小写."""
    return re.sub(r"\s+", " ", text.strip()).lower()


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
                # T39: 损坏如实记录（不静默降级），备份原始文件（不覆盖丢数据），fail-open 继续
                import logging

                logging.getLogger(__name__).warning(
                    "记忆索引损坏，已备份并重置为空索引（原因: %s）", exc
                )
                try:
                    backup = self._index_path.with_suffix(".corrupt.json")
                    backup.write_text(
                        self._index_path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                except OSError:
                    pass  # 备份失败尽力而为
                self._entries = []

    def _save(self) -> None:
        # 原子写（tmp+rename）：Web/飞书跨进程共享记忆时防半写损坏/交错覆盖
        payload = json.dumps(
            [e.to_dict() for e in self._entries], ensure_ascii=False, indent=2
        )
        try:
            tmp = self._index_path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self._index_path)
        except OSError:
            # 原子写失败回退直写（fail-open，尽力而为）
            self._index_path.write_text(payload, encoding="utf-8")

    # ── 版本化与去重（EVO-20260811-cbd6c52a）──
    def _compute_fingerprint(self, entry: MemoryEntry) -> str:
        """规范化内容 SHA-256（空内容返回空串，不参与指纹匹配）."""
        norm = _normalize_content(entry.content)
        if not norm:
            return ""
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def _find_same_fact(self, entry: MemoryEntry) -> MemoryEntry | None:
        """查找"同事实"旧条目:
        - 强匹配: content_fingerprint 非空且相等（内容规范化后完全一致）
        - 弱匹配: type 相同 且 双方 keywords 均非空 且 交集 >= 1（同一主题更新）
        都不命中返回 None（视为新事实追加）。
        """
        fp = entry.content_fingerprint or self._compute_fingerprint(entry)
        new_keys = [str(k).lower() for k in entry.keywords]
        for e in self._entries:
            if fp and (e.content_fingerprint or self._compute_fingerprint(e)) == fp:
                return e
            # 弱匹配（同主题更新）: 交集>=1 且 交集包含任一方首标签。
            # 修复(2026-08-13): 原交集>=1 过弱，共享泛用词（如 adjust_strategy/基线）
            # 会误判跨主题条目为同事实并覆盖（借鉴 playbook 资产化时实证触发）。
            old_keys = [str(k).lower() for k in e.keywords]
            if e.type == entry.type and new_keys and old_keys:
                inter = set(new_keys) & set(old_keys)
                if inter and (new_keys[0] in inter or old_keys[0] in inter):
                    return e
        return None

    def _update_existing(self, existing: MemoryEntry, entry: MemoryEntry) -> MemoryEntry:
        """覆盖更新旧条目（保留 id/created_at/访问统计，版本 +1，旧版沉 version_history）."""
        now = datetime.now(UTC).isoformat()
        # 旧版沉淀（不删除业务数据）
        existing.version_history.append(
            {
                "version": existing.version,
                "content": existing.content,
                "updated_at": existing.updated_at or existing.created_at,
            }
        )
        existing.version += 1
        existing.content = entry.content
        existing.keywords = list(entry.keywords)
        existing.citations = entry.citations or existing.citations  # 溯源跟随新条目（修复残留旧来源）
        existing.summary = entry.summary or existing.summary
        existing.source_session_id = entry.source_session_id or existing.source_session_id
        existing.source_message_id = entry.source_message_id or existing.source_message_id
        existing.updated_at = now
        existing.content_fingerprint = entry.content_fingerprint or self._compute_fingerprint(entry)
        existing.decay_score = 1.0  # 更新即"最新"，衰减重置（访问统计保留）
        return existing

    def save_entry(self, entry: MemoryEntry) -> MemoryEntry:
        if not entry.id:
            entry.id = f"MEM-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
        if not entry.created_at:
            entry.created_at = datetime.now(UTC).isoformat()
        if not entry.content_fingerprint:
            entry.content_fingerprint = self._compute_fingerprint(entry)
        existing = self._find_same_fact(entry)
        if existing is not None:
            updated = self._update_existing(existing, entry)
            self._save()
            return updated
        entry.updated_at = entry.updated_at or entry.created_at
        self._entries.append(entry)
        self._save()
        return entry

    def search(self, keywords: list[str], top_k: int = 5) -> list[MemoryEntry]:
        """关键词检索 + 衰减排序（Phase 2）: 检索命中更新访问统计（内存），不即时全量落盘."""
        if not keywords:
            return []
        scored: list[tuple[float, MemoryEntry]] = []
        now = datetime.now(UTC).isoformat()
        for e in self._entries:
            hay = " ".join([e.content, *e.keywords]).lower()
            score = sum(1 for k in keywords if k.lower() in hay)
            if score > 0:
                # 命中 → 先基于"上次访问时间"算当前衰减分（体现久未访问降权），再刷新访问时间（命中即强化）
                e.decay_score = self._compute_decay(e)
                e.access_count += 1
                e.last_access_at = now
                scored.append((score, e))
        # 排序: 关键词分降序 → decay_score 降序 → 版本新鲜度（updated_at/created_at）降序
        scored.sort(
            key=lambda x: (
                x[0],
                x[1].decay_score,
                x[1].updated_at or x[1].created_at,
            ),
            reverse=True,
        )
        return [e for _, e in scored[:top_k]]

    @staticmethod
    def _compute_decay(entry: MemoryEntry) -> float:
        """衰减分: 1.0 * 0.5**(未访问天数/半衰期)；无访问记录视为 1.0."""
        if not entry.last_access_at:
            return 1.0
        try:
            last = datetime.fromisoformat(entry.last_access_at)
            days = (datetime.now(UTC) - last).total_seconds() / 86400.0
            return round(1.0 * (0.5 ** max(0.0, days / _HALF_LIFE_DAYS)), 4)
        except (ValueError, TypeError):
            return 1.0

    def flush(self) -> None:
        """强制落盘（供调用方在合适时机批量持久化，避免每轮检索全量写 JSON）."""
        self._save()

    def cleanup(self, *, max_entries: int = 0) -> dict:
        """P1-5: 记忆条数上限保护（启动时调用一次，超限淘汰 decay_score 最低的条目）.

        max_entries<=0 空操作（零回归）；淘汰后落盘。
        Returns: {"pruned": N}
        """
        if max_entries <= 0 or len(self._entries) <= max_entries:
            return {"pruned": 0}
        excess = len(self._entries) - max_entries
        sorted_entries = sorted(
            self._entries,
            key=lambda e: (e.decay_score, e.last_access_at or ""),
        )
        doomed = {id(e) for e in sorted_entries[:excess]}
        self._entries = [e for e in self._entries if id(e) not in doomed]
        self._save()
        return {"pruned": excess}

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
