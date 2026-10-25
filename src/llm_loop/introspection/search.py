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

import hashlib
import heapq
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.run_context import workspace_base
from llm_loop.introspection.rule_index import RuleIndex
from llm_loop.knowledge import heldout_guard
from llm_loop.runtime.installation import bundle_root
from llm_loop.timekeeping import system_local_now
from llm_loop.usage_net import row_annotation as _usage_net_row_annotation

_LOGGER = logging.getLogger("llm_loop.introspection.search")

# EVO-20260923-6fe23c9b F2(b): 行为卡（method/experience/lesson）卡龄降权阈值（天，按 updated_at/ts）
CARD_AGE_DOWNWEIGHT_DAYS = 14


def annotate_card_age(rows: list[dict]) -> list[dict]:
    """检索行为卡附 card_age_days；超龄（>14d 未更新）稳定降权排后（组内保持原相关序）。

    exact hydration 路径不经过本函数（precise ref 不参与排序权衡）。
    """
    now = system_local_now()
    annotated: list[dict] = []
    for row in rows:
        ts = str(row.get("updated_at") or row.get("ts") or "")
        age_days: int | None = None
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                age_days = max((now - dt).days, 0)
            except ValueError:
                age_days = None
        if age_days is not None:
            row = {**row, "card_age_days": age_days}
            if age_days > CARD_AGE_DOWNWEIGHT_DAYS:
                row["card_age_downweighted"] = True
        annotated.append(row)
    return sorted(annotated, key=lambda r: 1 if r.get("card_age_downweighted") else 0)

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
    "lesson",  # P1-B: 失败/未验证/已证伪教训，与正向经验分开 discovery
    "episode",  # INJECTION-GOVERNANCE R8.5: resolved Q&A/tool-chain index
    "rule",  # on-demand Rule SoT index / exact hydration
    "file_effect",  # P3: current-session mechanical AI/human file-effect receipts
    "synopsis",  # model-authored derived view bound to exact source SHA/ref
    "method",  # Method Learning compact discovery / exact hydration
    "all",
}

# held-out 读侧可见过滤（fail-open）**不做字段挑选**：对注解完成后的最终返回行
# 整行 json.dumps 后交 heldout_guard 检查（见 RecordSearcher._heldout_row_text）。
# 第一轮的字段白名单漏掉了注解阶段注入的键（freshness_refs / recent_issue），
# 第二轮改为整行序列化——任何阶段（card()/hydrated() 投影、annotate_card_age、
# _annotate_usage 的 usage_feedback 合并、语义卡构造）写入行的模型文本都在
# 检查面内；调用契约：过滤必须发生在所有注解之后、knowledge_read 打点之前。


class InvalidSearchKindError(ValueError):
    """kind 取值不合法专用异常（typed 归因事实源，R3/D5）.

    继承 ValueError 保持既有 ``Raises: ValueError`` 契约与直接调用方兼容；
    异常类型即归因依据——工具层仅将该类型归为 [参数错误]，执行期其余异常
    一律归 [内部错误]，消除"按异常类型归因在类型重叠时结构性失效"缺陷。
    """


class InvalidSearchQueryError(ValueError):
    """A kind-specific strict query grammar rejected caller input."""



def _query_terms(query: str) -> list[str]:
    """空白分词并小写化；空串返回空列表（空=不过滤，保持列表模式契约）.

    小写化与 hay 的 .lower() 对齐（对齐旧实现 ``q = query.lower()`` 语义，
    大写查询如 ``EVO-20260918-c63f0c21``/``DC-1`` 不再结构性落空）。
    """
    return [t.lower() for t in str(query or "").split() if t]


def _hay_matches(hay: str, terms: list[str]) -> bool:
    """词项 AND 匹配（每词独立子串命中）；terms 为空视为不过滤.

    EVO-20260918 修复: 原 ``q not in hay`` 整串子串导致多词查询（如
    ``浏览器 感知``）对原文含 ``browser_perceive`` 的记录结构性落空；
    分词 AND 是原单串行为的严格超集，不减少既有命中。
    """
    return all(t in hay for t in terms)


