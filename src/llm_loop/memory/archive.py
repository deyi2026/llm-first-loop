"""压缩档案 ArchiveStore（design.md T22: 另存提取替代截断）.

边界说明（M11）: 本模块负责压缩档案存取（JSONL + 确定性提取）;记忆条目存取（index.json）在 memory/store.py，二者存储对象与文件格式不同，不合并。

"截断不是目的"——上下文超长/工具结果超长时，将被丢弃的信息
**原文完整另存 + 关键事实/关键路径/摘要作为检索索引**（信息零丢失），
AI 可通过 search_archive 检索找回。

存储: JSONL `data/archives/<session_id>.jsonl`；
条目含 id/ts/role/source/tool_name/tool_call_id/status/key_facts/key_paths/
summary/chars/original。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PATH_TOKEN_RE = re.compile(r"[\w./\\\-]+\.\w{1,8}|[/\\][\w.\-]+(?:[/\\][\w.\-]+)*")
_URL_RE = re.compile(r"https?://\S+")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ArchiveEntry:
    """压缩档案条目（原文完整 + 检索索引）."""

    id: str
    ts: str
    role: str
    source: str
    content: str  # 原文（完整另存）
    summary: str = ""  # 摘要/头尾片段（检索索引）
    key_facts: list[str] = field(default_factory=list)  # 关键事实/要点
    key_paths: list[str] = field(default_factory=list)  # 关键路径/URL（检索索引）
    tool_name: str | None = None
    tool_call_id: str | None = None
    status: str | None = None
    chars: int = 0
    summary_source: str = "deterministic"  # T28: llm/deterministic/none（来源如实标注）
    embedding: list[float] | None = None  # T35: 可选语义向量（不可用仍可关键词命中）

    def to_dict(self) -> dict:
        return asdict(self)


def extract_key_info(
    text: str, max_facts: int = 5, head_tail: int = 300
) -> tuple[list[str], list[str], str]:
    """确定性提取关键信息（P0）: 路径/URL 作为关键路径；头尾片段作为摘要.

    P1 可扩展为 LLM 摘要（接口不变）。
    """
    # 关键路径: 文件路径 token + URL
    paths: list[str] = []
    seen: set[str] = set()
    for m in _PATH_TOKEN_RE.findall(text):
        tok = m.strip()
        if len(tok) >= 4 and tok not in seen:
            seen.add(tok)
            paths.append(tok)
    for m in _URL_RE.findall(text):
        if m not in seen:
            seen.add(m)
            paths.append(m)

    # 关键事实: 含动作/结果信号的行（P0 简单规则: 首行 + 含状态词的行）
    facts: list[str] = []
    signal_words = ("成功", "失败", "完成", "错误", "已", "结果", "返回", "错误", "异常")
    for line in text.splitlines():
        line = line.strip()
        if not line or line in facts:
            continue
        if len(line) <= 200 and any(w in line for w in signal_words):
            facts.append(line[:200])
        if len(facts) >= max_facts:
            break

    # 摘要: 头尾片段
    if len(text) <= head_tail * 2:
        summary = text
    else:
        summary = (
            f"{text[:head_tail]} …[中间省略 {len(text) - head_tail * 2} 字符]… {text[-head_tail:]}"
        )
    return facts, paths, summary


class ArchiveStore:
    """压缩档案存储（JSONL，P0）."""

    def __init__(self, archive_dir: str | Path) -> None:
        self._dir = Path(archive_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    def archive(
        self,
        session_id: str,
        *,
        role: str,
        source: str,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        status: str | None = None,
    ) -> ArchiveEntry:
        """另存一条消息/结果为压缩档案条目（原文完整 + 索引）."""
        facts, paths, summary = extract_key_info(content)
        entry = ArchiveEntry(
            id=f"ARC-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            ts=_now(),
            role=role,
            source=source,
            content=content,
            summary=summary,
            key_facts=facts,
            key_paths=paths,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            status=status,
            chars=len(content),
        )
        p = self._path(session_id)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return entry

    def search(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        *,
        role: str | None = None,
        tool_name: str | None = None,
    ) -> list[dict]:
        """按关键词检索压缩档案（匹配摘要+关键事实+关键路径+原文片段）.

        返回结构化命中（原文片段 + 时间 + 来源定位，可溯源）。
        """
        p = self._path(session_id)
        if not p.exists():
            return []
        q = query.lower()
        hits: list[dict] = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if role and entry.get("role") != role:
                    continue
                if tool_name and entry.get("tool_name") != tool_name:
                    continue
                hay = " ".join(
                    [
                        entry.get("content", ""),
                        entry.get("summary", ""),
                        " ".join(entry.get("key_facts", [])),
                        " ".join(entry.get("key_paths", [])),
                    ]
                ).lower()
                if q and q not in hay:
                    continue
                hits.append(
                    {
                        "id": entry.get("id"),
                        "ts": entry.get("ts"),
                        "role": entry.get("role"),
                        "source": entry.get("source"),
                        "tool_name": entry.get("tool_name"),
                        "tool_call_id": entry.get("tool_call_id"),
                        "status": entry.get("status"),
                        "chars": entry.get("chars"),
                        "summary": entry.get("summary", "")[:500],
                        "key_facts": entry.get("key_facts", [])[:5],
                        "key_paths": entry.get("key_paths", [])[:5],
                        "content_preview": entry.get("content", "")[:800],
                        "file": str(p),
                    }
                )
                if len(hits) >= limit:
                    break
        return hits

    def stats(self, session_id: str) -> dict:
        """压缩档案统计（供 architecture_status 展示）."""
        p = self._path(session_id)
        if not p.exists():
            return {"archived_count": 0, "archived_chars": 0}
        count = 0
        chars = 0
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    entry = json.loads(line)
                    chars += int(entry.get("chars", 0))
                except (json.JSONDecodeError, ValueError):
                    pass
        return {"archived_count": count, "archived_chars": chars}

    def update_summary(self, entry_id: str, summary: str, summary_source: str) -> bool:
        """按 id 回填摘要到档案条目（T28）.

        失败返回 False + 日志（fail-open，不影响已交付档案）。
        """
        p = self._path(self._entry_session(entry_id))
        if not p.exists():
            return False
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
            out: list[str] = []
            found = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    out.append(line)
                    continue
                if entry.get("id") == entry_id:
                    entry["summary"] = summary
                    entry["summary_source"] = summary_source
                    found = True
                out.append(json.dumps(entry, ensure_ascii=False))
            if found:
                p.write_text("\n".join(out) + "\n", encoding="utf-8")
            return found
        except OSError:
            return False

    def _entry_session(self, entry_id: str) -> str:
        """定位条目所属会话（线性扫描，档案量小可接受）."""
        for p in self._dir.glob("*.jsonl"):
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("id") == entry_id:
                        return p.stem
        return ""

    def cleanup(self, *, max_entries: int = 0, ttl_days: int = 0) -> dict:
        """R7: 清理过期/超量档案条目（启动时调用一次，防磁盘膨胀）.

        - max_entries > 0: 单会话档案超过 N 条时删除最旧的（保留最近 N 条）
        - ttl_days > 0: 超过 N 天的条目删除（按条目 ts 判断）
        - 两者都为 0: 空操作（零回归）
        - 单文件清理失败 fail-open（warning + 跳过），不阻断其他文件

        Returns:
            {"pruned_files": N, "pruned_entries": N}
        """
        if max_entries <= 0 and ttl_days <= 0:
            return {"pruned_files": 0, "pruned_entries": 0}

        import logging

        cutoff_ts = None
        if ttl_days > 0:
            cutoff_ts = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()
        total_pruned = 0
        pruned_files = 0

        for p in self._dir.glob("*.jsonl"):
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
                kept: list[str] = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        kept.append(line)  # 无法解析的条目保留（fail-open）
                        continue
                    if cutoff_ts is not None:
                        ts = entry.get("ts", "")
                        if ts and ts < cutoff_ts:
                            total_pruned += 1
                            continue
                    kept.append(line)
                if max_entries > 0 and len(kept) > max_entries:
                    total_pruned += len(kept) - max_entries
                    kept = kept[-max_entries:]
                if len(kept) < len(lines):
                    if kept:
                        p.write_text("\n".join(kept) + "\n", encoding="utf-8")
                    else:
                        p.unlink(missing_ok=True)  # 全部清理 → 删除空档案文件
                    pruned_files += 1
            except Exception as exc:  # noqa: BLE001 — 单文件清理失败 fail-open
                logging.getLogger(__name__).warning("档案 GC 失败（fail-open）: %s: %s", p, exc)
                continue

        return {"pruned_files": pruned_files, "pruned_entries": total_pruned}
