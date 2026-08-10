"""T47: 语义接线集成测试（FR-AUD-ARC-02）.

M11 修复 semantic_retriever 未接线：主循环记忆注入走语义检索。
- EMBEDDING_PROVIDER=hash 时语义路径生效
- 默认配置（无 semantic_retriever）P0 关键词路径零回归
"""

from __future__ import annotations

from llm_loop.memory.embedder import HashEmbedder
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry


def test_semantic_retriever_injected_and_used(build_test_engine, tmp_path):
    """M11: semantic_retriever 注入后，语义检索命中（mode 标注注入记忆消息）."""
    engine, fake = build_test_engine([{"content": "最终回答。"}])
    # 装配语义检索器（模拟 EMBEDDING_PROVIDER=hash）
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=str(tmp_path / "data" / "memory"))
    engine.semantic_retriever = retriever  # type: ignore[attr-defined]
    # 注入一条语义相关记忆
    engine.memory.save_entry(
        MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"])
    )
    sid = engine.session.create()
    engine.run(sid, "喜欢的色彩是？")
    # 语义检索标注出现在记忆消息中
    last_call = fake.calls[0]["messages"]
    assert any("语义检索生效" in str(m.get("content", "")) for m in last_call)


def test_default_config_keyword_path_regression(build_test_engine):
    """默认配置（semantic_retriever=None）→ 关键词路径（P0 零回归）."""
    engine, fake = build_test_engine([{"content": "最终回答。"}])
    assert engine.semantic_retriever is None  # 默认未装配
    engine.memory.save_entry(
        MemoryEntry(id="", type="fact", content="Python 内容", keywords=["Python"])
    )
    sid = engine.session.create()
    engine.run(sid, "Python 相关")
    last_call = fake.calls[0]["messages"]
    assert any("[相关记忆]" in str(m.get("content", "")) for m in last_call)
