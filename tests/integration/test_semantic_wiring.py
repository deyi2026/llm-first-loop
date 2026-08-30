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
    """R3: semantic retriever is called with the current sid; prompt gets pointer form."""
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

    assert calls and calls[0].get("session_id") == sid
    last_call = fake.calls[0]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in last_call)
    assert "[memory:fact] 用户喜欢蓝色" in joined
    assert "ref=memory:" in joined
    assert "语义检索生效" not in joined  # R3 不再把检索 mode 当资料正文自动注入


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
    joined = "\n".join(str(m.get("content", "")) for m in last_call)
    assert "[memory:fact] Python 内容" in joined
    assert "ref=memory:" in joined
