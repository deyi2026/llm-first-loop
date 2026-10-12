"""T47: 语义接线集成测试（FR-AUD-ARC-02）.

M11 修复 semantic_retriever 未接线：主循环记忆注入走语义检索。
- EMBEDDING_PROVIDER=hash 时语义路径生效
- 默认配置（无 semantic_retriever）P0 关键词路径零回归
"""

from __future__ import annotations

from llm_loop.memory.embedder import HashEmbedder
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry


def test_semantic_retriever_is_on_demand_not_automatic_prompt(build_test_engine, tmp_path):
    """Semantic memory remains available but is not run automatically on human ingress."""
    engine, fake = build_test_engine([{"content": "最终回答。"}])
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=str(tmp_path / "data" / "memory"))
    calls: list[dict] = []
    original_search = retriever.search

    def counted_search(*args, **kwargs):
        calls.append(dict(kwargs))
        return original_search(*args, **kwargs)

    retriever.search = counted_search  # type: ignore[method-assign]
    engine.semantic_retriever = retriever  # type: ignore[attr-defined]
    engine.memory.save_entry(
        MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"])
    )
    sid = engine.session.create()
    engine.run(sid, "喜欢的色彩是？")

    assert calls == []
    last_call = fake.calls[0]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in last_call)
    assert "[memory:fact] 用户喜欢蓝色" not in joined
    assert "ref=memory:" not in joined


def test_default_config_keyword_memory_is_not_auto_projected(build_test_engine):
    """Default keyword memory also stays on-demand instead of automatic prompt context."""
    engine, fake = build_test_engine([{"content": "最终回答。"}])
    assert engine.semantic_retriever is None  # 默认未装配
    engine.memory.save_entry(
        MemoryEntry(id="", type="fact", content="Python 内容", keywords=["Python"])
    )
    sid = engine.session.create()
    engine.run(sid, "Python 相关")
    last_call = fake.calls[0]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in last_call)
    assert "[memory:fact] Python 内容" not in joined
    assert "ref=memory:" not in joined
