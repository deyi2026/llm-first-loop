"""T0-B: SemanticRetriever 主嵌入不可用时整套回退 hash（同空间切换）单测.

核心不变量: 回退发生在引擎级——查询向量/阈值/缓存文件三件套一起切到
hash-v2 空间，绝不把 hash 向量写进 api 版本缓存文件（防向量空间互踩）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from llm_loop.memory.retriever import SemanticRetriever


class StubAPIEmbedder:
    provider = "api"
    vector_version = "api-v1:test"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def embed(self, text: str):
        if self.fail:
            return None
        return [1.0, 0.0]


class StubHashEmbedder:
    provider = "hash"
    vector_version = "hash-v2"

    def embed(self, text: str):
        return [1.0, 0.0]


@dataclass
class MemEntry:
    id: str
    content: str
    keywords: list[str] = field(default_factory=list)
    scope: str = "global"
    source_session_id: str = ""


class MemStore:
    def __init__(self, entries: list[MemEntry]) -> None:
        self._entries = entries

    def all(self):
        return self._entries


def _retriever(tmp_path: Path, primary, fallback=None, **kw):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(exist_ok=True)
    return SemanticRetriever(
        primary,
        memory_dir=mem_dir,
        archive_dir=None,
        fallback_embedder=fallback,
        **kw,
    )


def test_primary_down_falls_back_hash_engine(tmp_path: Path):
    # hash 查询向量与候选夹角余弦 ≈0.3：过 hash 阈值 0.22，不过 api 阈值 0.50
    class HashVec(StubHashEmbedder):
        def embed(self, text: str):
            if text.startswith("query:"):
                return [1.0, 0.0]
            return [0.3, 0.9539]

    primary = StubAPIEmbedder(fail=True)
    r = _retriever(tmp_path, primary, fallback=HashVec())
    memory = MemStore([MemEntry(id="m1", content="候选甲", keywords=["甲"])])
    result = r.search("query: 语义", top_k=5, memory=memory)
    assert r.fallback_engaged == 1
    assert any(e["id"] == "m1" for e in result.entries), "hash 引擎应命中 0.3 相似度候选"
    assert "回退" in result.note
    # 缓存文件必须是 hash 版本（同空间切换，不污染 api 缓存）
    cache_files = list((tmp_path / "memory").glob("embeddings-*.json"))
    assert len(cache_files) == 1
    payload = json.loads(cache_files[0].read_text())
    assert payload["v"] == "hash-v2"


def test_primary_up_uses_api_engine_no_fallback(tmp_path: Path):
    primary = StubAPIEmbedder()  # embed 恒 [1,0] → cos=1.0
    r = _retriever(tmp_path, primary, fallback=StubHashEmbedder())
    memory = MemStore([MemEntry(id="m1", content="候选甲", keywords=["甲"])])
    result = r.search("query", top_k=5, memory=memory)
    assert r.fallback_engaged == 0
    assert result.entries
    cache_files = list((tmp_path / "memory").glob("embeddings-*.json"))
    payload = json.loads(cache_files[0].read_text())
    assert payload["v"] == "api-v1:test"


def test_primary_exception_also_falls_back(tmp_path: Path):
    class Boom(StubAPIEmbedder):
        def embed(self, text: str):
            raise ConnectionError("8765 refused")

    r = _retriever(tmp_path, Boom(), fallback=StubHashEmbedder())
    memory = MemStore([MemEntry(id="m1", content="甲", keywords=["甲"])])
    result = r.search("query", top_k=5, memory=memory)
    assert r.fallback_engaged == 1
    assert result.entries


def test_no_fallback_keeps_keyword_degradation(tmp_path: Path):
    r = _retriever(tmp_path, StubAPIEmbedder(fail=True), fallback=None)
    memory = MemStore([MemEntry(id="m1", content="甲", keywords=["甲"])])
    result = r.search("query", top_k=5, memory=memory, keyword_results=[{"id": "m1", "key": "memory:m1"}])
    assert r.fallback_engaged == 0
    assert result.mode == "keyword"
    assert result.entries and result.entries[0]["id"] == "m1"


def test_two_cache_files_coexist_without_crossover(tmp_path: Path):
    # 先 api 命中（写 api 缓存），再 api 挂掉回退（写 hash 缓存）→ 两文件并存、各自版本键正确
    primary = StubAPIEmbedder()
    r = _retriever(tmp_path, primary, fallback=StubHashEmbedder())
    memory = MemStore([MemEntry(id="m1", content="甲", keywords=["甲"])])
    r.search("query", top_k=5, memory=memory)
    primary.fail = True
    result = r.search("query", top_k=5, memory=memory)
    assert r.fallback_engaged == 1 and result.entries
    files = sorted((tmp_path / "memory").glob("embeddings-*.json"))
    assert len(files) == 2
    versions = {json.loads(f.read_text())["v"] for f in files}
    assert versions == {"api-v1:test", "hash-v2"}
