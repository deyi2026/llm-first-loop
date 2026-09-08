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

from llm_loop.introspection.rule_index import RuleIndex

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
    "episode",  # INJECTION-GOVERNANCE R8.5: resolved Q&A/tool-chain index
    "rule",  # on-demand Rule SoT index / exact hydration
    "file_effect",  # P3: current-session mechanical AI/human file-effect receipts
    "synopsis",  # model-authored derived view bound to exact source SHA/ref
    "method",  # Method Learning compact discovery / exact hydration
    "all",
}


class InvalidSearchKindError(ValueError):
    """kind 取值不合法专用异常（typed 归因事实源，R3/D5）.

    继承 ValueError 保持既有 ``Raises: ValueError`` 契约与直接调用方兼容；
    异常类型即归因依据——工具层仅将该类型归为 [参数错误]，执行期其余异常
    一律归 [内部错误]，消除"按异常类型归因在类型重叠时结构性失效"缺陷。
    """


class InvalidSearchQueryError(ValueError):
    """A kind-specific strict query grammar rejected caller input."""



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
        episode_store: Any | None = None,
        experience_store: Any | None = None,
        method_store: Any | None = None,
        semantic_retriever: Any | None = None,
        rule_path: str | Path | None = None,
        file_effect_query: Any | None = None,
        workspace_scope_resolver: Any | None = None,
        synopsis_store: Any | None = None,
        synopsis_source_resolver: Any | None = None,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._memory = memory_store
        self._archive = archive_store
        self._episode_store = episode_store
        self._experience_store = experience_store  # P1-2: 经验库（None 时 _search_experience 返回空）
        self._method_store = method_store
        self._semantic = semantic_retriever  # T31: 语义检索器（可 None 走关键词）
        default_rule_path = Path(__file__).resolve().parents[3] / "docs" / "ai_rules.md"
        self._rule_index = RuleIndex(rule_path or default_rule_path)
        self._file_effect_query = file_effect_query
        self._workspace_scope_resolver = workspace_scope_resolver
        self._synopsis_store = synopsis_store
        self._synopsis_source_resolver = synopsis_source_resolver
        # R3(P0-3/D11): experience 检索诊断透传——search() 入口重置，experience/all 路径回填
        self._last_diagnostics: dict[str, Any] | None = None

    @property
    def last_diagnostics(self) -> dict[str, Any] | None:
        """最近一次 experience 检索的诊断四要素摘要（{scanned/degraded/skipped/scan_error}）.

        每次 search() 入口重置为 None，仅 experience/all 路径回填——非经验库路径
        不携带陈旧诊断；工具层经 duck-typing 读取（属性缺失优雅降级为无诊断段）。
        """
        return self._last_diagnostics

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
            InvalidSearchKindError: kind 不合法（ValueError 子类，既有 ValueError 契约保持）.
        """
        # R3(P0-3): 每次检索重置诊断，防上一次 experience/all 检索的陈旧诊断跨 kind 泄漏
        self._last_diagnostics = None
        if kind not in _VALID_KINDS:
            raise InvalidSearchKindError(f"kind '{kind}' 不在可选范围: {', '.join(sorted(_VALID_KINDS))}")
        special = self._search_special(kind, query, limit, session_id)
        if special is not None:
            return special

        # P1-4: kind=all 时各 kind 均匀分配 limit（避免前序 kind 挤占、后序永远不可见）
        each_limit = max(1, limit // 14) if kind == "all" else limit

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
                summary_keys=("id", "consistent", "declarations", "discrepancies", "cross_round_hits", "tool_call_ids"),
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
            results += self._search_memory(query, each_limit, session_id=session_id)
            results += self._search_archive(query, each_limit, session_id)
            results += self._search_episode(query, each_limit, session_id)
            results += self._search_experience(query, each_limit)  # P1-2: 经验库并列返回
            results += self._search_synopsis(query, each_limit, session_id)
            results += self._search_method(query, each_limit)
        return results[:limit]

    def _search_special(
        self, kind: str, query: str, limit: int, session_id: str
    ) -> list[dict] | None:
        """对象型/精确水合分派；普通 JSONL 关键词检索仍回主流程。

        memory/archive/episode/experience 走对象存储；declaration_check 只有精确
        source ref 才短路水合，宽查询返回 None 继续轻量 JSONL 索引。
        """
        if kind == "memory":
            return self._search_memory(query, limit, session_id=session_id)
        if kind == "archive":
            return self._search_archive(query, limit, session_id)
        if kind == "episode":
            return self._search_episode(query, limit, session_id)
        if kind == "experience":  # P1-2: 经验库检索
            return self._search_experience(query, limit)
        if kind == "rule":
            return self._rule_index.search(query, limit)
        if kind == "synopsis":
            return self._search_synopsis(query, limit, session_id)
        if kind == "method":  # Method Learning v1: 轻量 Method 卡发现（method-Mxxx/METHOD-xx 精确水合）
            return self._search_method(query, limit)
        if kind == "file_effect":
            if self._file_effect_query is None or not session_id:
                return []
            if callable(self._workspace_scope_resolver):
                scope = str(self._workspace_scope_resolver() or "")
            else:
                from llm_loop.core.run_context import workspace_base

                scope = workspace_base()
            try:
                page = self._file_effect_query.query(
                    session_id=session_id, workspace_scope=scope, query=query, limit=limit
                )
            except ValueError as exc:
                raise InvalidSearchQueryError(str(exc)) from exc
            out: list[dict] = []
            for index, receipt in enumerate(page.receipts):
                facts = receipt.public_facts()
                facts.update(
                    {
                        "kind": "file_effect",
                        "id": receipt.operation_id,
                        "ts": receipt.ts,
                        "summary": (
                            f"operation={receipt.operation_id} origin={receipt.origin} "
                            f"path={receipt.path} effect_state={receipt.effect_state} "
                            f"receipt_state={receipt.receipt_state}"
                        ),
                        "has_more": page.has_more,
                        "next_query": page.next_query if index == len(page.receipts) - 1 else "",
                    }
                )
                out.append(facts)
            return out
        if kind == "declaration_check":
            return self._hydrate_declaration_check(query)
        return None

    def _search_synopsis(self, query: str, limit: int, session_id: str) -> list[dict]:
        """Discover or explicitly hydrate model-authored source synopses.

        Ordinary search is index-only and never re-resolves sources. Exact
        ``synopsis:<id>`` hydration may compare the current exact source SHA as a
        mechanical version fact; it does not judge semantic/task applicability.
        """
        if self._synopsis_store is None:
            return []
        if callable(self._workspace_scope_resolver):
            scope = str(self._workspace_scope_resolver() or "")
        else:
            from llm_loop.core.run_context import workspace_base

            scope = workspace_base()
        raw = str(query or "").strip()
        if raw.startswith("synopsis:"):
            try:
                record = self._synopsis_store.get(
                    raw, workspace_scope=scope, session_id=session_id
                )
            except (TypeError, ValueError):
                return []
            if record is None:
                return []
            current_state = "not_checked"
            if callable(self._synopsis_source_resolver):
                try:
                    current = self._synopsis_source_resolver(record.source_ref)
                    current_sha256 = str(getattr(current, "source_sha256", "") or "")
                    current_state = (
                        "same_snapshot"
                        if current_sha256 and current_sha256 == record.source_sha256
                        else "changed_representation"
                    )
                except Exception:  # noqa: BLE001 - currentness probe is non-authoritative
                    current_state = "unavailable"
            card = record.public_card(source_ref_state=current_state)
            card["exact_summary_read"] = "source_synopsis(action=read_summary, synopsis_ref=<ref>)"
            return [card]
        try:
            records = self._synopsis_store.search(
                workspace_scope=scope,
                session_id=session_id,
                query=raw,
                limit=limit,
            )
        except (TypeError, ValueError):
            return []
        return [record.public_card() for record in records]

    def _hydrate_declaration_check(self, query: str) -> list[dict] | None:
        """精确 DC id / legacy line-ref 显式水合；宽检索返回 None 走轻量索引。

        declaration_check 是 self_eval honesty 的事实源。只有调用方明确给出
        ``DC-*`` 或 ``declaration_check.jsonl:L<n>`` 时返回 receipts 等逐样本事实；
        普通关键词检索仍由 ``_jsonl_search`` 返回 300-char 摘要，避免观测数据
        因“可检索”变成默认大上下文。
        """
        raw = str(query or "").strip()
        if raw.lower().startswith("declaration_check:"):
            raw = raw.split(":", 1)[1].strip()
        by_id = raw.startswith("DC-")
        line_no: int | None = None
        if raw.startswith("declaration_check.jsonl:L"):
            try:
                line_no = int(raw.rsplit("L", 1)[1])
            except ValueError:
                return []
        if not by_id and line_no is None:
            return None

        path = self._audit_dir / "declaration_check.jsonl"
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as f:
                for current_line, line in enumerate(f, 1):
                    if line_no is not None and current_line != line_no:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        if line_no is not None:
                            return []
                        continue
                    if by_id and str(entry.get("id") or "") != raw:
                        continue
                    source_ref = str(entry.get("id") or f"declaration_check.jsonl:L{current_line}")
                    detail_keys = (
                        "session_id",
                        "consistent",
                        "declarations",
                        "discrepancies",
                        "cross_round_hits",
                        "tool_call_ids",
                        "receipts",
                        "matched_by",
                        "answer_preview",
                    )
                    detail = {key: entry.get(key) for key in detail_keys if key in entry}
                    return [
                        {
                            "kind": "declaration_check",
                            "ts": entry.get("ts", ""),
                            "id": source_ref,
                            "summary": (
                                f"consistent={entry.get('consistent')} "
                                f"declarations={entry.get('declarations', [])} "
                                f"discrepancies={entry.get('discrepancies', [])}"
                            )[:300],
                            "file": str(path),
                            "source_ref": source_ref,
                            "hydrated": True,
                            "detail": detail,
                        }
                    ]
        except OSError:
            return []
        return []

    def _search_episode(self, query: str, limit: int, session_id: str) -> list[dict]:
        if self._episode_store is None or not session_id:
            return []
        resolved = list(self._episode_store.search(session_id, query=query, limit=limit))
        # B2(EVO-20260902-41898b20): truncated run 行并入列表（state=truncated +
        # run_end_reason），修复"中断 run 在 episode 检索面结构性不可见"；
        # duck-typing 守卫：无 search_truncated 的存储实现零影响。
        truncated: list[dict] = []
        try:
            truncated = list(
                self._episode_store.search_truncated(session_id, query=query, limit=limit)
            )
        except AttributeError:
            pass  # duck-typing 守卫：无 search_truncated 的存储实现零影响
        except Exception:  # noqa: BLE001 — truncated 列表失败不拖垮 resolved 检索
            truncated = []
        merged = sorted(
            resolved + truncated, key=lambda h: str(h.get("ts") or ""), reverse=True
        )
        return merged[: max(1, int(limit))]

    def hydrate_episode(
        self,
        *,
        session_id: str,
        ref: str,
        offset: int = 0,
        max_chars: int = 6000,
    ) -> dict | None:
        """Explicit bounded hydration for one resolved episode ref."""

        if self._episode_store is None or not session_id:
            return None
        # truncated ref uses the same explicit hydration surface. New rows prefer
        # immutable exact artifacts; legacy rows fall back to compact stored tails.
        if str(ref or "").startswith("truncated:"):
            # duck-typing 派发：无 hydrate_truncated 的存储实现如实回 None
            try:
                return self._episode_store.hydrate_truncated(
                    session_id, ref, offset=offset, max_chars=max_chars
                )
            except AttributeError:
                return None
        return self._episode_store.hydrate(
            session_id,
            ref,
            offset=offset,
            max_chars=max_chars,
        )

    # ── EVO-20260814: 统一事件流视图（对齐 Harness Trajectory 思路）──
    _EVENT_STREAMS: dict[str, tuple[str, tuple[str, ...]]] = {
        # stream 名 -> (jsonl 文件名, 摘要键)
        "action_trace": ("action_trace.jsonl", ("phase", "action_type", "detail")),
        "exception_log": ("exception_log.jsonl", ("phase", "error_type", "detail")),
        "self_correction": ("self_correction_log.jsonl", ("phase", "action", "detail")),
        "evolution": ("evolution_suggestions.jsonl", ("id", "status", "content")),
        "param_adjust": ("param_adjust_history.jsonl", ("key", "before", "after")),
        "declaration_check": (
            "declaration_check.jsonl",
            ("id", "consistent", "declarations", "discrepancies", "cross_round_hits", "tool_call_ids"),
        ),
        "self_eval": ("self_eval_log.jsonl", ("eval_id", "trigger", "summary")),
        "memory_extract": ("memory_extract_log.jsonl", ("extract_id", "scope", "summary")),
        "proc_versions": ("proc_versions.jsonl", ("process", "version", "started_at")),
        "feishu_audit": ("feishu_audit.jsonl", ("message_id", "sender_id", "action", "note")),
        "evolution_exec": ("evolution_exec_log.jsonl", ("id", "status", "note")),
        # M2-G1.3: tool octet 观测流（terminal tool receipt；摘要键仅顶层字段，
        # status/reason_code 在 outcome 嵌套内——红线禁止顺手支持 nested 查询）
        "tool_octet": ("tool_octet.jsonl", ("tool_name", "round_index", "args_digest")),
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

    def _search_method(self, query: str, limit: int) -> list[dict]:
        """Method cards by default; exact ``method:<id>`` hydrates one full record."""
        if self._method_store is None:
            return []
        return self._method_store.list(query, limit)

    def _search_experience(self, query: str, limit: int) -> list[dict]:
        """P1-2/R3: experience search with exact ``experience:<id>`` hydration."""
        if self._experience_store is None:
            self._last_diagnostics = None
            return []
        raw = str(query or "").strip()
        exact = raw[len("experience:") :] if raw.lower().startswith("experience:") else raw
        if exact:
            doc = self._experience_store.get(exact)
            if doc is not None:
                # R3(P0-3): hydrate 路径不走扫描，诊断置健康零值（区分"不存在/不可解析"
                # 依赖 get 留痕日志归因，design §1.2.3 口径注明）
                self._last_diagnostics = {"scanned": 0, "degraded": 0, "skipped": 0, "scan_error": None}
                stem = exact.removesuffix(".md")
                return [self._experience_store.to_hydrated_record(stem, doc)][:limit]
        # R3(P0-3): 三态扫描 Outcome——诊断独立于 results[:limit] 截断照常回填
        #（kind=all 聚合中 experience 记录被挤出返回集时，诊断仍到达模型）
        outcome = self._experience_store.search_outcome(query, limit)
        self._last_diagnostics = {
            "scanned": outcome.scanned_count,
            "degraded": outcome.degraded_count,
            "skipped": outcome.skipped_count,
            "scan_error": outcome.scan_error,
        }
        return outcome.records

    @staticmethod
    def _memory_visible_in_session(entry: Any, session_id: str) -> bool:
        return getattr(entry, "scope", "global") != "session" or (
            bool(session_id) and getattr(entry, "source_session_id", "") == session_id
        )

    @staticmethod
    def _memory_record(entry: Any) -> dict:
        return {
            "kind": "memory",
            "ts": entry.created_at,
            "id": entry.id,
            "summary": _memory_progressive_summary(entry),
            "file": "memory/index.json",
            "key": f"memory:{entry.id}",
        }

    def _search_memory(
        self, query: str, limit: int, session_id: str = ""
    ) -> list[dict]:
        """R3: keyword search plus exact ``memory:<id>`` hydration with scope isolation."""
        if self._memory is None:
            return []
        raw = str(query or "").strip()
        exact = raw[len("memory:") :] if raw.lower().startswith("memory:") else raw
        if exact:
            entry = self._memory._by_id(exact)  # noqa: SLF001 - exact ref hydration
            if entry is not None and self._memory_visible_in_session(entry, session_id):
                return [self._memory_record(entry)][:limit]
        if not raw:
            entries = [
                e
                for e in self._memory.all()
                if self._memory_visible_in_session(e, session_id)
            ]
            return [self._memory_record(e) for e in entries[:limit]]
        keyword_hits = self._memory.search(
            raw.split(), top_k=limit, session_id=session_id
        )
        keyword_dicts = [self._memory_record(e) for e in keyword_hits]
        # T31: semantic recall keeps the same session-scoped keyword seed.
        if self._semantic is not None and self._semantic.semantic_available():
            result = self._semantic.search(
                raw,
                top_k=limit,
                scope="memory",
                session_id=session_id,
                memory=self._memory,
                keyword_results=keyword_dicts,
            )
            merged = self._merge_semantic(result, keyword_dicts, "memory")
            return [
                h
                for h in merged
                if not str(h.get("id", ""))
                or (
                    (entry := self._memory._by_id(str(h.get("id", "")))) is None
                    or self._memory_visible_in_session(entry, session_id)
                )
            ][:limit]
        return keyword_dicts

    def _search_archive(self, query: str, limit: int, session_id: str) -> list[dict]:
        if self._archive is None:
            return []
        if session_id:
            keyword_hits = self._tag_kind(self._archive.search(session_id, query, limit=limit))
        else:
            keyword_hits = []
            for sid in self._archive.session_ids():
                keyword_hits += self._archive.search(
                    sid, query, limit=limit - len(keyword_hits)
                )
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
                    # EVO-20260903-06e5a2fd: 只有精确 eval_id 水合才带逐样本诊断；
                    # 宽检索/列表保持轻量，避免观测数据反向污染工作上下文。
                    exact_query = q.removeprefix("eval:")
                    if exact_query == str(entry.get("eval_id", "")).lower():
                        diagnostics = entry.get("diagnostics")
                        if isinstance(diagnostics, dict) and diagnostics:
                            record["diagnostics"] = diagnostics
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