def _jsonl_search(
    path: Path,
    query: str,
    limit: int,
    *,
    kind: str,
    summary_keys: tuple[str, ...],
    content_key: str = "content",
) -> list[dict]:
    """JSONL 全文关键词匹配，返回结构化可溯源记录.

    EVO-20260918 修复: 检索域从 summary_keys+content 扩展为恒含 ``id``/``ts``
    ——按记录 id（如 ``EVO-20260918-c63f0c21``）查询不再结构性落空；
    多词查询按空白分词 AND 匹配。summary 呈现字段保持不变。

    ASSESS-20261008 BUG-05: 候选选择发生在输出 limit 之前——同词多条命中按
    （ts, 行序）取最新 top-k（结果新→旧），内存上界 O(limit)（有界淘汰，
    不整文件载入排序）。原实现按文件位置取前 limit 条：append-only old→new
    写入 + limit=1 永远只返回最旧记录（位置偏置）。损坏行跳过不崩溃；
    ts 缺失视为最旧；同 ts 以行序新者胜。事件顺序复盘走 event_stream
    （独立全扫实现，升序契约不受影响）。
    """
    if not path.exists():
        return []
    terms = _query_terms(query)
    hits: list[tuple[str, int, dict]] = []  # 小顶堆: (ts_key, seq, item)
    with path.open("r", encoding="utf-8") as f:
        for seq, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("ts", entry.get("created_at", entry.get("timestamp", "")))
            hay = " ".join(
                str(v)
                for v in (
                    entry.get("id", ""),
                    ts,
                    *(entry.get(k, "") for k in summary_keys),
                    entry.get(content_key, ""),
                )
            ).lower()
            if terms and not _hay_matches(hay, terms):
                continue
            heapq.heappush(
                hits,
                (
                    str(ts or ""),
                    seq,
                    {
                        "kind": kind,
                        "ts": ts,
                        "id": entry.get("id", ""),
                        "summary": " ".join(
                            str(entry.get(k, "")) for k in summary_keys
                        )[:300],
                        "file": str(path),
                    },
                ),
            )
            if len(hits) > limit:
                heapq.heappop(hits)
    hits.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in hits]


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
        semantic_memory_enabled: bool = True,
        semantic_archive_enabled: bool = True,
        semantic_method_enabled: bool = True,
        rule_path: str | Path | None = None,
        file_effect_query: Any | None = None,
        workspace_scope_resolver: Any | None = None,
        synopsis_store: Any | None = None,
        synopsis_source_resolver: Any | None = None,
        multiquery_shadow: Any | None = None,
        knowledge_read_sink: Any | None = None,
        rule_feedback_projection: Any | None = None,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._memory = memory_store
        self._archive = archive_store
        self._multiquery_shadow = multiquery_shadow  # REPORT-20260924 影子探针（None/off=零行为）
        self._episode_store = episode_store
        self._experience_store = experience_store  # P1-2: 经验库（None 时 _search_experience 返回空）
        self._method_store = method_store
        self._semantic = semantic_retriever  # T31: 语义检索器（可 None 走关键词）
        self._semantic_memory_enabled = bool(semantic_memory_enabled)
        self._semantic_archive_enabled = bool(semantic_archive_enabled)
        self._semantic_method_enabled = bool(semantic_method_enabled)
        rule_root = bundle_root() or Path(__file__).resolve().parents[3]
        default_rule_path = rule_root / "docs" / "ai_rules.md"
        self._rule_index = RuleIndex(rule_path or default_rule_path)
        self._file_effect_query = file_effect_query
        self._workspace_scope_resolver = workspace_scope_resolver
        self._synopsis_store = synopsis_store
        self._synopsis_source_resolver = synopsis_source_resolver
        # TASK-ac085ab1-002: 精确水合成功路径的 knowledge_read 打点 sink（fail-open）
        self._knowledge_read_sink = knowledge_read_sink
        # TASK-ac085ab1-003: 规则反馈注释通道（EventStore 投影，只读派生）
        self._rule_feedback_projection = rule_feedback_projection
        # R3(P0-3/D11): experience 检索诊断透传——search() 入口重置，experience/all 路径回填
        self._last_diagnostics: dict[str, Any] | None = None
        self._last_semantic_diagnostics: dict[str, Any] | None = None
        # held-out 读侧可见过滤（fail-open）：丢弃行计数与 task_id；
        # search() 入口重置为 None（None=本次未发生丢弃，含未走 method/experience 路径）。
        self._last_heldout_filter: dict[str, Any] | None = None

    @property
    def last_diagnostics(self) -> dict[str, Any] | None:
        """最近一次 experience 检索的诊断四要素摘要（{scanned/degraded/skipped/scan_error}）.

        每次 search() 入口重置为 None，仅 experience/all 路径回填——非经验库路径
        不携带陈旧诊断；工具层经 duck-typing 读取（属性缺失优雅降级为无诊断段）。
        """
        return self._last_diagnostics

    @property
    def semantic_diagnostics(self) -> dict[str, Any] | None:
        """最近一次 semantic 检索的机械诊断，不包含查询正文或记录内容."""
        return self._last_semantic_diagnostics

    def rule_exists(self, ref: str) -> bool:
        """Exact rule-ref existence over the same RuleIndex truth source.

        TASK-ac085ab1-004: 受限结算通道的 rule_lookup 用——只做存在性判断，
        不走 search() 主路径（避免触发 knowledge_read 打点/泛查询逻辑）。
        回执 rule_ref 与请求 ref 全等才视为存在，防止模糊命中伪造存在性。
        """
        clean = str(ref or "").strip().upper()
        if not clean:
            return False
        rows = self._rule_index.search(clean, 1)
        return bool(rows) and str(rows[0].get("rule_ref") or "").upper() == clean

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
        self._last_semantic_diagnostics = None
        self._last_heldout_filter = None
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
            # P1-B: all 可发现两类学习记录；每条卡片自身携带
            # record_kind/verification_state，不把失败 lesson 静默当成正向经验。
            results += self._search_experience(query, each_limit, record_kind=None, session_id=session_id)
            results += self._search_synopsis(query, each_limit, session_id)
            results += self._search_method(query, each_limit, session_id=session_id)
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
        if kind == "experience":  # P1-2/P1-B: verified-positive/legacy experience discovery
            return self._search_experience(query, limit, record_kind="experience", session_id=session_id)
        if kind == "lesson":
            return self._search_experience(query, limit, record_kind="lesson", session_id=session_id)
        if kind == "rule":
            return self._search_rule(query, limit, session_id)
        if kind == "synopsis":
            return self._search_synopsis(query, limit, session_id)
        if kind == "method":  # Method Learning v1: 轻量 Method 卡发现（method-Mxxx/METHOD-xx 精确水合）
            return self._search_method(query, limit, session_id=session_id)
        if kind == "file_effect":
            if self._file_effect_query is None or not session_id:
                return []
            if callable(self._workspace_scope_resolver):
                scope = str(self._workspace_scope_resolver() or "")
            else:

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
        session_id: str | None = None,
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
            session_id: 精确 session 过滤；None 表示显式 workspace-wide 审计.

        Returns:
            按 ts 升序（旧→新）的统一事件列表; 每条含 stream/ts/summary 可溯源.
        """
        if streams.strip().lower() == "all":
            names = list(self._EVENT_STREAMS)
        else:
            names = [s.strip() for s in streams.split(",") if s.strip()]
        # EVO-20260918: 多词分词 AND + id/ts 入检索域（与 _jsonl_search 对齐）
        terms = _query_terms(query)
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
                    entry_session_id = str(entry.get("session_id") or "")
                    if session_id is not None and entry_session_id != session_id:
                        continue
                    hay = " ".join(
                        str(v)
                        for v in (
                            entry.get("id", ""),
                            ts,
                            *(entry.get(k, "") for k in keys),
                            entry.get("content", ""),
                            entry.get("note", ""),
                        )
                    ).lower()
                    if terms and not _hay_matches(hay, terms):
                        continue
                    merged.append(
                        {
                            "stream": name,
                            "ts": ts,
                            "session_id": entry_session_id,
                            "summary": " ".join(str(entry.get(k, "")) for k in keys)[:300],
                            "file": str(path),
                        }
                    )
        # 按 ts 降序取最近 N 条，再反转为升序（旧→新轨迹）
        merged.sort(key=lambda e: e["ts"], reverse=True)
        merged = merged[:limit]
        merged.sort(key=lambda e: e["ts"])
        return merged

    def _annotate_usage(self, rows: list[dict], *, side: str) -> list[dict]:
        """EVO-20261014-7299aec2: 命中行附使用净分（record_use 审计派生视图，只读）。

        与 card_age 同一聚合层；fail-open——派生视图任何异常只降级为不加字段，
        不得影响检索主路径。

        TASK-ac085ab1-003 P1 查询回流: store 有 usage_feedback 时改用其完整反馈
        注释（净分 + 分项自评 + 近因问题摘要 + 当前版本状态 + 读取入口 +
        legacy 未分层分母披露），per-side 模式不变。
        """
        if not rows:
            return rows
        store = self._method_store if side == "method" else self._experience_store
        if store is None:
            return rows
        memo: dict[str, dict | None] = {}
        annotated: list[dict] = []
        for row in rows:
            try:
                ref = str(row.get("experience_ref") or row.get("key") or "")
                if not ref:
                    annotated.append(row)
                    continue
                if ref not in memo:
                    feedback = getattr(store, "usage_feedback", None)
                    value = feedback(ref) if callable(feedback) else None
                    if value is None:
                        # 回退旧路径：净分注释（usage_net 摘要 → 行注字段）
                        summary = store.usage_net(ref)
                        value = _usage_net_row_annotation(summary) if summary else None
                    # 只收 dict 形态的反馈视图入 memo（与下方 isinstance 消费口径
                    # 一致）；非 dict 结果一律按无附加注释处理，行为不变。
                    memo[ref] = value if isinstance(value, dict) else None
                extra = memo[ref] if isinstance(memo[ref], dict) else None
                annotated.append({**row, **extra} if extra else row)
            except Exception:  # noqa: BLE001 — 派生视图降级不阻断检索
                annotated.append(row)
        return annotated

    def _emit_knowledge_read(
        self, *, kind: str, ref: str, version: str, session_id: str, extra: dict | None = None
    ) -> None:
        """TASK-ac085ab1-002: 精确水合成功路径打 knowledge_read 事件（fail-open）.

        版本哈希取自构成本次回执的同一份内存内容快照；事件语义收窄为
        "精确内容已返回调用方"。泛查询不调用本方法。
        """
        from llm_loop.core.run_context import current_run_generation
        from llm_loop.introspection.settlement import emit_knowledge_read

        emit_knowledge_read(
            self._knowledge_read_sink,
            kind=kind,
            ref=ref,
            version=version,
            session_id=session_id,
            run=current_run_generation.get() or "",
        )

    def _search_rule(self, query: str, limit: int, session_id: str) -> list[dict]:
        """TASK-ac085ab1-002/003: 规则检索 + 精确水合打点 + 反馈注释通道.

        注释通道数据取自 EventStore 投影（rule_feedback_projection），携带反馈
        水位与 pending_count；不改规则排序、不改规则权威（authority=rule_sot）。
        """
        rows = self._rule_index.search(query, limit)
        if rows and rows[0].get("hydrated") is True:
            content = str(rows[0].get("content") or "")
            version = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
            self._emit_knowledge_read(
                kind="rule",
                ref=str(rows[0].get("rule_ref") or ""),
                version=version,
                session_id=session_id,
            )
        projection = self._rule_feedback_projection
        if projection is None or not rows:
            return rows
        annotated: list[dict] = []
        for row in rows:
            try:
                ref = str(row.get("rule_ref") or row.get("id") or "")
                data = projection(ref) if ref else None
                annotated.append({**row, **data} if data else row)
            except Exception:  # noqa: BLE001 — 注释通道 fail-open
                annotated.append(row)
        return annotated

    @staticmethod
    def _heldout_row_text(row: dict) -> str:
        """整行最终序列化（不挑字段）：注解阶段注入的任何键都在检查面内.

        第一轮按字段白名单拼接待检文本，漏掉了注解阶段新增的键
        （freshness_refs / recent_issue 等）——漏检的根因正是"挑选"本身。
        改为对整行 ``json.dumps(..., ensure_ascii=False, default=str)`` 检查：
        dict/list 叶子值天然展平进序列化文本，非 str 叶子经 default=str 进入，
        行里任何来源（卡片投影、usage_feedback 合并、card_age 注记）的模型
        文本都无法借"字段不在表里"逃逸。行均为小对象，每行一次调用可接受。
        """
        return json.dumps(row, ensure_ascii=False, default=str)

    def _filter_heldout_rows(self, rows: list[dict], *, kind: str) -> list[dict]:
        """held-out 读侧可见过滤（fail-open，eval/rules/holdout.md §4）.

        在行生成（含 limit 截断）与**全部注解完成之后**逐行整行检查：命中
        探针的行直接丢弃——不补位（不把截断外的下一行提上来）、不重排、
        不改行结构。调用方契约：必须先跑 ``_annotate_usage`` /
        ``annotate_card_age`` / 语义卡构造，再调本方法——否则注解阶段注入
        的字段（如 usage_feedback 的 recent_issue）会绕过过滤（P1-B 回流
        的根因）；knowledge_read 打点必须在本方法之后（被丢弃的行未"返回
        给调用方"）。
        guard unavailable/内部异常由 check_text 映射为非 blocked → 放行；
        丢弃事实写入 ``self._last_heldout_filter``（``{"dropped": int,
        "task_ids": [str, ...]}``，search() 入口重置为 None），kind=all 时
        method/experience 两条路径的计数自然累加。每次丢弃记一条 INFO 日志，
        只含 kind/task_id/类别（task_id/statement_probe），绝不携带行正文
        （``kind`` 由调用方传入固定字面量，不取行内可控值）。
        """
        kept: list[dict] = []
        for row in rows:
            verdict = heldout_guard.check_text(self._heldout_row_text(row))
            if verdict.get("status") == "blocked":
                stat = self._last_heldout_filter
                if stat is None:
                    stat = {"dropped": 0, "task_ids": []}
                    self._last_heldout_filter = stat
                stat["dropped"] += 1
                task_id = str(verdict.get("task_id") or "")
                if task_id and task_id not in stat["task_ids"]:
                    stat["task_ids"].append(task_id)
                _LOGGER.info(
                    "heldout read filter dropped row: kind=%s reason=%s task_id=%s",
                    kind,
                    verdict.get("reason"),
                    task_id,
                )
                continue
            kept.append(row)
        return kept

    def _search_method(self, query: str, limit: int, *, session_id: str = "") -> list[dict]:
        """Method discovery uses lexical cards plus optional semantic RRF.

        Exact stable refs remain exact hydration and never go through semantic fallback.
        Semantic recall only broadens discovery; applicability stays ``not_evaluated``.
        """
        if self._method_store is None:
            return []
        raw = str(query or "").strip()
        if raw.lower().startswith("method:"):
            # P1-B 读侧修复：过滤必须在 _annotate_usage（usage_feedback 的
            # recent_issue 合并）**之后**——第一轮先过滤后注解，note 回流字段
            # 绕过了过滤；knowledge_read 打点仍在过滤之后（丢弃行未返回调用方）。
            rows = self._filter_heldout_rows(
                self._annotate_usage(self._method_store.list(raw, limit), side="method"),
                kind="method",
            )
            for row in rows:
                # 打点仅发生在精确水合成功路径；版本=同一份内存记录快照的 content_hash
                self._emit_knowledge_read(
                    kind="method",
                    ref=str(row.get("key") or ""),
                    version=str(row.get("content_hash") or ""),
                    session_id=session_id,
                )
            return rows
        keyword_limit = max(limit * 4, 20)
        keyword = self._method_store.list(raw, keyword_limit)
        if (
            not self._semantic_method_enabled
            or self._semantic is None
            or not self._semantic.semantic_available()
            or not raw
        ):
            return self._filter_heldout_rows(  # held-out 读侧可见过滤（limit 截断后，不补位）
                self._annotate_usage(  # EVO-20260923-6fe23c9b F2(b) + EVO-20261014-7299aec2
                    annotate_card_age(keyword[:limit]), side="method"
                ),
                kind="method",
            )
        result = self._semantic.search(
            raw,
            top_k=limit,
            scope="method",
            method=self._method_store,
            keyword_results=keyword,
        )
        rows: list[dict] = []
        failures = 0
        for hit in result.entries:
            ref = str(hit.get("key") or "")
            record = self._method_store.get(ref)
            if record is None:
                failures += 1
                continue
            card = record.card()
            card["_method_semantic_discovery"] = True
            if record.freshness_refs:
                card["freshness"] = self._method_store.freshness(record.method_ref)
            rows.append(card)
        rows = self._annotate_usage(  # EVO-20260923-6fe23c9b F2(b) + EVO-20261014-7299aec2
            annotate_card_age(rows[:limit]), side="method"
        )
        self._store_semantic_diagnostics(
            result,
            scope="method",
            canonical_hydration_failures=failures,
            rows=rows,
        )
        return self._filter_heldout_rows(rows, kind="method")

    def _search_experience(
        self,
        query: str,
        limit: int,
        *,
        record_kind: str | None = "experience",
        session_id: str = "",
    ) -> list[dict]:
        """P1-2/P1-B: typed discovery with exact ``experience:<id>`` hydration.

        Exact refs remain historically traceable regardless of record_kind. Broad discovery
        is where lesson vs positive experience is separated.
        """
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
                self._last_semantic_diagnostics = None
                stem = exact.removesuffix(".md")
                # P1-B 读侧修复：过滤必须在 _annotate_usage（usage_feedback 的
                # recent_issue 合并）**之后**；knowledge_read 打点仍在过滤之后
                # （丢弃行未返回调用方）。
                rows = self._filter_heldout_rows(
                    self._annotate_usage(  # EVO-20261014-7299aec2
                        [self._experience_store.to_hydrated_record(stem, doc)][:limit],
                        side="experience",
                    ),
                    kind="experience",
                )
                if rows:
                    # TASK-ac085ab1-002: 精确水合成功路径打点；版本哈希取自同一份 doc 快照
                    try:
                        version = hashlib.sha256(doc.to_md().encode("utf-8")).hexdigest()
                    except Exception:  # noqa: BLE001 — 打点失败不阻断水合
                        version = ""
                    self._emit_knowledge_read(
                        kind=str(getattr(doc, "record_kind", "") or "experience"),
                        ref=f"experience:{stem}",
                        version=version,
                        session_id=session_id,
                    )
                return rows
        # R3(P0-3): 三态扫描 Outcome——诊断独立于 results[:limit] 截断照常回填
        #（kind=all 聚合中 experience 记录被挤出返回集时，诊断仍到达模型）
        outcome = self._experience_store.search_outcome(
            query,
            limit,
            record_kind=record_kind,
        )
        self._last_diagnostics = {
            "scanned": outcome.scanned_count,
            "degraded": outcome.degraded_count,
            "skipped": outcome.skipped_count,
            "scan_error": outcome.scan_error,
        }
        semantic_diag = getattr(self._experience_store, "last_semantic_diagnostics", None)
        self._last_semantic_diagnostics = dict(semantic_diag or {}) or None
        return self._filter_heldout_rows(  # held-out 读侧可见过滤（limit 截断后，不补位）
            self._annotate_usage(  # EVO-20260923-6fe23c9b F2(b) + EVO-20261014-7299aec2
                annotate_card_age(outcome.records), side="experience"
            ),
            kind="experience",
        )

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
        self,
        query: str,
        limit: int,
        session_id: str = "",
        _skip_shadow: bool = False,
    ) -> list[dict]:
        """R3: keyword search plus exact ``memory:<id>`` hydration with scope isolation.

        ``_skip_shadow``: 影子探针的变体检索内部复用本方法时置 True，防递归旁路。
        """
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
        if (
            self._semantic_memory_enabled
            and self._semantic is not None
            and self._semantic.semantic_available()
        ):
            result = self._semantic.search(
                raw,
                top_k=limit,
                scope="memory",
                session_id=session_id,
                memory=self._memory,
                keyword_results=keyword_dicts,
            )
            final = self._canonical_memory_rows(
                result,
                keyword_dicts,
                limit=limit,
                session_id=session_id,
            )
            # REPORT-20260924 多查询融合影子模式：旁路测量，返回值不受任何影响
            probe = getattr(self, "_multiquery_shadow", None)
            if probe is not None and getattr(probe, "enabled", False) and not _skip_shadow:
                probe.run(
                    raw,
                    limit,
                    session_id,
                    search_fn=lambda t: [
                        str(h.get("id") or "")
                        for h in self._search_memory(
                            t, limit, session_id=session_id, _skip_shadow=True
                        )
                    ],
                    primary_ids=[str(h.get("id") or "") for h in final],
                )
            return final
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
        if (
            self._semantic_archive_enabled
            and self._semantic is not None
            and self._semantic.semantic_available()
        ):
            result = self._semantic.search(
                query,
                top_k=limit,
                scope="archive",
                session_id=session_id,
                archive=self._archive,
                keyword_results=keyword_hits,
            )
            return self._canonical_archive_rows(
                result,
                keyword_hits,
                limit=limit,
                session_id=session_id,
            )
        return keyword_hits

    @staticmethod
    def _copy_semantic_metadata(source: dict, target: dict, mode: str) -> dict:
        for key in ("_rrf_score", "_semantic_score", "_entity_score"):
            if key in source:
                target[key] = source[key]
        if mode != "keyword":
            target["note"] = f"语义检索生效（mode={mode}）"
        return target

    def _store_semantic_diagnostics(
        self,
        result: Any,
        *,
        scope: str,
        canonical_hydration_failures: int,
        rows: list[dict],
    ) -> None:
        diag = dict(getattr(result, "diagnostics", {}) or {})
        diag["scope"] = scope
        diag["canonical_hydration_failures"] = canonical_hydration_failures
        diag["empty_render_count"] = sum(
            1 for row in rows if not str(row.get("summary") or "").strip()
        )
        self._last_semantic_diagnostics = diag

    def _canonical_memory_rows(
        self,
        result: Any,
        keyword_hits: list[dict],
        *,
        limit: int,
        session_id: str,
    ) -> list[dict]:
        """将 semantic 排名结果按 stable memory id 回源为 canonical record."""
        rows: list[dict] = []
        seen: set[str] = set()
        failures = 0
        for hit in list(result.entries):
            entry_id = str(hit.get("id") or "")
            if not entry_id:
                failures += 1
                continue
            if entry_id in seen:
                continue
            entry = self._memory._by_id(entry_id) if self._memory is not None else None
            if entry is None or not self._memory_visible_in_session(entry, session_id):
                failures += 1
                continue
            row = self._copy_semantic_metadata(
                hit, self._memory_record(entry), str(result.mode)
            )
            rows.append(row)
            seen.add(entry_id)
            if len(rows) >= limit:
                break
        # fail-open: semantic projection 不得抹掉原本可见的 lexical hit.
        for hit in keyword_hits:
            if len(rows) >= limit:
                break
            entry_id = str(hit.get("id") or "")
            if entry_id and entry_id in seen:
                continue
            rows.append(dict(hit))
            if entry_id:
                seen.add(entry_id)
        rows = rows[:limit]
        self._store_semantic_diagnostics(
            result,
            scope="memory",
            canonical_hydration_failures=failures,
            rows=rows,
        )
        return rows

    def _canonical_archive_rows(
        self,
        result: Any,
        keyword_hits: list[dict],
        *,
        limit: int,
        session_id: str,
    ) -> list[dict]:
        """将 semantic 排名结果按 stable archive id 回源为 canonical record."""
        rows: list[dict] = []
        seen: set[str] = set()
        failures = 0
        lexical_by_id = {
            str(hit.get("id") or ""): hit
            for hit in keyword_hits
            if str(hit.get("id") or "")
        }
        for hit in list(result.entries):
            entry_id = str(hit.get("id") or "")
            if not entry_id:
                failures += 1
                continue
            if entry_id in seen:
                continue
            canonical: dict[str, object] | None = lexical_by_id.get(entry_id)
            if canonical is None and session_id and self._archive is not None:
                getter = getattr(self._archive, "get_by_id", None)
                if callable(getter):
                    fetched = getter(session_id, entry_id)
                    if isinstance(fetched, dict):
                        canonical = fetched
            if canonical is None:
                failures += 1
                continue
            row = dict(canonical)
            row.setdefault("kind", "archive")
            if not str(row.get("summary") or "").strip():
                row["summary"] = str(row.get("content_preview") or "")[:500]
            row = self._copy_semantic_metadata(hit, row, str(result.mode))
            rows.append(row)
            seen.add(entry_id)
            if len(rows) >= limit:
                break
        for hit in keyword_hits:
            if len(rows) >= limit:
                break
            entry_id = str(hit.get("id") or "")
            if entry_id and entry_id in seen:
                continue
            row = dict(hit)
            if not str(row.get("summary") or "").strip():
                row["summary"] = str(row.get("content_preview") or "")[:500]
            rows.append(row)
            if entry_id:
                seen.add(entry_id)
        rows = rows[:limit]
        self._store_semantic_diagnostics(
            result,
            scope="archive",
            canonical_hydration_failures=failures,
            rows=rows,
        )
        return rows

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
        # EVO-20260918: 多词分词 AND + ts 入检索域（与 _jsonl_search 对齐）
        terms = _query_terms(query)
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
                        str(v)
                        for v in (
                            entry.get("ts", ""),
                            entry.get("eval_id", ""),
                            entry.get("session_id", ""),
                            entry.get("trigger", ""),
                            entry.get("summary", ""),
                            entry.get("note", ""),
                        )
                    ).lower()
                    if terms and not _hay_matches(hay, terms):
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
