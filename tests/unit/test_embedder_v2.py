"""T6(2026-08-14) 本地向量记忆增强测试（零 LLM 零网络）.

覆盖: HashEmbedder v2（2+3-gram）确定性/区分度/3-gram 增强的语义召回 /
embedding 缓存版本化（新格式 roundtrip / 版本不匹配忽略重建 / 旧扁平格式仅
hash-v1 兼容 / 损坏 fail-open）。
"""

from __future__ import annotations

import json

from llm_loop.memory.embedder import HashEmbedder, cosine_similarity
from llm_loop.memory.retriever import SemanticRetriever

# ── HashEmbedder v2 ──


def test_v2_deterministic_and_distinct():
    e = HashEmbedder(dim=128)
    v1 = e.embed("多模态理解任务")
    v2 = e.embed("多模态理解任务")
    assert v1 == v2  # 确定性
    assert e.embed("多模态理解任务") != e.embed("天气预报")


def test_v2_version_tag():
    assert HashEmbedder.vector_version == "hash-v2"
    assert HashEmbedder().vector_version == "hash-v2"


def test_v2_threegram_enhances_similarity():
    """3-gram 增强：共享 3-gram 的文本相似度显著高于仅共享 2-gram 的文本."""
    e = HashEmbedder(dim=256)
    a = "上下文压缩策略"
    b = "上下文压缩优化"  # 与 a 共享 2+3-gram
    c = "压缩上下文策略"  # 与 a 共享部分 2-gram、无完整 3-gram
    sim_ab = cosine_similarity(e.embed(a), e.embed(b))
    sim_ac = cosine_similarity(e.embed(a), e.embed(c))
    assert sim_ab > sim_ac, f"期望 3-gram 共享提升相似度: {sim_ab} vs {sim_ac}"


def test_v2_semantic_recall(tmp_path):
    """语义相关但关键词不重叠的记忆被召回（T6 增强后保持）."""
    from llm_loop.memory.store import MemoryEntry, MemoryStore

    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(
        MemoryEntry(id="", type="fact", content="多模态视频理解需要视觉编码器", keywords=["多模态", "视频"])
    )
    mem.save_entry(
        MemoryEntry(id="", type="fact", content="今天天气晴朗适合散步", keywords=["天气"])
    )
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    result = retriever.search(
        "多模态图像理解", top_k=5, scope="memory", session_id="", memory=mem, archive=None
    )
    assert any("视觉编码器" in h.get("content", "") for h in result.entries)


# ── 缓存版本化 ──


def test_cache_new_format_roundtrip(tmp_path):
    """新格式（v+data）roundtrip：同版本加载."""
    mem = tmp_path / "memory"
    mem.mkdir()
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=mem)
    cache = retriever._mem_emb_cache
    cache["key-a"] = [0.1, 0.2]
    retriever._persist_emb_cache(retriever._mem_cache_path, cache)
    raw = json.loads((mem / "embeddings.json").read_text(encoding="utf-8"))
    assert raw["v"] == "hash-v2"
    assert raw["data"] == {"key-a": [0.1, 0.2]}
    # 重新加载（同版本）→ 命中
    retriever2 = SemanticRetriever(HashEmbedder(), memory_dir=mem)
    assert retriever2._mem_emb_cache.get("key-a") == [0.1, 0.2]


def test_cache_version_mismatch_ignored(tmp_path):
    """版本不匹配（v1 缓存文件 + v2 embedder）→ 忽略重建（防新旧向量混用）."""
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "embeddings.json").write_text(
        json.dumps({"v": "hash-v1", "data": {"old": [0.9, 0.9]}}), encoding="utf-8"
    )
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=mem)
    assert retriever._mem_emb_cache == {}


def test_cache_legacy_flat_only_v1(tmp_path):
    """旧扁平格式（无版本键）：hash-v1 兼容加载，v2 忽略."""
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "embeddings.json").write_text(json.dumps({"legacy": [0.5]}), encoding="utf-8")
    # v2 embedder → 忽略
    r2 = SemanticRetriever(HashEmbedder(), memory_dir=mem)
    assert r2._mem_emb_cache == {}
    # v1 兼容模拟：embedder 声明 hash-v1 → 加载
    class _V1Embedder(HashEmbedder):
        vector_version = "hash-v1"

    r1 = SemanticRetriever(_V1Embedder(), memory_dir=mem)
    assert r1._mem_emb_cache.get("legacy") == [0.5]


def test_cache_corrupt_fail_open(tmp_path):
    """损坏缓存文件 → fail-open 忽略（检索不中断）."""
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "embeddings.json").write_text("{broken", encoding="utf-8")
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=mem)
    assert retriever._mem_emb_cache == {}
    # 无 embedder（None）→ 版本空串，不加载任何缓存
    r_none = SemanticRetriever(None, memory_dir=mem)
    assert r_none._mem_emb_cache == {}
