"""语义检索器 SemanticRetriever（design.md §3.2.2.2 / FR-P1-RET 系列）.

边界说明（M11）: 本模块提供跨 memory/archive 的统一语义召回算法（预算/降级）;
显式记忆检索由 RecordSearcher/MemoryStore 使用；memory/retrieve.py 仅保留词法关键词提取。

语义召回（预算内）→ 关键词兜底 → 如实降级标注（FR-P1-RET-01/02/04/05）。
- embedding 惰性计算并缓存（避免每次全量重算）
- 整个语义检索受 RETRIEVE_TIMEOUT_S 预算约束，超时转关键词兜底
- 嵌入失败/不可用 → 关键词兜底 + note 如实标注
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

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
    diagnostics: dict[str, Any] = field(default_factory=dict)


class SemanticRetriever:
    """语义检索器（RRF 多信号融合: 语义 + 关键词 → 如实降级标注）.

    Phase 3（EVO 深化）: 融合算法从"语义优先+关键词补充"线性融合升级为
    RRF（Reciprocal Rank Fusion）: score(d) = Σ_i 1/(k + rank_i(d))，k=60。
    Phase 5: 三通道（语义排名 + 关键词排名 + 实体排名）各自贡献，
    多信号同时命中者得分更高（mem0 式 Entity Linking 轻量版）。
    """

    # Runtime auto-prewarm is only an incremental repair path. Full cold-corpus
    # warmup belongs to the explicit scripts/embedding_warmup.py job.
    _BACKGROUND_PREWARM_MAX = 32
    # Service startup must not synchronously embed an unbounded growing Method pool.
    # Deferred candidates remain available to keyword retrieval and incremental warmup.
    _METHOD_STARTUP_WARMUP_MAX = 128

    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        timeout_s: float = 1.0,
        semantic_top_k: int = 20,
        threshold: float | None = None,
        memory_dir: str | Path | None = None,
        archive_dir: str | Path | None = None,
        fallback_embedder: Embedder | None = None,
    ) -> None:
        self.embedder = embedder
        # T0-B（2026-09-16）: 主嵌入（生产 api@8765）不可用时整套回退 hash——查询向量/
        # 阈值/缓存文件三件套同空间切换（引擎级），绝不把 fallback 向量写进主版本
        # 缓存文件（T8 版本化缓存所防的互踩事故在回退路径同样成立）。
        self.fallback_embedder = fallback_embedder
        self.fallback_engaged = 0
        self._fb_state: dict | None = None  # 惰性构建：首次回退时才加载 hash 版缓存
        self.timeout_s = timeout_s
        self.semantic_top_k = semantic_top_k
        # T7: threshold=None → 按 embedder 相似度分布取校准默认
        if threshold is None:
            threshold = self._default_threshold(embedder)
        self.threshold = threshold
        # M59 配置面收敛: 运行时动态 top_k 提供器（AI 经 adjust_strategy 可调；未注入用构造值）
        self._top_k_provider: Callable[[], int] | None = None
        self._mem_emb_cache: dict[str, list[float]] = {}
        self._arch_emb_cache: dict[str, list[float]] = {}
        self._method_emb_cache: dict[str, list[float]] = {}
        self._experience_emb_cache: dict[str, list[float]] = {}
        self._cache_state_lock = threading.RLock()
        self._cache_file_stamps: dict[str, tuple[int, int, int] | None] = {}
        self._prewarm_state_lock = threading.Lock()
        self._prewarm_inflight = False
        self._prewarm_pending: dict[str, dict] = {}
        self._last_background_diag: dict[str, Any] = {
            "prewarm_ms": 0.0,
            "cache_flush_ms": 0.0,
            "missing_count": 0,
            "completed": True,
            "error": "",
        }
        self.last_rank_texts_diagnostics: dict[str, Any] = {}
        # T8 缓存文件按向量版本分离（embeddings-<tag>.json）：不同 provider/算法
        # 各写各的文件，根治"两代代码/两种 embedder 共写 embeddings.json 互踩覆写"
        # （2026-09-16 实测事故：worktree 旧代码无版本键整体覆写，1487 条 bge 缓存丢失）。
        # 旧 embeddings.json 仅作回退读（版本匹配才载入）；persist 一律写 tag 文件。
        if memory_dir:
            self._mem_emb_cache = self._load_emb_cache_versioned(Path(memory_dir))
        if archive_dir:
            self._arch_emb_cache = self._load_emb_cache_versioned(Path(archive_dir))
        self._mem_cache_path = self._cache_path(Path(memory_dir)) if memory_dir else None
        self._arch_cache_path = self._cache_path(Path(archive_dir)) if archive_dir else None
        self._method_cache_path: Path | None = None
        self._experience_cache_path: Path | None = None
        self.last_cached_rank_diagnostics: dict[str, Any] = {}

    def _primary_engine(self) -> dict[str, Any]:
        return {
            "embedder": self.embedder,
            "threshold": self.threshold,
            "mem_cache": self._mem_emb_cache,
            "arch_cache": self._arch_emb_cache,
            "mem_path": self._mem_cache_path,
            "arch_path": self._arch_cache_path,
            "method_cache": self._method_emb_cache,
            "method_path": self._method_cache_path,
            "experience_cache": self._experience_emb_cache,
            "experience_path": self._experience_cache_path,
        }

    def configure_experience_cache_dir(self, cache_dir: str | Path) -> None:
        """Bind persistent Experience semantic cache to canonical shared runtime state."""
        directory = Path(cache_dir)
        self._experience_emb_cache = self._load_emb_cache_versioned(directory)
        self._experience_cache_path = self._cache_path(directory)

    def warm_experience_store(self, experience: Any, *, max_passes: int = 3) -> dict[str, Any]:
        """Warm active Experience/Lesson candidate vectors before semantic enablement."""
        if (
            experience is None
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
        ):
            return {"requested": False, "initial_missing": 0, "remaining_missing": 0}
        candidates_by_key: dict[str, dict[str, Any]] = {}
        for record_kind in ("experience", "lesson"):
            for candidate in experience.semantic_candidates(record_kind=record_kind):
                key = str(candidate.get("key") or "")
                if key:
                    candidates_by_key[key] = dict(candidate)
        candidates = list(candidates_by_key.values())
        engine = self._primary_engine()
        initial_missing = self._missing_candidate_count(candidates, engine)
        started = time.monotonic()
        passes = 0
        previous_missing = initial_missing
        while previous_missing and passes < max(1, int(max_passes)):
            passes += 1
            pre_sizes = self._prewarm_batch(candidates, engine, deadline=None)
            self._flush_dirty_caches(engine, pre_sizes)
            remaining = self._missing_candidate_count(candidates, engine)
            if remaining >= previous_missing:
                previous_missing = remaining
                break
            previous_missing = remaining
        return {
            "requested": True,
            "candidate_count": len(candidates),
            "initial_missing": initial_missing,
            "remaining_missing": previous_missing,
            "passes": passes,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
        }

    def schedule_experience_candidate(self, candidate: dict[str, Any]) -> bool:
        """Schedule one newly persisted Experience/Lesson vector outside the write path."""
        if (
            not candidate
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
            or str(candidate.get("kind") or "") not in {"experience", "lesson"}
            or not str(candidate.get("key") or "")
        ):
            return False
        return self._schedule_background_prewarm(
            [dict(candidate)], self._primary_engine()
        )

    def warm_memory_store(self, memory: Any, *, max_passes: int = 3) -> dict[str, Any]:
        """Synchronously warm existing memory before a semantic-enabled runtime is ready.

        This is a startup/qualification gate, never a foreground search path. It allows
        explicit semantic enablement to begin with a hot cache while search itself remains
        strictly fail-open and non-blocking.
        """
        if (
            memory is None
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
        ):
            return {"requested": False, "initial_missing": 0, "remaining_missing": 0}
        engine = self._primary_engine()
        candidates = self._memory_cache_candidates(memory)
        initial_missing = self._missing_candidate_count(candidates, engine)
        started = time.monotonic()
        passes = 0
        previous_missing = initial_missing
        while previous_missing and passes < max(1, int(max_passes)):
            passes += 1
            pre_sizes = self._prewarm_batch(candidates, engine, deadline=None)
            self._flush_dirty_caches(engine, pre_sizes)
            remaining = self._missing_candidate_count(candidates, engine)
            if remaining >= previous_missing:
                previous_missing = remaining
                break
            previous_missing = remaining
        return {
            "requested": True,
            "initial_missing": initial_missing,
            "remaining_missing": previous_missing,
            "passes": passes,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
        }

    def schedule_memory_entry(self, entry: Any) -> bool:
        """Schedule one newly saved/updated memory vector outside the write path."""
        if (
            entry is None
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
        ):
            return False
        entry_id = str(getattr(entry, "id", "") or "")
        if not entry_id:
            return False
        cand = {
            "kind": "memory",
            "id": entry_id,
            "content": (
                f"{getattr(entry, 'content', '')} "
                f"{' '.join(getattr(entry, 'keywords', []) or [])}"
            ).strip(),
            "key": f"memory:{entry_id}",
        }
        return self._schedule_background_prewarm([cand], self._primary_engine())

    @staticmethod
    def _archive_candidate(entry: Any) -> dict:
        entry_id = str(
            (entry.get("id") if isinstance(entry, dict) else getattr(entry, "id", ""))
            or ""
        )
        summary = str(
            (
                entry.get("summary", "")
                if isinstance(entry, dict)
                else getattr(entry, "summary", "")
            )
            or ""
        )
        key_facts = (
            entry.get("key_facts", [])
            if isinstance(entry, dict)
            else getattr(entry, "key_facts", [])
        ) or []
        return {
            "kind": "archive",
            "id": entry_id,
            "content": f"{summary} {' '.join(key_facts)}".strip(),
            "key": f"archive:{entry_id}",
        }

    def schedule_archive_entry(self, entry: Any) -> bool:
        """Schedule one durable archive entry for background vectorization."""
        if (
            entry is None
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
        ):
            return False
        cand = self._archive_candidate(entry)
        if not cand["id"]:
            return False
        return self._schedule_background_prewarm([cand], self._primary_engine())

    def configure_method_dir(self, method_dir: str | Path) -> None:
        """Bind Method semantic-cache storage after RuntimePaths authority is resolved."""
        directory = Path(method_dir)
        self._method_emb_cache = self._load_emb_cache_versioned(directory)
        self._method_cache_path = self._cache_path(directory)
        # Rebuild lazy fallback state so its Method cache/path uses the same authority.
        self._fb_state = None

    def warm_method_store(
        self,
        method: Any,
        *,
        max_passes: int = 3,
        max_candidates: int = _METHOD_STARTUP_WARMUP_MAX,
    ) -> dict[str, Any]:
        """Warm a bounded, status-diverse slice of Method vectors at service startup.

        The entire Method pool remains discoverable. This startup budget only bounds
        synchronous embedding work; missing vectors outside the slice are eligible for
        incremental background prewarm, while lexical recall remains available immediately.
        """
        if (
            method is None
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
        ):
            return {
                "requested": False, "candidate_count": 0,
                "warmup_candidate_count": 0, "deferred_candidates": 0,
                "initial_missing": 0, "remaining_missing": 0,
                "warmup_initial_missing": 0, "warmup_remaining_missing": 0,
                "deferred_missing": 0,
            }
        engine = self._primary_engine()
        candidates = list(method.semantic_candidates())
        warmup_limit = max(0, int(max_candidates))
        warmup_candidates = candidates[:warmup_limit]
        deferred_candidates = candidates[warmup_limit:]
        initial_missing = self._missing_candidate_count(candidates, engine)
        warmup_initial_missing = self._missing_candidate_count(warmup_candidates, engine)
        started = time.monotonic()
        passes = 0
        previous_missing = warmup_initial_missing
        while previous_missing and passes < max(1, int(max_passes)):
            passes += 1
            pre_sizes = self._prewarm_batch(warmup_candidates, engine, deadline=None)
            self._flush_dirty_caches(engine, pre_sizes)
            remaining = self._missing_candidate_count(warmup_candidates, engine)
            if remaining >= previous_missing:
                previous_missing = remaining
                break
            previous_missing = remaining
        deferred_missing = self._missing_candidate_count(deferred_candidates, engine)
        warmup_remaining_missing = previous_missing
        return {
            "requested": True,
            "candidate_count": len(candidates),
            "initial_missing": initial_missing,
            "remaining_missing": warmup_remaining_missing + deferred_missing,
            "warmup_candidate_count": len(warmup_candidates),
            "deferred_candidates": len(deferred_candidates),
            "warmup_initial_missing": warmup_initial_missing,
            "warmup_remaining_missing": warmup_remaining_missing,
            "deferred_missing": deferred_missing,
            "passes": passes,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
        }

    def schedule_method_candidate(self, candidate: dict[str, Any]) -> bool:
        """Schedule one newly persisted Method candidate for background vectorization."""
        if (
            not candidate
            or self.embedder is None
            or getattr(self.embedder, "provider", "") != "api"
        ):
            return False
        if str(candidate.get("kind") or "") != "method":
            return False
        if not str(candidate.get("key") or ""):
            return False
        return self._schedule_background_prewarm(
            [dict(candidate)], self._primary_engine()
        )

    def _cache_tag(self, embedder: Embedder | None = None) -> str:
        """向量版本 + cache-key schema → 文件名安全 tag."""
        ver = self._emb_version(embedder if embedder is not None else self.embedder)
        # ck2 binds cached vectors to candidate content, not only stable record id.
        # Keep it in a separate file so old long-lived processes can continue reading
        # their ck1 cache during rolling deployment without split-brain overwrites.
        tag = re.sub(r"[^A-Za-z0-9._-]", "_", f"{ver}-ck2")[:72]
        return tag or "legacy"

    def _cache_path(self, directory: Path, embedder: Embedder | None = None) -> Path:
        return directory / f"embeddings-{self._cache_tag(embedder)}.json"

    def _load_emb_cache_versioned(self, directory: Path) -> dict[str, list[float]]:
        """载入版本化缓存；tag 文件缺失时回退旧 embeddings.json（版本匹配才载入）."""
        cache: dict[str, list[float]] = {}
        self._load_emb_cache(self._cache_path(directory), cache)
        if not cache:
            self._load_emb_cache(directory / "embeddings.json", cache)
        return cache

    def _emb_version(self, embedder: Embedder | None = None) -> str:
        """当前 embedder 向量算法版本（T6: 缓存按版本校验，防新旧向量混用）."""
        target = self.embedder if embedder is None else embedder
        if target is not None:
            return str(getattr(target, "vector_version", "") or "")
        return ""

    @staticmethod
    def _default_threshold(embedder: Embedder | None) -> float:
        """T7 按 embedder 相似度分布取校准默认（实测 2026-09-16，515 真实查询 × 1487 候选）:

        - hash（字符 n-gram 词法重叠，分布低）: 0.22（原校准值，语义召回靠词法重叠）
        - api/bge-small-zh-v1.5（语义向量，中文各向异性偏高，全 pair P50=0.44）: 0.50
          → 每查询通过数 P50 1487→208（信号密度×7），top-5 切损 2.3%；相关/无关分界 ≈0.54
        """
        if embedder is not None and getattr(embedder, "provider", "") == "hash":
            return 0.22
        return 0.50

    def _fallback_state(self) -> dict | None:
        """T0-B: 惰性构建回退引擎（embedder/阈值/双缓存/双路径，hash 空间自洽）."""
        if self.fallback_embedder is None:
            return None
        if self._fb_state is None:
            state: dict = {
                "embedder": self.fallback_embedder,
                "threshold": self._default_threshold(self.fallback_embedder),
                "mem_cache": {},
                "arch_cache": {},
                "mem_path": None,
                "arch_path": None,
                "method_cache": {},
                "method_path": None,
            }
            if self._mem_cache_path is not None:
                state["mem_path"] = self._cache_path(self._mem_cache_path.parent, self.fallback_embedder)
                state["mem_cache"] = self._load_emb_cache_for(state["mem_path"], self.fallback_embedder)
            if self._arch_cache_path is not None:
                state["arch_path"] = self._cache_path(self._arch_cache_path.parent, self.fallback_embedder)
                state["arch_cache"] = self._load_emb_cache_for(state["arch_path"], self.fallback_embedder)
            if self._method_cache_path is not None:
                state["method_path"] = self._cache_path(self._method_cache_path.parent, self.fallback_embedder)
                state["method_cache"] = self._load_emb_cache_for(state["method_path"], self.fallback_embedder)
            self._fb_state = state
        return self._fb_state

    def _load_emb_cache_for(self, path: Path, embedder: Embedder | None) -> dict[str, list[float]]:
        """T0-B: 按指定 embedder 版本载入缓存（空缓存=冷启动重嵌入）."""
        cache: dict[str, list[float]] = {}
        self._load_emb_cache(path, cache, embedder)
        return cache

    def _load_emb_cache(self, path: Path, cache: dict, embedder: Embedder | None = None) -> None:
        """加载 embedding 缓存（T6 版本化：新格式带 v 键校验；旧扁平格式仅 hash-v1 兼容）."""
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ver = self._emb_version(embedder)
            if isinstance(raw, dict) and "v" in raw:
                # 新格式: {"v": <版本>, "data": {key: vec}}；版本不匹配 → 忽略
                # （fail-open 重建，防算法变更后新旧向量混用）
                if raw.get("v") == ver:
                    cache.update(raw.get("data", {}))
            elif isinstance(raw, dict) and ver == "hash-v1":
                # 旧扁平格式（v1 时代无版本键）：仅 hash-v1 兼容
                cache.update(raw)
        except (json.JSONDecodeError, OSError, TypeError):
            pass  # 损坏/异常 fail-open：忽略缓存
        self._cache_file_stamps[str(path)] = self._cache_file_stamp(path)

    def _persist_emb_cache(self, path: Path | None, cache: dict, embedder: Embedder | None = None) -> None:
        if path is None:
            return
        lock_path = path.with_suffix(path.suffix + ".lock")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+b") as fh:
                try:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                except (ImportError, OSError):
                    pass
                try:
                    disk_cache: dict[str, list[float]] = {}
                    self._load_emb_cache_for_merge(path, disk_cache, embedder)
                    with self._cache_state_lock:
                        merged = dict(disk_cache)
                        merged.update(cache)
                        payload = {
                            "v": self._emb_version(embedder),
                            "cache_key_schema": "content-v2",
                            "data": merged,
                        }
                        tmp = path.with_name(
                            f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
                        )
                        tmp.write_text(
                            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                        )
                        tmp.replace(path)
                        cache.clear()
                        cache.update(merged)
                        self._cache_file_stamps[str(path)] = self._cache_file_stamp(path)
                finally:
                    try:
                        import fcntl

                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    except (ImportError, OSError):
                        pass
        except OSError as exc:  # fail-open：缓存写失败仅影响下次冷启动
            logger.debug("embedding 缓存写失败，仅影响下次冷启动（fail-open）: %s", exc)

    def _load_emb_cache_for_merge(
        self, path: Path, cache: dict[str, list[float]], embedder: Embedder | None
    ) -> None:
        """Load one cache file without mutating freshness stamps (persist-lock helper)."""
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(raw, dict)
                and raw.get("v") == self._emb_version(embedder)
                and raw.get("cache_key_schema") == "content-v2"
            ):
                data = raw.get("data", {})
                if isinstance(data, dict):
                    cache.update(data)
        except (json.JSONDecodeError, OSError, TypeError):
            return

    @staticmethod
    def _cache_file_stamp(path: Path) -> tuple[int, int, int] | None:
        try:
            st = path.stat()
            return st.st_ino, st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def _refresh_cache_if_changed(
        self, path: Path | None, cache: dict, embedder: Embedder | None
    ) -> bool:
        if path is None:
            return False
        stamp = self._cache_file_stamp(path)
        if stamp is None or stamp == self._cache_file_stamps.get(str(path)):
            return False
        disk_cache: dict[str, list[float]] = {}
        self._load_emb_cache_for_merge(path, disk_cache, embedder)
        with self._cache_state_lock:
            cache.update(disk_cache)
            self._cache_file_stamps[str(path)] = stamp
        return True

    def _refresh_engine_caches(self, engine: dict) -> int:
        refreshed = 0
        for cache, path in (
            (engine["mem_cache"], engine["mem_path"]),
            (engine["arch_cache"], engine["arch_path"]),
            (engine.setdefault("method_cache", {}), engine.get("method_path")),
            (engine.setdefault("experience_cache", {}), engine.get("experience_path")),
        ):
            if self._refresh_cache_if_changed(path, cache, engine["embedder"]):
                refreshed += 1
        return refreshed

    @staticmethod
    def _vector_cache_key(cand: dict) -> str:
        content = str(cand.get("content") or "")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{cand.get('key', '')}#sha256:{digest}"

    # ── 语义可用性 ──
    def semantic_available(self) -> bool:
        return self.embedder is not None and self.embedder.provider != "none"

    def _embed_query_with_deadline(
        self, embedder: Embedder, query: str, deadline: float
    ) -> tuple[list[float] | None, float, str]:
        """Embed a foreground query without leaking the generic API timeout."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, 0.0, "deadline_exhausted"
        call_budget = min(remaining, max(0.05, min(0.8, self.timeout_s * 0.8)))
        started = time.monotonic()
        try:
            embed_with_timeout = getattr(embedder, "embed_with_timeout", None)
            if callable(embed_with_timeout):
                vec = embed_with_timeout(
                    query,
                    timeout_s=call_budget,
                    request_class="foreground",
                )
            else:
                vec = embedder.embed(query)
        except Exception:  # noqa: BLE001 - semantic is fail-open
            vec = None
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if vec is not None:
            return cast(list[float], vec), elapsed_ms, ""
        transport_diag = dict(getattr(embedder, "last_diagnostics", {}) or {})
        transport_error = str(transport_diag.get("error") or "")
        if transport_error == "queue_timeout":
            return None, elapsed_ms, "queue_timeout"
        if transport_error in {"ReadTimeout", "TimeoutException"}:
            return None, elapsed_ms, "query_embedding_timeout"
        reason = (
            "query_embedding_timeout"
            if elapsed_ms >= call_budget * 1000.0 * 0.9
            else "embedding_unavailable"
        )
        return None, elapsed_ms, reason

    def _background_diag_snapshot(self) -> dict[str, Any]:
        with self._prewarm_state_lock:
            return {
                "background_prewarm_inflight": self._prewarm_inflight,
                "last_prewarm_count": int(
                    self._last_background_diag.get("missing_count", 0) or 0
                ),
                "last_prewarm_ms": float(
                    self._last_background_diag.get("prewarm_ms", 0.0)
                ),
                "last_cache_flush_ms": float(
                    self._last_background_diag.get("cache_flush_ms", 0.0)
                ),
                "last_prewarm_error": str(
                    self._last_background_diag.get("error", "") or ""
                ),
            }

    def rank_texts(
        self,
        query: str,
        candidates: list[str],
        *,
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Rank an already-bounded text candidate set without changing membership.

        Used by docs search, which performs lexical candidate admission first and only
        needs semantic ordering.  Failure returns an empty list so the caller can
        truthfully fall back to its existing lexical order.
        """
        self.last_rank_texts_diagnostics = {
            "semantic_requested": bool(query and candidates),
            "semantic_effective": False,
            "semantic_fallback_reason": "",
            "candidate_count": len(candidates),
            "engine": "",
            "latency_ms": 0.0,
        }
        if not query or not candidates or not self.semantic_available():
            return []
        start = time.monotonic()
        deadline = start + self.timeout_s
        active = self.embedder
        query_vec: list[float] | None = None
        primary_error = ""
        if active is not None:
            query_vec, _query_ms, primary_error = self._embed_query_with_deadline(
                active, query, deadline
            )
        engine_name = "primary"
        if query_vec is None or active is None:
            self.last_rank_texts_diagnostics.update(
                {
                    "semantic_fallback_reason": primary_error or "embedding_unavailable",
                    "latency_ms": round((time.monotonic() - start) * 1000.0, 3),
                }
            )
            return []

        vectors: list[list[float] | None]
        batch_with_timeout = getattr(active, "embed_batch_with_timeout", None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self.last_rank_texts_diagnostics.update(
                {
                    "semantic_fallback_reason": "deadline_exhausted",
                    "engine": engine_name,
                    "latency_ms": round((time.monotonic() - start) * 1000.0, 3),
                }
            )
            return []
        if callable(batch_with_timeout):
            try:
                vectors = cast(
                    list[list[float] | None],
                    batch_with_timeout(
                        candidates,
                        timeout_s=remaining,
                        request_class="foreground",
                        chunk_size=8,
                    ),
                )
            except Exception:  # noqa: BLE001 - fail-open to lexical
                vectors = [None] * len(candidates)
        else:
            batch = getattr(active, "embed_batch", None)
            if callable(batch) and getattr(active, "provider", "") != "api":
                try:
                    vectors = cast(list[list[float] | None], batch(candidates))
                except Exception:  # noqa: BLE001
                    vectors = [None] * len(candidates)
            else:
                vectors = []
                for text in candidates:
                    if time.monotonic() >= deadline:
                        vectors.append(None)
                        break
                    try:
                        embed_with_timeout = getattr(active, "embed_with_timeout", None)
                        if callable(embed_with_timeout):
                            vec = embed_with_timeout(
                                text,
                                timeout_s=max(0.01, deadline - time.monotonic()),
                                request_class="foreground",
                            )
                        else:
                            vec = active.embed(text)
                    except Exception:  # noqa: BLE001
                        vec = None
                    vectors.append(cast(list[float] | None, vec))
                if len(vectors) < len(candidates):
                    vectors.extend([None] * (len(candidates) - len(vectors)))

        if (
            len(vectors) != len(candidates)
            or any(vec is None for vec in vectors)
            or time.monotonic() > deadline
        ):
            transport_diag = dict(getattr(active, "last_diagnostics", {}) or {})
            reason = str(transport_diag.get("error") or "") or "candidate_embedding_unavailable"
            if time.monotonic() > deadline and not reason:
                reason = "deadline_exhausted"
            self.last_rank_texts_diagnostics.update(
                {
                    "semantic_fallback_reason": reason,
                    "engine": engine_name,
                    "latency_ms": round((time.monotonic() - start) * 1000.0, 3),
                }
            )
            return []

        scored: list[tuple[int, float]] = []
        for index, vec in enumerate(vectors):
            assert vec is not None
            scored.append((index, float(cosine_similarity(query_vec, vec))))
        scored.sort(key=lambda item: item[1], reverse=True)
        cap = len(scored) if top_k is None else max(0, int(top_k))
        self.last_rank_texts_diagnostics.update(
            {
                "semantic_effective": True,
                "engine": engine_name,
                "latency_ms": round((time.monotonic() - start) * 1000.0, 3),
            }
        )
        return scored[:cap]

    def rank_cached_candidates(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Rank stable keyed candidates using the shared persistent vector-cache contract.

        This path is for semantic consumers such as Experience discovery that need
        semantic recall across the full canonical candidate set rather than lexical-only
        membership.  Remote/API foreground requests are strictly cache-read-only: if any
        candidate vector is missing, the whole semantic channel fails open for this query
        and schedules background repair instead of partially ranking a biased subset.
        """
        self.last_cached_rank_diagnostics = {
            "semantic_requested": bool(query and candidates),
            "semantic_effective": False,
            "semantic_fallback_reason": "",
            "candidate_count": len(candidates),
            "candidate_missing_count": 0,
            "cache_files_refreshed": 0,
            "prewarm_scheduled": False,
            "engine": "",
            "latency_ms": 0.0,
        }
        if not query or not candidates or not self.semantic_available() or self.embedder is None:
            self.last_cached_rank_diagnostics["semantic_fallback_reason"] = "unavailable"
            return []

        started = time.monotonic()
        deadline = started + self.timeout_s
        engine = self._primary_engine()
        refreshed = self._refresh_engine_caches(engine)
        missing = self._missing_candidate_count(candidates, engine)
        is_remote_api = getattr(engine["embedder"], "provider", "") == "api"
        prewarm_scheduled = False
        if is_remote_api and missing:
            prewarm_scheduled = self._schedule_background_prewarm(candidates, engine)
            self.last_cached_rank_diagnostics.update(
                {
                    "semantic_fallback_reason": "candidate_cache_cold",
                    "candidate_missing_count": missing,
                    "cache_files_refreshed": refreshed,
                    "prewarm_scheduled": prewarm_scheduled,
                    **self._background_diag_snapshot(),
                    "engine": "primary",
                    "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                }
            )
            return []

        pre_sizes: dict[int, int] = {}
        if not is_remote_api and missing:
            pre_sizes = self._prewarm_batch(candidates, engine, deadline=deadline)
            missing = self._missing_candidate_count(candidates, engine)
            if missing:
                self._flush_dirty_caches(engine, pre_sizes)
                self.last_cached_rank_diagnostics.update(
                    {
                        "semantic_fallback_reason": "candidate_embedding_unavailable",
                        "candidate_missing_count": missing,
                        "cache_files_refreshed": refreshed,
                        "engine": "primary",
                        "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                    }
                )
                return []

        query_vec, query_ms, primary_error = self._embed_query_with_deadline(
            engine["embedder"], query, deadline
        )
        transport_diag = dict(getattr(engine["embedder"], "last_diagnostics", {}) or {})
        if query_vec is None:
            self.last_cached_rank_diagnostics.update(
                {
                    "semantic_fallback_reason": primary_error or "embedding_unavailable",
                    "candidate_missing_count": missing,
                    "cache_files_refreshed": refreshed,
                    "engine": "primary",
                    "query_embedding_ms": round(query_ms, 3),
                    "embedding_queue_wait_ms": transport_diag.get("queue_wait_ms"),
                    "embedding_encode_ms": transport_diag.get("encode_ms"),
                    "embedding_http_ms": transport_diag.get("http_ms"),
                    "embedding_transport_error": transport_diag.get("error", ""),
                    "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                }
            )
            return []

        scored: list[tuple[int, float]] = []
        try:
            for index, cand in enumerate(candidates):
                if time.monotonic() > deadline:
                    self.last_cached_rank_diagnostics.update(
                        {
                            "semantic_fallback_reason": "deadline_exhausted",
                            "candidate_missing_count": missing,
                            "cache_files_refreshed": refreshed,
                            "engine": "primary",
                            "query_embedding_ms": round(query_ms, 3),
                            "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                        }
                    )
                    return []
                vec = self._cached_vector(cand, engine) if is_remote_api else self._embed_cached(cand, engine)
                if vec is None:
                    self.last_cached_rank_diagnostics.update(
                        {
                            "semantic_fallback_reason": "candidate_embedding_unavailable",
                            "candidate_missing_count": max(1, missing),
                            "cache_files_refreshed": refreshed,
                            "engine": "primary",
                            "query_embedding_ms": round(query_ms, 3),
                            "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                        }
                    )
                    return []
                scored.append((index, float(cosine_similarity(query_vec, vec))))
        finally:
            if not is_remote_api:
                self._flush_dirty_caches(engine, pre_sizes)

        scored.sort(key=lambda item: item[1], reverse=True)
        qualified = [item for item in scored if item[1] >= float(engine["threshold"])]
        cap = len(qualified) if top_k is None else max(0, int(top_k))
        self.last_cached_rank_diagnostics.update(
            {
                "semantic_effective": bool(qualified),
                "candidate_missing_count": 0,
                "cache_files_refreshed": refreshed,
                "prewarm_scheduled": prewarm_scheduled,
                **self._background_diag_snapshot(),
                "engine": "primary",
                "threshold": float(engine["threshold"]),
                "semantic_hit_count": len(qualified),
                "query_embedding_ms": round(query_ms, 3),
                "embedding_queue_wait_ms": transport_diag.get("queue_wait_ms"),
                "embedding_encode_ms": transport_diag.get("encode_ms"),
                "embedding_http_ms": transport_diag.get("http_ms"),
                "embedding_transport_error": transport_diag.get("error", ""),
                "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
            }
        )
        return qualified[:cap]

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
        method: Any | None = None,
        keyword_results: list[dict] | None = None,
    ) -> RetrievalResult:
        """语义检索（预算内）→ 与关键词结果融合.

        Args:
            query: 检索词.
            scope: "memory" / "archive" / "all".
            keyword_results: 调用方已算的关键词结果（用于融合去重）.
        """
        start = time.monotonic()
        deadline = start + self.timeout_s
        keyword_count = len(keyword_results or [])
        if not self.semantic_available() or self.embedder is None:
            return RetrievalResult(
                entries=keyword_results or [],
                mode="keyword",
                note="",
                diagnostics={
                    "semantic_requested": True,
                    "semantic_effective": False,
                    "semantic_fallback_reason": "unavailable",
                    "semantic_latency_ms": 0.0,
                    "semantic_hit_count": 0,
                    "keyword_hit_count": keyword_count,
                    "fused_hit_count": keyword_count,
                },
            )
        # T0-B: 引擎级回退——主嵌入不可用时，查询向量/阈值/缓存三件套整体切到
        # fallback（hash）空间；fallback 也失败才降级关键词。绝不混用向量空间。
        q_vec: list[float] | None = None
        engine: dict | None = None
        fallback_note = ""
        primary_error = ""
        query_embedding_ms = 0.0
        q_vec, query_embedding_ms, primary_error = self._embed_query_with_deadline(
            self.embedder, query, deadline
        )
        primary_transport_diag = dict(
            getattr(self.embedder, "last_diagnostics", {}) or {}
        )
        if q_vec is not None:
            engine = {
                "embedder": self.embedder,
                "threshold": self.threshold,
                "mem_cache": self._mem_emb_cache,
                "arch_cache": self._arch_emb_cache,
                "mem_path": self._mem_cache_path,
                "arch_path": self._arch_cache_path,
                "method_cache": self._method_emb_cache,
                "method_path": self._method_cache_path,
            }
        else:
            fb = self._fallback_state()
            if fb is not None:
                q_vec, _fallback_ms, fallback_error = self._embed_query_with_deadline(
                    fb["embedder"], query, deadline
                )
                if q_vec is not None:
                    engine = fb
                    self.fallback_engaged += 1
                    fallback_note = "主嵌入服务不可用，语义通道已整套回退 hash（查询/缓存/阈值同空间切换）"
                    logger.warning(
                        "[T0-B] 主嵌入不可用(%s)，语义通道整套回退 hash", primary_error or "embed 返回 None"
                    )
                elif fallback_error:
                    primary_error = primary_error or fallback_error
        if q_vec is None or engine is None:
            note = f"语义检索不可用：{primary_error}，已降级为关键词检索" if primary_error else ""
            return RetrievalResult(
                entries=keyword_results or [],
                mode="keyword",
                note=note,
                diagnostics={
                    "semantic_requested": True,
                    "semantic_effective": False,
                    "semantic_fallback_reason": primary_error or "embedding_unavailable",
                    "semantic_latency_ms": round((time.monotonic() - start) * 1000, 3),
                    "query_embedding_ms": round(query_embedding_ms, 3),
                    "embedding_queue_wait_ms": primary_transport_diag.get(
                        "queue_wait_ms"
                    ),
                    "embedding_encode_ms": primary_transport_diag.get("encode_ms"),
                    "embedding_http_ms": primary_transport_diag.get("http_ms"),
                    "embedding_transport_error": primary_transport_diag.get(
                        "error", ""
                    ),
                    "semantic_hit_count": 0,
                    "keyword_hit_count": keyword_count,
                    "fused_hit_count": keyword_count,
                },
            )

        # 语义召回（预算内）
        semantic_hits: list[dict] = []
        candidates = self._candidates(scope, session_id, memory, archive, method)
        cache_files_refreshed = self._refresh_engine_caches(engine)
        # API semantic foreground path only consumes already-cached candidate vectors.
        # Missing vectors are warmed asynchronously, so query-time latency is never owned
        # by corpus prewarm or multi-MB cache persistence. Local/hash embedders keep the
        # historical synchronous path because they are zero-network and deterministic.
        is_remote_api = getattr(engine["embedder"], "provider", "") == "api"
        candidate_missing_count = self._missing_candidate_count(candidates, engine)
        foreground_cached_keys = {
            self._vector_cache_key(c)
            for c in candidates
            if self._vector_cache_key(c) in self._cache_route(c, engine)[0]
        }
        prewarm_scheduled = False
        if is_remote_api and candidate_missing_count:
            prewarm_scheduled = self._schedule_background_prewarm(candidates, engine)
            pre_sizes: dict[int, int] = {}
        else:
            pre_sizes = self._prewarm_batch(candidates, engine, deadline=deadline)
        try:
            for c in candidates:
                if time.monotonic() > deadline:
                    return RetrievalResult(
                        entries=keyword_results or [],
                        mode="keyword",
                        note="语义检索超时，已降级为关键词检索",
                        diagnostics={
                            "semantic_requested": True,
                            "semantic_effective": False,
                            "semantic_fallback_reason": "timeout",
                            "semantic_latency_ms": round(
                                (time.monotonic() - start) * 1000, 3
                            ),
                            "query_embedding_ms": round(query_embedding_ms, 3),
                            "embedding_queue_wait_ms": primary_transport_diag.get(
                                "queue_wait_ms"
                            ),
                            "embedding_encode_ms": primary_transport_diag.get(
                                "encode_ms"
                            ),
                            "embedding_http_ms": primary_transport_diag.get("http_ms"),
                            "embedding_transport_error": primary_transport_diag.get(
                                "error", ""
                            ),
                            "candidate_missing_count": candidate_missing_count,
                            "cache_files_refreshed": cache_files_refreshed,
                            "prewarm_scheduled": prewarm_scheduled,
                            **self._background_diag_snapshot(),
                            "semantic_hit_count": len(semantic_hits),
                            "keyword_hit_count": keyword_count,
                            "fused_hit_count": keyword_count,
                        },
                    )
                vec = (
                    self._cached_vector(c, engine)
                    if self._vector_cache_key(c) in foreground_cached_keys
                    else None
                    if is_remote_api
                    else self._embed_cached(c, engine)
                )
                if vec is None:
                    continue
                score = cosine_similarity(q_vec, vec)
                if score >= engine["threshold"]:
                    semantic_hits.append({**c, "_semantic_score": round(score, 3)})
        finally:
            if not is_remote_api:
                # Local/hash path retains historical sync persistence; API cache writes are
                # performed only by the background prewarm worker.
                self._flush_dirty_caches(engine, pre_sizes)
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
        return RetrievalResult(
            entries=fused,
            mode=mode,
            note=fallback_note,
            diagnostics={
                "semantic_requested": True,
                "semantic_effective": bool(semantic_hits),
                "semantic_fallback_reason": (
                    "primary_to_hash" if fallback_note else ""
                ),
                "semantic_latency_ms": round((time.monotonic() - start) * 1000, 3),
                "query_embedding_ms": round(query_embedding_ms, 3),
                "embedding_queue_wait_ms": primary_transport_diag.get(
                    "queue_wait_ms"
                ),
                "embedding_encode_ms": primary_transport_diag.get("encode_ms"),
                "embedding_http_ms": primary_transport_diag.get("http_ms"),
                "embedding_transport_error": primary_transport_diag.get("error", ""),
                "candidate_missing_count": candidate_missing_count,
                "cache_files_refreshed": cache_files_refreshed,
                "prewarm_scheduled": prewarm_scheduled,
                **self._background_diag_snapshot(),
                "semantic_hit_count": len(semantic_hits),
                "keyword_hit_count": keyword_count,
                "fused_hit_count": len(fused),
            },
        )

    # ── 候选条目（惰性向量化）──
    @staticmethod
    def _memory_candidate(entry: Any) -> dict:
        return {
            "kind": "memory",
            "id": entry.id,
            "content": f"{entry.content} {' '.join(entry.keywords)}",
            "key": f"memory:{entry.id}",
        }

    def _memory_cache_candidates(self, memory: Any) -> list[dict]:
        """All memory rows eligible for derived vector caching, independent of visibility.

        Vector presence grants no retrieval authority. Session visibility is enforced later
        by _candidates()/MemoryStore and therefore cache warmup can safely cover all rows,
        avoiding first-query misses for existing session-scoped memories.
        """
        cands: list[dict] = []
        if memory is None:
            return cands
        for e in memory.all():
            cands.append(self._memory_candidate(e))
        return cands

    def _candidates(self, scope: str, session_id: str, memory: Any, archive: Any, method: Any = None) -> list[dict]:
        cands: list[dict] = []
        if scope in {"memory", "all"} and memory is not None:
            for e in memory.all():
                if getattr(e, "scope", "global") == "session" and not (
                    session_id and getattr(e, "source_session_id", "") == session_id
                ):
                    continue
                cands.append(self._memory_candidate(e))
        if scope in {"archive", "all"} and archive is not None and session_id:
            hits = archive.search(session_id, "", limit=10000)
            for h in hits:
                cands.append(self._archive_candidate(h))
        if scope in {"method", "all"} and method is not None:
            with contextlib.suppress(Exception):
                cands.extend(method.semantic_candidates())
        return cands

    def _embed_cached(self, cand: dict, engine: dict) -> list[float] | None:
        # 修复: 按候选自身 kind 路由缓存（scope="all" 时此前误走 archive 缓存，
        # 导致 memory 候选逐条重嵌入+缓存文件交叉污染；候选 dict 已带 kind 字段）
        # T0-B: 缓存/嵌入/落盘路径全部取自当前 engine（主或 fallback，空间自洽）
        cache, _path = self._cache_route(cand, engine)
        key = self._vector_cache_key(cand)
        if key not in cache:
            vec = engine["embedder"].embed(cand["content"])
            if vec is None:
                return None
            cache[key] = vec
            # EVO-20260924-d9c5ad20: 移除逐条全量 persist（N 条新文档 = N 次 ~2MB
            # JSON 重写，是冷启动在 timeout_s 内超时→静默 keyword 降级的主因）；
            # 落盘改为 search() 批处理结束 _flush_dirty_caches 去抖（每缓存 ≤1 次）。
        return cache.get(key)

    def _cached_vector(self, cand: dict, engine: dict) -> list[float] | None:
        """Read-only foreground vector lookup for API-backed semantic search."""
        cache, _path = self._cache_route(cand, engine)
        return cache.get(self._vector_cache_key(cand))

    def _missing_candidate_count(self, candidates: list[dict], engine: dict) -> int:
        missing = 0
        for cand in candidates:
            cache, _path = self._cache_route(cand, engine)
            if self._vector_cache_key(cand) not in cache:
                missing += 1
        return missing

    def _schedule_background_prewarm(
        self, candidates: list[dict], engine: dict
    ) -> bool:
        """Warm API candidate vectors and persist them outside the user request."""
        missing: list[dict] = []
        for cand in candidates:
            cache, _path = self._cache_route(cand, engine)
            if self._vector_cache_key(cand) not in cache:
                missing.append(dict(cand))
        if not missing:
            return False
        missing = missing[: self._BACKGROUND_PREWARM_MAX]

        with self._prewarm_state_lock:
            added = False
            for cand in missing:
                key = self._vector_cache_key(cand)
                if key and key not in self._prewarm_pending:
                    self._prewarm_pending[key] = dict(cand)
                    added = True
            if self._prewarm_inflight:
                return added
            self._prewarm_inflight = True

        def _worker() -> None:
            while True:
                with self._prewarm_state_lock:
                    batch = list(self._prewarm_pending.values())[
                        : self._BACKGROUND_PREWARM_MAX
                    ]
                    for cand in batch:
                        self._prewarm_pending.pop(self._vector_cache_key(cand), None)
                    if not batch:
                        self._prewarm_inflight = False
                        return
                    self._last_background_diag = {
                        "prewarm_ms": 0.0,
                        "cache_flush_ms": 0.0,
                        "missing_count": len(batch),
                        "completed": False,
                        "error": "",
                    }
                started = time.monotonic()
                flush_ms = 0.0
                error = ""
                try:
                    has_batch = callable(
                        getattr(engine["embedder"], "embed_batch", None)
                    )
                    pre_sizes = self._prewarm_batch(batch, engine, deadline=None)
                    # Some API-compatible embedders expose only single-item embed().
                    # Keep that compatibility only when no batch interface exists at all.
                    # A partial/failed batch is intentionally left missing for a later
                    # background round; never amplify one batch timeout into N serial calls.
                    if not has_batch:
                        for cand in batch:
                            cache, _path = self._cache_route(cand, engine)
                            vector_key = self._vector_cache_key(cand)
                            if vector_key in cache:
                                continue
                            embed_with_timeout = getattr(
                                engine["embedder"], "embed_with_timeout", None
                            )
                            if callable(embed_with_timeout):
                                vec = embed_with_timeout(
                                    cand["content"],
                                    timeout_s=float(
                                        getattr(engine["embedder"], "timeout_s", 5.0)
                                        or 5.0
                                    ),
                                    request_class="background",
                                )
                            else:
                                vec = engine["embedder"].embed(cand["content"])
                            if vec:
                                cache[vector_key] = vec
                    flush_started = time.monotonic()
                    self._flush_dirty_caches(engine, pre_sizes)
                    flush_ms = (time.monotonic() - flush_started) * 1000.0
                except Exception as exc:  # noqa: BLE001 - background warmup is fail-open
                    error = type(exc).__name__
                    logger.debug("background semantic prewarm failed", exc_info=True)
                finally:
                    with self._prewarm_state_lock:
                        self._last_background_diag = {
                            "prewarm_ms": round(
                                (time.monotonic() - started) * 1000.0, 3
                            ),
                            "cache_flush_ms": round(flush_ms, 3),
                            "missing_count": len(batch),
                            "completed": True,
                            "error": error,
                        }

        threading.Thread(
            target=_worker,
            name="semantic-prewarm",
            daemon=True,
        ).start()
        return added

    def _cache_route(self, cand: dict, engine: dict) -> tuple[dict, Path | None]:
        """候选 → (所属缓存 dict, 落盘路径)。按 kind 路由（与 _embed_cached 消重）."""
        kind = cand.get("kind", "memory")
        if kind == "method":
            return engine.setdefault("method_cache", {}), engine.get("method_path")
        if kind in {"experience", "lesson"}:
            return engine.setdefault("experience_cache", {}), engine.get("experience_path")
        if kind == "archive":
            return engine["arch_cache"], engine["arch_path"]
        return engine["mem_cache"], engine["mem_path"]

    def _prewarm_batch(
        self, candidates: list[dict], engine: dict, deadline: float | None = None
    ) -> dict[int, int]:
        """冷启动批量预热（EVO-20260924-d9c5ad20）：未缓存候选分片 embed_batch 填缓存。

        返回 {id(cache): 预热前条数} 供 _flush_dirty_caches 判断去抖落盘。
        - 预算约束：每片前检查 deadline，超时停片——剩余候选由循环路径兜底
          （快速降级返回，不挂预算外时间），后续查询增量吃掉剩余
        - embedder 无 embed_batch / 批量结果不齐 / 批量异常 → 静默跳过
          （循环内逐条路径兜底，行为与旧版一致）
        - 批量失败条目（None）不写缓存，保持"失败可在单条路径重试"语义
        """
        caches = [
            engine["mem_cache"],
            engine["arch_cache"],
            engine.setdefault("method_cache", {}),
            engine.setdefault("experience_cache", {}),
        ]
        pre = {id(c): len(c) for c in caches}
        embed_batch = getattr(engine["embedder"], "embed_batch", None)
        if embed_batch is None or not candidates:
            return pre
        grouped: list[tuple[dict, str, str]] = []
        for c in candidates:
            cache, _ = self._cache_route(c, engine)
            vector_key = self._vector_cache_key(c)
            if vector_key not in cache:
                grouped.append((cache, vector_key, c["content"]))
        if not grouped:
            return pre
        chunk = int(getattr(engine["embedder"], "_BATCH_CHUNK", 64) or 64)
        try:
            for s in range(0, len(grouped), chunk):
                if deadline is not None and time.monotonic() > deadline:
                    break
                piece = grouped[s : s + chunk]
                vecs = embed_batch([t for _, _, t in piece])
                if not isinstance(vecs, list) or len(vecs) != len(piece):
                    return pre  # 结果不齐：本片作废并停止预热（循环内逐条兜底）
                for (cache, key, _), vec in zip(piece, vecs, strict=True):
                    if vec:
                        cache[key] = vec
        except Exception:  # noqa: BLE001 — 预热失败回退逐条（与单条 embed 异常语义一致）
            return pre
        return pre

    def _flush_dirty_caches(self, engine: dict, pre_sizes: dict[int, int]) -> None:
        """持久化去抖（EVO-20260924-d9c5ad20）：本轮新增过条目的缓存各落盘至多一次."""
        for cache, path in (
            (engine["mem_cache"], engine["mem_path"]),
            (engine["arch_cache"], engine["arch_path"]),
            (engine.setdefault("method_cache", {}), engine.get("method_path")),
            (engine.setdefault("experience_cache", {}), engine.get("experience_path")),
        ):
            if path is not None and len(cache) > pre_sizes.get(id(cache), len(cache)):
                self._persist_emb_cache(path, cache, engine["embedder"])

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
