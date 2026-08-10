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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from llm_loop.memory.embedder import Embedder, cosine_similarity

logger = logging.getLogger(__name__)

RetrieveMode = Literal["semantic", "keyword", "mixed"]


@dataclass
class RetrievalResult:
    """检索结果（mode/note 如实标注实际生效方式，FR-P1-RET-04）."""

    entries: list[dict] = field(default_factory=list)
    mode: RetrieveMode = "keyword"
    note: str = ""


class SemanticRetriever:
    """语义检索器（语义 → 关键词兜底 → 如实降级标注）."""

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
        semantic_hits = semantic_hits[: self.semantic_top_k]

        # 融合去重（语义优先 + 关键词补充至 top_k）
        fused: list[dict] = []
        seen: set[str] = set()
        for h in semantic_hits:
            key = self._entry_key(h)
            if key not in seen:
                seen.add(key)
                fused.append(h)
        for k in keyword_results or []:
            key = self._entry_key(k)
            if key not in seen and len(fused) < top_k:
                seen.add(key)
                fused.append(k)
        mode: RetrieveMode = "semantic" if semantic_hits else "keyword"
        if semantic_hits and keyword_results:
            mode = "mixed"
        return RetrievalResult(entries=fused[:top_k], mode=mode, note="")

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

    @staticmethod
    def _entry_key(h: dict) -> str:
        return str(h.get("key") or h.get("id") or h.get("file") or "")
