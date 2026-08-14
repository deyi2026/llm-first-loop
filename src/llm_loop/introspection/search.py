"""统一检索 search_records（design.md T23: 记录 AI 可查可检索）.

边界说明（M11）: 本模块为统一检索实现层（RecordSearcher，无 LLM 可见性）;
LLM 可见的工具分派/呈现层在 introspection/corrections.py（消费本模块 search_records_fn）。

架构运行记录（action_trace/exception_log/self_correction_log/declaration_check）
与记忆、压缩档案**统一可被 AI 通过工具检索**——可查可检索、可溯源，
不限于内存窗口。

- JSONL 全文关键词匹配（复用 ArchiveStore 检索思路）
- memory 走 MemoryStore.search
- archive 走 ArchiveStore.search（search_archive 为其薄封装别名，统一入口）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_VALID_KINDS = {
    "action_trace",
    "exception_log",
    "self_correction_log",
    "declaration_check",
    "memory",
    "memory_extract",  # T33: 独立记忆提取记录
    "archive",
    "selfheal",  # M12 T49: 故障自愈记录
    "param_adjust",  # M12 T51: 参数调整历史
    "evolution",  # M12 T52: 架构演进建议
    "evolution_exec",  # M12 深化 T57: 演进执行审计（EXEC-06）
    "self_eval",  # M12 深化 T62: 自我评估记录（EVAL-04）
    "change_log",  # P2-6: 配置变更审计
    "proc_versions",  # P2-6: 进程版本记录
    "feishu_audit",  # P2-6: 飞书消息审计
    "experience",  # P1-2: 经验库检索
    "all",
}


def _jsonl_search(
    path: Path,
    query: str,
    limit: int,
    *,
    kind: str,
    summary_keys: tuple[str, ...],
    content_key: str = "content",
) -> list[dict]:
    """JSONL 全文关键词匹配，返回结构化可溯源记录."""
    if not path.exists():
        return []
    q = query.lower()
    hits: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            hay = " ".join(str(entry.get(k, "")) for k in summary_keys + (content_key,)).lower()
            if q and q not in hay:
                continue
            hits.append(
                {
                    "kind": kind,
                    "ts": entry.get("ts", entry.get("created_at", entry.get("timestamp", ""))),
                    "id": entry.get("id", ""),
                    "summary": " ".join(str(entry.get(k, "")) for k in summary_keys)[:300],
                    "file": str(path),
                }
            )
            if len(hits) >= limit:
                break
    return hits


def _memory_progressive_summary(e) -> str:
    """渐进水合展示：procedure 条目优先提取【已验解法】段（契约级），其余回退整条前 300 字.

    借鉴 SkillZip PathHydrate（progressive disclosure）：AI 检索经验时先看可执行解法，
    而非整条陈述，减少 token 占用（SkillZip 论文: 文本接近≠契约等价，解法段才是可执行契约）。
    """
    content = str(getattr(e, "content", "") or "")
    if getattr(e, "type", "") == "procedure":
        idx = content.find("已验解法")
        if idx != -1:
            start = idx + len("已验解法")
            while start < len(content) and content[start] in ":： \n\t":
                start += 1
            end = len(content)
            for stop in ("\n实证", "\n反例", "\n触发标签"):
                pos = content.find(stop, start)
                if pos != -1:
                    end = min(end, pos)
            solution = content[start:end].strip()
            if solution:
                return f"[已验解法] {solution[:280]}"
    return content[:300]


class RecordSearcher:
    """统一检索器（T23）: 各 kind 记录 + 记忆 + 压缩档案（T31 语义路径）."""

    def __init__(
        self,
        *,
        audit_dir: str | Path,
        memory_store: Any | None = None,
        archive_store: Any | None = None,
        experience_store: Any | None = None,
        semantic_retriever: Any | None = None,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._memory = memory_store
        self._archive = archive_store
        self._experience_store = experience_store  # P1-2: 经验库（None 时 _search_experience 返回空）
        self._semantic = semantic_retriever  # T31: 语义检索器（可 None 走关键词）

    def search(
        self,
        kind: str = "all",
        query: str = "",
        limit: int = 10,
        session_id: str = "",
    ) -> list[dict]:
        """统一检索入口.

        Args:
            kind: 检索类别（7 种之一）.
            query: 关键词（空则返回该 kind 最近记录）.
            limit: 条数上限.
            session_id: 会话过滤（archive 用）.

        Raises:
            ValueError: kind 不合法.
        """
        if kind not in _VALID_KINDS:
            raise ValueError(f"kind '{kind}' 不在可选范围: {', '.join(sorted(_VALID_KINDS))}")

        if kind == "memory":
            return self._search_memory(query, limit)
        if kind == "archive":
            return self._search_archive(query, limit, session_id)
        if kind == "experience":  # P1-2: 经验库检索
            return self._search_experience(query, limit)

        # P1-4: kind=all 时各 kind 均匀分配 limit（避免前序 kind 挤占、后序永远不可见）
        each_limit = max(1, limit // 13) if kind == "all" else limit

        results: list[dict] = []
        if kind in {"action_trace", "all"}:
            results += _jsonl_search(
                self._audit_dir / "action_trace.jsonl",
                query,
                each_limit,
                kind="action_trace",
                summary_keys=("phase", "action_type", "detail"),
            )
        if kind in {"exception_log", "all"}:
            results += _jsonl_search(
                self._audit_dir / "exception_log.jsonl",
                query,
                each_limit,
                kind="exception_log",
                summary_keys=("phase", "error_type", "error_message"),
            )
        if kind in {"self_correction_log", "all"}:
            results += _jsonl_search(
                self._audit_dir / "self_correction_log.jsonl",
                query,
                each_limit,
                kind="self_correction_log",
                summary_keys=("tool_name", "result_status"),
            )
        if kind in {"selfheal", "all"}:  # M12 T49: 故障自愈记录
            results += _jsonl_search(
                self._audit_dir / "selfheal_log.jsonl",
                query,
                each_limit,
                kind="selfheal",
                summary_keys=("component", "error_type", "category", "suggested_actions"),
                content_key="error_message",
            )
        if kind in {"param_adjust", "all"}:  # M12 T51: 参数调整历史
            results += _jsonl_search(
                self._audit_dir / "param_adjust_history.jsonl",
                query,
                each_limit,
                kind="param_adjust",
                summary_keys=("key", "before", "after"),
            )
        if kind in {"evolution", "all"}:  # M12 T52: 演进建议
            evolution_path = self._audit_dir / "evolution_suggestions.jsonl"
            if evolution_path.exists():
                results += _jsonl_search(
                    evolution_path,
                    query,
                    each_limit,
                    kind="evolution",
                    summary_keys=("content", "evidence", "impact_scope", "status"),
                )
        if kind in {"evolution_exec", "all"}:  # M12 深化 T57: 演进执行审计（EXEC-06）
            exec_path = self._audit_dir / "evolution_exec_log.jsonl"
            if exec_path.exists():
                results += _jsonl_search(
                    exec_path,
                    query,
                    each_limit,
                    kind="evolution_exec",
                    summary_keys=("suggestion_id", "executor", "status", "verify_result"),
                    content_key="note",
                )
        if kind in {"self_eval", "all"}:  # M12 深化 T62: 自我评估记录（EVAL-04）
            eval_path = self._audit_dir / "self_eval_log.jsonl"
            if eval_path.exists():
                results += self._search_self_eval(eval_path, query, each_limit)
        if kind in {"evolution", "all"}:  # M12 深化 T62: 建议带 eval_id → 关联评估摘要
            self._annotate_evolution_eval(results)
        if kind in {"memory_extract", "all"}:  # T33: 独立记忆提取记录
            results += _jsonl_search(
                self._audit_dir / "memory_extract_log.jsonl",
                query,
                each_limit,
                kind="memory_extract",
                summary_keys=("trigger", "session_id", "note"),
                content_key="failures",
            )
        if kind in {"declaration_check", "all"}:
            results += _jsonl_search(
                self._audit_dir / "declaration_check.jsonl",
                query,
                each_limit,
                kind="declaration_check",
                summary_keys=("consistent", "declarations", "discrepancies"),
                content_key="answer_preview",
            )
        if kind in {"change_log", "all"}:  # P2-6: 配置变更审计
            results += _jsonl_search(
                self._audit_dir / "change_log.jsonl",
                query,
                each_limit,
                kind="change_log",
                summary_keys=("key", "before", "after", "note"),
            )
        if kind in {"proc_versions", "all"}:  # P2-6: 进程版本记录
            results += _jsonl_search(
                self._audit_dir / "proc_versions.jsonl",
                query,
                each_limit,
                kind="proc_versions",
                summary_keys=("process", "version", "started_at"),
                content_key="git_hash",
            )
        if kind in {"feishu_audit", "all"}:  # P2-6: 飞书消息审计
            results += _jsonl_search(
                self._audit_dir / "feishu_audit.jsonl",
                query,
                each_limit,
                kind="feishu_audit",
                summary_keys=("message_id", "sender_id", "action", "note"),
                content_key="text",
            )
        if kind == "all":
            results += self._search_memory(query, each_limit)
            results += self._search_archive(query, each_limit, session_id)
            results += self._search_experience(query, each_limit)  # P1-2: 经验库并列返回
        return results[:limit]

    # ── EVO-20260814: 统一事件流视图（对齐 Harness Trajectory 思路）──
    _EVENT_STREAMS: dict[str, tuple[str, tuple[str, ...]]] = {
        # stream 名 -> (jsonl 文件名, 摘要键)
        "action_trace": ("action_trace.jsonl", ("phase", "action_type", "detail")),
        "exception_log": ("exception_log.jsonl", ("phase", "error_type", "detail")),
        "self_correction": ("self_correction_log.jsonl", ("phase", "action", "detail")),
        "evolution": ("evolution_suggestions.jsonl", ("id", "status", "content")),
        "param_adjust": ("param_adjust_history.jsonl", ("key", "before", "after")),
        "declaration_check": ("declaration_check_log.jsonl", ("phase", "result", "detail")),
        "self_eval": ("self_eval.jsonl", ("eval_id", "trigger", "summary")),
        "memory_extract": ("memory_extract_log.jsonl", ("extract_id", "scope", "summary")),
        "proc_versions": ("proc_versions.jsonl", ("process", "version", "started_at")),
        "feishu_audit": ("feishu_audit.jsonl", ("message_id", "sender_id", "action", "note")),
        "evolution_exec": ("evolution_exec_log.jsonl", ("id", "status", "note")),
    }

    def event_stream(
        self,
        streams: str = "all",
        query: str = "",
        limit: int = 50,
        since: str = "",
    ) -> list[dict]:
        """统一事件流视图（EVO-20260814）.

        把分散的 append-only 审计流（action_trace/exception_log/...）按时间序
        合并为单一轨迹视图——对齐 Harness 的 Trajectory 思路：可观测/回溯
        应看到"一条流"，而非各文件分别查。

        Args:
            streams: 逗号分隔的流名子集（'all' = 全部流；'action_trace,exception_log' = 指定流）.
            query: 关键词（空 = 不过滤）.
            limit: 返回条数上限（按时间倒序取最近 N 条）.
            since: ISO 时间下界（只返回 ts >= since 的事件，空 = 不限）.

        Returns:
            按 ts 升序（旧→新）的统一事件列表; 每条含 stream/ts/summary 可溯源.
        """
        if streams.strip().lower() == "all":
            names = list(self._EVENT_STREAMS)
        else:
            names = [s.strip() for s in streams.split(",") if s.strip()]
        q = query.lower()
        merged: list[dict] = []
        for name in names:
            fname, keys = self._EVENT_STREAMS.get(name, (None, ()))
            if fname is None:
                continue  # 未知流名跳过（不阻断）
            path = self._audit_dir / fname
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = str(entry.get("ts", entry.get("created_at", entry.get("timestamp", ""))))
                    if since and ts < since:
                        continue
                    hay = " ".join(
                        str(entry.get(k, "")) for k in keys + ("content", "note")
                    ).lower()
                    if q and q not in hay:
                        continue
                    merged.append(
                        {
                            "stream": name,
                            "ts": ts,
                            "summary": " ".join(str(entry.get(k, "")) for k in keys)[:300],
                            "file": str(path),
                        }
                    )
        # 按 ts 降序取最近 N 条，再反转为升序（旧→新轨迹）
        merged.sort(key=lambda e: e["ts"], reverse=True)
        merged = merged[:limit]
        merged.sort(key=lambda e: e["ts"])
        return merged

    def _search_experience(self, query: str, limit: int) -> list[dict]:
        """P1-2: 经验库检索（None 时返回空，零回归）。"""
        if self._experience_store is None:
            return []
        return self._experience_store.list_active(query, limit)

    def _search_memory(self, query: str, limit: int) -> list[dict]:
        if self._memory is None:
            return []
        if not query:
            entries = self._memory.all()
            return [
                {
                    "kind": "memory",
                    "ts": e.created_at,
                    "id": e.id,
                    "summary": e.content[:300],
                    "file": "memory/index.json",
                }
                for e in entries[:limit]
            ]
        keyword_hits = self._memory.search(query.split(), top_k=limit)
        keyword_dicts = [
            {
                "kind": "memory",
                "ts": e.created_at,
                "id": e.id,
                # SkillZip PathHydrate 借鉴（渐进水合）: procedure 命中时优先返回
                # "已验解法"段（契约级可执行信息），非 procedure 或无法提取则回退整条前 300 字
                "summary": _memory_progressive_summary(e),
                "file": "memory/index.json",
                "key": f"memory:{e.id}",
            }
            for e in keyword_hits
        ]
        # T31: 语义召回（预算内，失败/不可用如实降级为关键词）
        if self._semantic is not None and self._semantic.semantic_available():
            result = self._semantic.search(
                query,
                top_k=limit,
                scope="memory",
                memory=self._memory,
                keyword_results=keyword_dicts,
            )
            return self._merge_semantic(result, keyword_dicts, "memory")
        return keyword_dicts

    def _search_archive(self, query: str, limit: int, session_id: str) -> list[dict]:
        if self._archive is None:
            return []
        if session_id:
            keyword_hits = self._tag_kind(self._archive.search(session_id, query, limit=limit))
        else:
            archive_dir = getattr(self._archive, "_dir", None)
            if archive_dir is None:
                return []
            keyword_hits = []
            for p in sorted(Path(archive_dir).glob("*.jsonl")):
                sid = p.stem
                keyword_hits += self._archive.search(sid, query, limit=limit - len(keyword_hits))
                if len(keyword_hits) >= limit:
                    break
            keyword_hits = self._tag_kind(keyword_hits)
        # T31: 语义召回
        if self._semantic is not None and self._semantic.semantic_available():
            result = self._semantic.search(
                query,
                top_k=limit,
                scope="archive",
                session_id=session_id,
                archive=self._archive,
                keyword_results=keyword_hits,
            )
            return self._merge_semantic(result, keyword_hits, "archive")
        return keyword_hits

    def _merge_semantic(self, result, keyword_hits: list[dict], kind: str) -> list[dict]:
        """语义结果与关键词结果融合（mode/note 如实标注）."""
        merged = list(result.entries)
        for h in merged:
            h.setdefault("kind", kind)
        if result.mode == "keyword":
            for h in keyword_hits:
                h.setdefault("note", result.note or "语义检索不可用，已降级为关键词检索")
        else:
            for h in merged:
                h.setdefault("note", f"语义检索生效（mode={result.mode}）")
        return merged

    @staticmethod
    def _tag_kind(hits: list[dict]) -> list[dict]:
        for h in hits:
            h.setdefault("kind", "archive")
        return hits

    def _search_self_eval(self, path: Path, query: str, limit: int) -> list[dict]:
        """self_eval 检索（EVAL-04 可检索 + EVAL-05 双向溯源: 返回关联建议 ID）."""
        q = query.lower()
        hits: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    hay = " ".join(
                        str(entry.get(k, ""))
                        for k in ("eval_id", "session_id", "trigger", "summary", "note")
                    ).lower()
                    if q and q not in hay:
                        continue
                    summary = f"{entry.get('eval_id', '')} trigger={entry.get('trigger', '')}: {entry.get('summary', '')[:200]}"
                    linked = self._evolution_linked_to_eval(str(entry.get("eval_id", "")))
                    record = {
                        "kind": "self_eval",
                        "ts": entry.get("ts", ""),
                        "id": entry.get("eval_id", ""),
                        "summary": summary,
                        "file": str(path),
                    }
                    if linked:
                        record["linked_suggestions"] = linked  # 评估 → 建议（双向溯源）
                    hits.append(record)
                    if len(hits) >= limit:
                        break
        except OSError:
            return []
        return hits

    def _evolution_linked_to_eval(self, eval_id: str) -> list[str]:
        """按 eval_id 反查关联建议 ID（评估 → 建议溯源）."""
        if not eval_id:
            return []
        path = self._audit_dir / "evolution_suggestions.jsonl"
        if not path.exists():
            return []
        linked: list[str] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("eval_id") == eval_id:
                        linked.append(str(entry.get("id", "")))
        except OSError:
            return []
        return linked

    def _annotate_evolution_eval(self, results: list[dict]) -> None:
        """evolution 检索结果带 eval_id → 附加关联评估摘要（建议 → 评估溯源）."""
        if not results:
            return
        eval_path = self._audit_dir / "self_eval_log.jsonl"
        if not eval_path.exists():
            return
        eval_summaries: dict[str, str] = {}
        try:
            with eval_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eid = str(entry.get("eval_id", ""))
                    if eid:
                        eval_summaries[eid] = str(entry.get("summary", ""))[:200]
        except OSError:
            return
        for r in results:
            eid = str(r.get("id", ""))
            if eid in eval_summaries:
                r["linked_eval_summary"] = eval_summaries[eid]
