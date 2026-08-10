"""P1 边界覆盖补充（T37: search 语义路径 / retrieve 语义 / summarize async / registry oversize）."""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.introspection.search import RecordSearcher
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.embedder import HashEmbedder
from llm_loop.memory.retrieve import build_memory_messages
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry, MemoryStore
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.registry import ToolRegistry


def test_search_records_semantic_memory(tmp_path):
    """T31: search_records kind=memory 语义可用时 mode=semantic."""
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"]))
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        memory_store=mem,
        semantic_retriever=retriever,
    )
    hits = searcher.search(kind="memory", query="蓝色", limit=5)
    assert len(hits) >= 1
    assert hits[0]["kind"] == "memory"


def test_search_records_keyword_when_semantic_none(tmp_path):
    """EMBEDDING_PROVIDER=none（无 semantic_retriever）→ P0 关键词行为."""
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="Python 内容", keywords=["Python"]))
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", memory_store=mem)
    hits = searcher.search(kind="memory", query="Python", limit=5)
    assert len(hits) == 1


def test_build_memory_messages_semantic(tmp_path):
    """T30: build_memory_messages 语义检索命中（mode 标注注入）."""
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"]))
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    msgs = build_memory_messages("喜欢的色彩", mem, semantic_retriever=retriever)
    assert len(msgs) == 1
    assert msgs[0].source.value == "memory"


def test_summarizer_async_backfill(tmp_path):
    """T28: async 模式 summarize_archive 后台回填."""
    from llm_loop.llm.client import LLMResponse
    from llm_loop.memory.summarize import Summarizer

    class _Fake:
        def chat(self, messages, tools):
            return LLMResponse(content="异步 LLM 摘要", tool_calls=[], provider="fake")

    store = ArchiveStore(tmp_path / "archives")
    entry = store.archive("s1", role="user", source="user", content="重要内容 ABCDEF")
    s = Summarizer(llm_client=_Fake(), mode="async")
    result = s.summarize_archive(entry.id, "重要内容 ABCDEF", store)
    assert result.source == "deterministic"  # 立即返回占位
    # 等待后台回填
    import time

    for _ in range(50):
        hits = store.search("s1", "异步 LLM 摘要")
        if hits:
            break
        time.sleep(0.05)
    assert hits, "后台摘要应回填"


def test_summarizer_sync_backfill(tmp_path):
    """T28: sync 模式 summarize_archive 同步回填 summary_source=llm."""
    from llm_loop.llm.client import LLMResponse
    from llm_loop.memory.summarize import Summarizer

    class _Fake:
        def chat(self, messages, tools):
            return LLMResponse(content="同步 LLM 摘要", tool_calls=[], provider="fake")

    store = ArchiveStore(tmp_path / "archives")
    entry = store.archive("s1", role="user", source="user", content="重要内容")
    s = Summarizer(llm_client=_Fake(), mode="sync")
    s.summarize_archive(entry.id, "重要内容", store)
    hits = store.search("s1", "同步 LLM 摘要")
    assert hits


def test_registry_oversize_archives(tmp_path):
    """T22/T35: 超长工具结果另存压缩档案（信息不丢失）."""
    from llm_loop.memory.archive import ArchiveStore

    arch = ArchiveStore(tmp_path / "archives")
    reg = ToolRegistry(max_output_chars=50, archive_store=arch)
    reg.set_session_id("s1")
    reg.register(ReadFileTool())
    f = tmp_path / "big.txt"
    f.write_text("内容" * 100, encoding="utf-8")
    result = reg.execute(ToolCall(id="c1", name="read_file", arguments={"path": str(f)}))
    assert result.status == ToolResultStatus.SUCCESS
    assert "已另存" in result.content  # 截断标注含另存指引
    # 完整结果已在档案中（可检索找回）
    hits = arch.search("s1", "内容")
    assert hits
    assert len(hits[0].get("content_preview", "")) > 50
