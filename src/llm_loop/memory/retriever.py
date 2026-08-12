"""语义检索器 SemanticRetriever（design.md §3.2.2.2 / FR-P1-RET 系列）.

边界说明（M11）: 本模块提供跨 memory/archive 的统一语义召回算法（预算/降级）;
记忆消息构造在 memory/retrieve.py（build_memory_messages），本模块被其与 RecordSearcher 共同复用。

语义召回（预算内）→ 关键词兜底 → 如实降级标注（FR-P1-RET-01/02/04/05）。
- embedding 惰性计算并缓存（避免每次全量重算）
- 整个语义检索受 RETRIEVE_TIMEOUT_S 预算约束，超时转关键词兜底
- 嵌入失败/不可用 → 关键词兜底 + note 如实标注
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from llm_loop.memory.embedder import Embedder, cosine_similarity

logger = logging.getLogger(__name__)

# ── Phase 5: 实体提取（mem0 式 Entity Linking 轻量实现，零依赖规则）──
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z]{2,}\b")  # 首字母大写、长度≥3 的英文专有名词
# 中文实体启发式（无空格/大小写，用常见实体后缀识别；零依赖）
_CN_ENTITY_SUFFIXES = (
    "公司", "集团", "系统", "项目", "模型", "框架", "平台", "协议", "语言",
    "工具", "部门", "团队", "城市", "国家", "机构", "组织", "企业", "产品",
    "引擎", "数据库", "服务", "库", "框架", "版本", "标准", "规范", "接口",
)
_CN_ENTITY_RE = re.compile(
    r"[\u4e00-\u9fff]{2,12}(" + "|".join(_CN_ENTITY_SUFFIXES) + r")"
)
_QUOTED_ENTITY_RE = re.compile(r'[“「『]([\u4e00-\u9fffA-Za-z0-9_]{2,20})[”」』]')
_ENTITY_STOP = {
    "The", "This", "That", "These", "Those", "What", "Which", "When",
    "Where", "Who", "How", "Why", "And", "But", "For", "Not", "You",
    "Your", "Please", "Hello", "Hi", "I", "We", "They", "He", "She",
    "It", "Are", "Is", "Was", "Were", "Do", "Does", "Did", "Can",
    "Could", "Should", "Would", "Will", "May", "Might", "Must",
}


def extract_entities(text: str) -> list[str]:
    """提取文本中的实体（专有名词）: 英文首字母大写词 + 中文实体后缀/引号专名.

    零依赖、确定性（Phase 5 + 中文增强, mem0 Entity Linking 轻量版）；
    中文启发式: ①常见实体后缀（如"智能体系统"→ 取"智能体系统"整词）
    ②引号/书名号包裹的专名（如"「记忆引擎」"）。
    """
    if not text:
        return []
    ents: list[str] = []
    # 英文专有名词（原规则）
    for m in _ENTITY_RE.finditer(text):
        w = m.group(0)
        if w not in _ENTITY_STOP and w.lower() not in {"llm", "api", "ai", "cli", "json", "yaml", "sql", "http", "https"}:
            ents.append(w)
    # 中文: 实体后缀词（整词保留，如 "记忆系统"）
    for m in _CN_ENTITY_RE.finditer(text):
        w = m.group(0)
        if len(w) >= 2:
            ents.append(w)
    # 中文/混合: 引号包裹专名
    for m in _QUOTED_ENTITY_RE.finditer(text):
        ents.append(m.group(1))
    # 去重保序
    seen: list[str] = []
    for e in ents:
        if e not in seen:
            seen.append(e)
    return seen


RetrieveMode = Literal["semantic", "keyword", "mixed", "entity", "mixed_entity"]


@dataclass
class RetrievalResult:
    """检索结果（mode/note 如实标注实际生效方式，FR-P1-RET-04）."""

    entries: list[dict] = field(default_factory=list)
    mode: RetrieveMode = "keyword"
    note: str = ""


class SemanticRetriever:
    """语义检索器（RRF 多信号融合: 语义 + 关键词 → 如实降级标注）.

    Phase 3（EVO 深化）: 融合算法从"语义优先+关键词补充"线性融合升级为
    RRF（Reciprocal Rank Fusion）: score(d) = Σ_i 1/(k + rank_i(d))，k=60。
    Phase 5: 三通道（语义排名 + 关键词排名 + 实体排名）各自贡献，
    多信号同时命中者得分更高（mem0 式 Entity Linking 轻量版）。
    """

    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        timeout_s: float = 1.0,
        semantic_top_k: int = 20,
        threshold: float = 0.22,
        memory_dir: str | Path | None = None,
        archive_dir: str | Path | None = None,
    ) -> None:
        self.embedder = embedder
        self.timeout_s = timeout_s
        self.semantic_top_k = semantic_top_k
        self.threshold = threshold
        # M59 配置面收敛: 运行时动态 top_k 提供器（AI 经 adjust_strategy 可调；未注入用构造值）
        self._top_k_provider: Callable[[], int] | None = None
        self._mem_emb_cache: dict[str, list[float]] = {}
        self._arch_emb_cache: dict[str, list[float]] = {}
        if memory_dir:
            self._load_emb_cache(Path(memory_dir) / "embeddings.json", self._mem_emb_cache)
        if archive_dir:
            self._load_emb_cache(Path(archive_dir) / "embeddings.json", self._arch_emb_cache)
        self._mem_cache_path = Path(memory_dir) / "embeddings.json" if memory_dir else None
        self._arch_cache_path = Path(archive_dir) / "embeddings.json" if archive_dir else None

    def _load_emb_cache(self, path: Path, cache: dict) -> None:
        if path.exists():
            from contextlib import suppress

            with suppress(json.JSONDecodeError, OSError):
                cache.update(json.loads(path.read_text(encoding="utf-8")))

    def _persist_emb_cache(self, path: Path | None, cache: dict) -> None:
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ── 语义可用性 ──
    def semantic_available(self) -> bool:
        return self.embedder is not None and self.embedder.provider != "none"

    # ── M59: 运行时动态语义召回上限 ──
    def set_top_k_provider(self, fn: Callable[[], int]) -> None:
        """注入动态 top_k 提供器（AI 经 adjust_strategy 可调；未注入用构造值）.

        fn 返回整数；调用失败/非法回退构造值（fail-open 不阻断检索）。
        """
        self._top_k_provider = fn

    def _semantic_top_k(self) -> int:
        if self._top_k_provider is not None:
            try:
                val = self._top_k_provider()
                if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                    return val
            except Exception:  # noqa: BLE001 — 提供器异常回退构造值
                pass
        return self.semantic_top_k

    # ── 主入口 ──
    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        scope: str = "all",
        session_id: str = "",
        memory: Any | None = None,
        archive: Any | None = None,
        keyword_results: list[dict] | None = None,
    ) -> RetrievalResult:
        """语义检索（预算内）→ 与关键词结果融合.

        Args:
            query: 检索词.
            scope: "memory" / "archive" / "all".
            keyword_results: 调用方已算的关键词结果（用于融合去重）.
        """
        if not self.semantic_available() or self.embedder is None:
            return RetrievalResult(entries=keyword_results or [], mode="keyword", note="")

        start = time.monotonic()
        try:
            q_vec = self.embedder.embed(query)
        except Exception as exc:  # noqa: BLE001
            return RetrievalResult(
                entries=keyword_results or [],
                mode="keyword",
                note=f"语义检索不可用：{exc}，已降级为关键词检索",
            )
        if q_vec is None:
            return RetrievalResult(entries=keyword_results or [], mode="keyword", note="")

        # 语义召回（预算内）
        semantic_hits: list[dict] = []
        candidates = self._candidates(scope, session_id, memory, archive)
        for c in candidates:
            if time.monotonic() - start > self.timeout_s:
                return RetrievalResult(
                    entries=keyword_results or [],
                    mode="keyword",
                    note="语义检索超时，已降级为关键词检索",
                )
            vec = self._embed_cached(c, scope)
            if vec is None:
                continue
            score = cosine_similarity(q_vec, vec)
            if score >= self.threshold:
                semantic_hits.append({**c, "_semantic_score": round(score, 3)})
        semantic_hits.sort(key=lambda x: x["_semantic_score"], reverse=True)
        semantic_hits = semantic_hits[: self._semantic_top_k()]

        # Phase 5: 实体通道（Entity Linking，轻量规则）
        entity_hits: list[dict] = []
        q_entities = extract_entities(query)
        if q_entities:
            for c in candidates:
                if time.monotonic() - start > self.timeout_s:
                    break  # 实体通道受同一时间预算约束，超时跳过（不阻塞）
                overlap = self._entity_overlap(q_entities, extract_entities(c.get("content", "")))
                if overlap > 0:
                    entity_hits.append({**c, "_entity_score": overlap})
            entity_hits.sort(key=lambda x: x["_entity_score"], reverse=True)
            entity_hits = entity_hits[: self._semantic_top_k()]

        # RRF 多信号融合（Phase 3+5）: 语义 + 关键词 + 实体 → 融合重排
        fused = self._rrf_fuse(
            semantic_hits, keyword_results or [], entity_hits, top_k=top_k
        )
        # mode 如实标注（FR-P1-RET-04）: 多信号参与 → mixed；实体独立命中 → entity
        signals = sum(1 for x in (semantic_hits, keyword_results, entity_hits) if x)
        if signals >= 2:
            mode: RetrieveMode = "mixed"
        elif entity_hits:
            mode = "mixed_entity"
        elif semantic_hits:
            mode = "semantic"
        else:
            mode = "keyword"
        return RetrievalResult(entries=fused, mode=mode, note="")

    # ── 候选条目（惰性向量化）──
    def _candidates(self, scope: str, session_id: str, memory: Any, archive: Any) -> list[dict]:
        cands: list[dict] = []
        if scope in {"memory", "all"} and memory is not None:
            for e in memory.all():
                cands.append(
                    {
                        "kind": "memory",
                        "id": e.id,
                        "content": f"{e.content} {' '.join(e.keywords)}",
                        "key": f"memory:{e.id}",
                    }
                )
        if scope in {"archive", "all"} and archive is not None and session_id:
            hits = archive.search(session_id, "", limit=10000)
            for h in hits:
                cands.append(
                    {
                        "kind": "archive",
                        "id": h.get("id", ""),
                        "content": f"{h.get('summary', '')} {' '.join(h.get('key_facts', []) or [])}",
                        "key": f"archive:{h.get('id', '')}",
                    }
                )
        return cands

    def _embed_cached(self, cand: dict, scope: str) -> list[float] | None:
        cache = self._mem_emb_cache if scope == "memory" else self._arch_emb_cache
        key = cand["key"]
        if key not in cache:
            vec = self.embedder.embed(cand["content"])  # type: ignore[union-attr]
            if vec is None:
                return None
            cache[key] = vec
            path = self._mem_cache_path if scope == "memory" else self._arch_cache_path
            self._persist_emb_cache(path, cache)
        return cache.get(key)

    def _rrf_fuse(
        self,
        semantic_hits: list[dict],
        keyword_results: list[dict],
        entity_hits: list[dict] | None = None,
        *,
        top_k: int,
        k: int = 60,
    ) -> list[dict]:
        """RRF 融合: score(d) = Σ_i 1/(k + rank_i(d)).

        - 语义通道排名 = semantic_hits 顺序（已按 _semantic_score 降序）
        - 关键词通道排名 = keyword_results 顺序（调用方已按关键词得分排序）
        - 实体通道排名 = entity_hits 顺序（已按 _entity_score 降序，Phase 5）
        - 多通道同时命中的条目获得叠加得分（多信号增强）
        - 附加 _rrf_score 便于审计/调试；各通道原始分保留
        """
        fused: dict[str, list] = {}
        channels = [("语义", semantic_hits), ("关键词", keyword_results), ("实体", entity_hits or [])]
        for _label, hits in channels:
            for rank, h in enumerate(hits, start=1):
                key = self._entry_key(h)
                contrib = 1.0 / (k + rank)
                if key in fused:
                    fused[key][0] += contrib
                else:
                    fused[key] = [contrib, dict(h)]
        ranked = sorted(fused.values(), key=lambda x: x[0], reverse=True)
        for score, entry in ranked:
            entry["_rrf_score"] = round(score, 4)
        return [entry for _, entry in ranked[:top_k]]

    @staticmethod
    def _entity_overlap(query_entities: list[str], candidate_entities: list[str]) -> int:
        """实体重叠数（query 实体 ∩ 候选条目实体）."""
        if not query_entities or not candidate_entities:
            return 0
        q_set = set(query_entities)
        return sum(1 for e in candidate_entities if e in q_set)

    @staticmethod
    def _entry_key(h: dict) -> str:
        return str(h.get("key") or h.get("id") or h.get("file") or "")
