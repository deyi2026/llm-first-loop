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
import logging
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
    reasoning_content: str | None = None  # P0-2: 思考链完整另存（随压缩归档，检索域含）

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
    """压缩档案存储（JSONL 分片 + sidecar 检索索引，T3b/T3c）.

    单会话条目存 `data/archives/<session_id>.jsonl`；单文件达到 segment_bytes
    阈值后开新段 `<session_id>-<seq>.jsonl`（seq 递增，旧文件视为 seq 0 兼容）。
    读路径按段遍历（最近段优先），旧单文件零迁移兼容。

    T3c sidecar 索引：每段伴随 `<segment>.idx` 追加写（id/ts/chars/summary/key_facts/
    key_paths/content_head/tool_call_id/offset），检索走"索引快速通道 + 全文补齐"
    （limit 截断语义等价）；存量段无索引 → 全文扫描 fail-open。
    """

    _CONTENT_HEAD_CHARS = 800  # 索引 content_head 截断（对齐 search content_preview 口径）

    def __init__(
        self, archive_dir: str | Path, *, segment_bytes: int = 100 * 1024 * 1024
    ) -> None:
        self._dir = Path(archive_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._segment_bytes = segment_bytes  # T3b: 单文件分片阈值（0=不分片，兼容旧行为）

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    @staticmethod
    def _index_path(segment: Path) -> Path:
        """段文件 → sidecar 索引路径（`<segment>.idx`）."""
        return Path(str(segment) + ".idx")

    # ── T3b 分片：段解析/枚举/追加目标 ──

    @staticmethod
    def _segment_seq(path: Path) -> tuple[str, int]:
        """解析段文件 → (session_id, seq)：`<sid>.jsonl` = seq 0；`<sid>-N.jsonl` = seq N."""
        stem = path.stem
        dash = stem.rfind("-")
        if dash > 0 and stem[dash + 1 :].isdigit():
            return stem[:dash], int(stem[dash + 1 :])
        return stem, 0

    def _segment_paths(self, session_id: str) -> list[Path]:
        """枚举会话全部段文件（seq 升序；主文件 <sid>.jsonl 在前，兼容旧存储）."""
        segs = list(self._dir.glob(f"{session_id}*.jsonl"))
        segs.sort(key=lambda p: self._segment_seq(p)[1])
        return segs

    def _append_path(self, session_id: str) -> Path:
        """追加目标段：最后一段超阈值（>0 时）→ 开新段；否则沿用最后一段."""
        segs = self._segment_paths(session_id)
        if segs:
            last = segs[-1]
            if self._segment_bytes > 0 and last.stat().st_size >= self._segment_bytes:
                last_seq = self._segment_seq(last)[1]
                return self._dir / f"{session_id}-{last_seq + 1}.jsonl"
            return last
        return self._path(session_id)

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
        reasoning_content: str | None = None,  # P0-2: 思考链完整另存
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
            reasoning_content=reasoning_content,
        )
        p = self._append_path(session_id)  # T3b: 超阈值开新段
        # T3c: 二进制追加取字节偏移（sidecar 索引定位用），UTF-8 无 BOM 下偏移稳定
        line_bytes = (json.dumps(entry.to_dict(), ensure_ascii=False) + "\n").encode("utf-8")
        with p.open("ab") as f:
            offset = f.tell()
            f.write(line_bytes)
        self._index_append(p, offset, entry)
        return entry

    # ── T3c sidecar 索引：写入/读取 ──

    def _index_append(self, segment: Path, offset: int, entry: ArchiveEntry) -> None:
        """索引追加写（fail-open：索引失败不影响档案原文与主流程）."""
        idx = self._index_path(segment)
        try:
            rec = {
                "id": entry.id,
                "ts": entry.ts,
                "chars": entry.chars,
                "summary": entry.summary,
                "key_facts": entry.key_facts,
                "key_paths": entry.key_paths,
                "content_head": entry.content[: self._CONTENT_HEAD_CHARS],
                "tool_call_id": entry.tool_call_id,
                "tool_name": entry.tool_name,
                "role": entry.role,
                "offset": offset,
            }
            with idx.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            logger = logging.getLogger(__name__)
            logger.warning("档案索引写失败（fail-open，检索回退全文扫描）: %s", idx)

    def rebuild_segment_index(self, segment: Path) -> int:
        """R3(2026-08-14): 为单个段文件重建 sidecar 索引（存量段补索引）.

        扫描段内每行，按与 _index_append 一致的 rec 格式写出索引（覆盖式重建，幂等）。
        损坏行跳过（fail-open）；返回成功索引的条目数。
        """
        idx = self._index_path(segment)
        count = 0
        try:
            lines_out: list[str] = []
            offset = 0
            with segment.open("rb") as f:
                while True:
                    raw = f.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            offset += len(raw)
                            continue  # 损坏行跳过（fail-open）
                        rec = {
                            "id": entry.get("id", ""),
                            "ts": entry.get("ts", ""),
                            "chars": entry.get("chars", 0),
                            "summary": entry.get("summary", ""),
                            "key_facts": entry.get("key_facts", []),
                            "key_paths": entry.get("key_paths", []),
                            "content_head": (entry.get("content") or "")[: self._CONTENT_HEAD_CHARS],
                            "tool_call_id": entry.get("tool_call_id"),
                            "tool_name": entry.get("tool_name"),
                            "role": entry.get("role", ""),
                            "offset": offset,
                        }
                        lines_out.append(json.dumps(rec, ensure_ascii=False))
                        count += 1
                    offset += len(raw)
            idx.write_text("\n".join(lines_out) + ("\n" if lines_out else ""), encoding="utf-8")
        except OSError:
            logger = logging.getLogger(__name__)
            logger.warning("档案索引重建失败（fail-open）: %s", segment)
            return 0
        return count

    def rebuild_all_indexes(self) -> dict:
        """R3: 遍历全部段文件重建索引（存量段补 sidecar；幂等可重复执行）.

        Returns: {"segments": N, "entries": M, "failed": K}
        """
        total_segments = 0
        total_entries = 0
        failed = 0
        for p in sorted(self._dir.glob("*.jsonl")):
            total_segments += 1
            try:
                total_entries += self.rebuild_segment_index(p)
            except Exception:  # noqa: BLE001 — 单段失败 fail-open 继续
                failed += 1
        return {"segments": total_segments, "entries": total_entries, "failed": failed}

    def _line_at(self, segment: Path, offset: int) -> str | None:
        """按字节偏移读取段文件一行（fail-open：越界/损坏返回 None）."""
        try:
            with segment.open("rb") as f:
                f.seek(offset)
                raw = f.readline()
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

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
        分片后按段倒序遍历（最近段先，limit 命中即停，不读更旧段）。

        T3c 快速通道：段有 sidecar 索引时先走索引预筛（summary/key_facts/key_paths/
        content_head 子串匹配）→ 命中行按偏移读全文确认；索引未达 limit 时
        全文补齐该段（保证 content 尾部命中/索引缺失条目不漏），索引缺失/损坏
        直接全文扫描（fail-open）。最终判定始终在全文，limit 截断语义等价。
        """
        segs = self._segment_paths(session_id)
        if not segs:
            return []
        q = query.lower()
        hits: list[dict] = []
        seen_ids: set[str] = set()
        for p in reversed(segs):  # T3b: 最近段优先
            idx = self._index_path(p)
            if idx.exists():
                # 快速通道：索引预筛（含 role/tool_name 过滤）
                for offset, _rec in self._index_scan(idx, q, role, tool_name):
                    line = self._line_at(p, offset)
                    if line is None:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eid = entry.get("id", "")
                    if eid in seen_ids:
                        continue
                    if self._entry_matches(entry, q, role, tool_name):
                        seen_ids.add(eid)
                        hits.append(self._hit_dict(entry, p))
                        if len(hits) >= limit:
                            return hits
                # 补齐：全文扫描该段（跳过已确认 id，保证索引盲区不漏）
                if len(hits) < limit:
                    self._scan_segment(p, q, role, tool_name, limit, seen_ids, hits)
                    if len(hits) >= limit:
                        return hits
            else:
                # 无索引（存量段）→ 全文扫描（fail-open 兼容）
                self._scan_segment(p, q, role, tool_name, limit, seen_ids, hits)
                if len(hits) >= limit:
                    return hits
        return hits

    # ── T3c 检索辅助 ──

    def _index_scan(self, idx: Path, q: str, role: str | None, tool_name: str | None) -> list:
        """索引预筛（子串匹配 summary/key_facts/key_paths/content_head）→ [(offset, rec)]."""
        out: list[tuple[int, dict]] = []
        try:
            with idx.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 索引损坏行跳过（全文补齐兜底）
                    if role and rec.get("role") != role:
                        continue
                    if tool_name and rec.get("tool_name") != tool_name:
                        continue
                    hay = " ".join(
                        [
                            rec.get("summary", ""),
                            " ".join(rec.get("key_facts", [])),
                            " ".join(rec.get("key_paths", [])),
                            rec.get("content_head", ""),
                        ]
                    ).lower()
                    if q and q not in hay:
                        continue
                    out.append((rec.get("offset", 0), rec))
        except OSError:
            return []  # 索引读失败 → 全文补齐兜底
        return out

    @staticmethod
    def _entry_matches(entry: dict, q: str, role: str | None, tool_name: str | None) -> bool:
        """全文匹配判定（与旧实现逐字一致，含思考链检索域）."""
        if role and entry.get("role") != role:
            return False
        if tool_name and entry.get("tool_name") != tool_name:
            return False
        if not q:
            return True
        hay = " ".join(
            [
                entry.get("content", ""),
                entry.get("summary", ""),
                " ".join(entry.get("key_facts", [])),
                " ".join(entry.get("key_paths", [])),
                entry.get("reasoning_content", "") or "",  # P0-2: 思考链可检索
            ]
        ).lower()
        return q in hay

    @staticmethod
    def _hit_dict(entry: dict, p: Path) -> dict:
        """命中结果构造（与旧实现逐字一致）."""
        return {
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

    def _scan_segment(
        self,
        p: Path,
        q: str,
        role: str | None,
        tool_name: str | None,
        limit: int,
        seen_ids: set[str],
        hits: list[dict],
    ) -> None:
        """全文扫描一段（跳过已确认 id，命中达 limit 即停）."""
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eid = entry.get("id", "")
                    if eid in seen_ids:
                        continue
                    if self._entry_matches(entry, q, role, tool_name):
                        seen_ids.add(eid)
                        hits.append(self._hit_dict(entry, p))
                        if len(hits) >= limit:
                            return
        except OSError:
            return  # 段读失败 fail-open（跳过该段）

    def get_by_tool_call_id(self, session_id: str, tool_call_id: str) -> dict | None:
        """按 tool_call_id 精确取档案条目（M52: web 端分层截断"展开原文"数据源）.

        返回 None 表示未归档（未截断/归档降级），调用方如实降级。
        T3c: 有索引时按偏移精确定位；无索引回退全文扫描。
        """
        if not tool_call_id:
            return None
        for p in reversed(self._segment_paths(session_id)):  # T3b: 最近段优先
            idx = self._index_path(p)
            if idx.exists():
                # 快速通道：索引 tool_call_id 精确匹配 → 偏移定位原文
                try:
                    with idx.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if rec.get("tool_call_id") != tool_call_id:
                                continue
                            raw = self._line_at(p, rec.get("offset", 0))
                            if raw is None:
                                continue
                            try:
                                return json.loads(raw)
                            except json.JSONDecodeError:
                                return None
                except OSError:
                    pass  # 索引读失败 → 回退全文扫描
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("tool_call_id") == tool_call_id:
                        return entry
        return None

    def stats(self, session_id: str) -> dict:
        """压缩档案统计（供 architecture_status 展示，跨段累加）."""
        count = 0
        chars = 0
        for p in self._segment_paths(session_id):  # T3b: 跨段累加
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    count += 1
                    try:
                        entry = json.loads(line)
                        chars += int(entry.get("chars", 0))
                    except (json.JSONDecodeError, ValueError) as exc:  # fail-open：单行损坏跳过
                        logging.getLogger(__name__).debug("档案统计单行损坏跳过（fail-open）: %s", exc)
        return {"archived_count": count, "archived_chars": chars}

    def update_summary(self, entry_id: str, summary: str, summary_source: str) -> bool:
        """按 id 回填摘要到档案条目（T28）.

        失败返回 False + 日志（fail-open，不影响已交付档案）。
        """
        p = self._entry_session_path(entry_id)
        if p is None:
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

    def _entry_session_path(self, entry_id: str) -> Path | None:
        """定位条目所在段文件（线性扫描全部段；T3b 返回完整路径，分片正确）."""
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
                        return p
        return None

    def cleanup(self, *, max_entries: int = 0, ttl_days: int = 0) -> dict:
        """R7: 清理过期/超量档案条目（启动时调用一次，防磁盘膨胀）.

        - max_entries > 0: 单会话（跨全部段）超过 N 条时删除最旧的（保留最近 N 条）
        - ttl_days > 0: 超过 N 天的条目删除（按条目 ts 判断）
        - 两者都为 0: 空操作（零回归）
        - 单文件清理失败 fail-open（warning + 跳过），不阻断其他文件

        Returns:
            {"pruned_files": N, "pruned_entries": N}
        """
        if max_entries <= 0 and ttl_days <= 0:
            return {"pruned_files": 0, "pruned_entries": 0}

        import logging

        total_pruned = 0
        pruned_files = 0

        # 按会话分组（T3b：单会话多段跨段处理；组内按 seq 升序——注意字符串排序
        # 会把 `-1.jsonl` 排到 `.jsonl` 前（'-' < '.'），必须按 seq 数字排序）
        groups: dict[str, list[Path]] = {}
        for p in self._dir.glob("*.jsonl"):
            sid, _ = self._segment_seq(p)
            groups.setdefault(sid, []).append(p)
        for segs in groups.values():
            segs.sort(key=lambda p: self._segment_seq(p)[1])

        cutoff_ts = None
        if ttl_days > 0:
            cutoff_ts = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()

        for sid, segs in groups.items():
            try:
                kept_lines: list[str] = []  # 段内保留行（ttl 过滤后）
                per_seg: dict[Path, list[str]] = {}
                orig_counts: dict[Path, int] = {}
                for p in segs:
                    lines = p.read_text(encoding="utf-8").splitlines()
                    orig_counts[p] = len(lines)
                    kept: list[str] = []
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        if cutoff_ts is not None:
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                kept.append(line)  # 无法解析的条目保留（fail-open）
                                continue
                            ts = entry.get("ts", "")
                            if ts and ts < cutoff_ts:
                                total_pruned += 1
                                continue
                        kept.append(line)
                    per_seg[p] = kept
                    kept_lines.extend(kept)

                if max_entries > 0 and len(kept_lines) > max_entries:
                    # 跨段全局保留最近 max_entries 条（从最后段向前裁剪/删整段）
                    to_drop = len(kept_lines) - max_entries
                    for p in segs:  # seq 升序 → 从最早段开始丢
                        lines = per_seg[p]
                        if to_drop <= 0:
                            break
                        if len(lines) <= to_drop:
                            to_drop -= len(lines)
                            total_pruned += len(lines)
                            per_seg[p] = []
                        else:
                            per_seg[p] = lines[to_drop:]
                            total_pruned += to_drop
                            to_drop = 0
                # 写回/删除空段（与原始行数一致则零改动）
                for p, kept in per_seg.items():
                    if len(kept) == orig_counts[p]:
                        continue
                    if kept:
                        p.write_text("\n".join(kept) + "\n", encoding="utf-8")
                    else:
                        p.unlink(missing_ok=True)
                    pruned_files += 1
            except Exception as exc:  # noqa: BLE001 — 单会话清理失败 fail-open
                logging.getLogger(__name__).warning("档案 GC 失败（fail-open）: %s: %s", sid, exc)
                continue

        return {"pruned_files": pruned_files, "pruned_entries": total_pruned}
