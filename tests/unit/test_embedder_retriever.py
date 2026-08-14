"""单元测试: Embedder 三实现 + SemanticRetriever（T29-T30 / FR-P1-RET）."""

from __future__ import annotations

from unittest import mock

from llm_loop.memory.embedder import HashEmbedder, NullEmbedder, cosine_similarity
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry, MemoryStore


# ── Embedder（T29）──
def test_null_embedder_always_none():
    """NullEmbedder 恒 None → 语义不可用（P0 关键词回归安全）."""
    e = NullEmbedder()
    assert e.provider == "none"
    assert e.embed("任何文本") is None


def test_hash_embedder_deterministic():
    """HashEmbedder: 同文本同向量确定性，不同文本有区分."""
    e = HashEmbedder(dim=128)
    v1 = e.embed("用户喜欢蓝色")
    v2 = e.embed("用户喜欢蓝色")
    v3 = e.embed("完全不同的主题")
    assert v1 == v2  # 确定性
    assert v1 != v3  # 有区分
    assert v1 is not None and len(v1) == 128


def test_hash_embedder_empty():
    """空文本 → None."""
    e = HashEmbedder()
    assert e.embed("") is None


def test_cosine_similarity():
    a = [1.0, 0.0]
    b = [1.0, 0.0]
    assert cosine_similarity(a, b) == 1.0
    assert cosine_similarity(a, [0.0, 1.0]) == 0.0
    assert cosine_similarity([], []) == 0.0


def test_api_embedder_request():
    """APIEmbedder mock httpx: 端点 URL/请求体/鉴权头正确."""
    from llm_loop.memory.embedder import APIEmbedder

    with mock.patch("httpx.Client") as client_cls:
        client = client_cls.return_value
        client.post.return_value = mock.MagicMock(
            status_code=200, json=lambda: {"data": [{"embedding": [0.1, 0.2]}]}
        )
        e = APIEmbedder(api_key="k", base_url="https://embed.local/v1", model="m")
        vec = e.embed("hello")
    assert vec == [0.1, 0.2]
    call = client.post.call_args
    assert call.args[0] == "https://embed.local/v1/embeddings"
    assert call.kwargs["headers"]["Authorization"] == "Bearer k"
    assert call.kwargs["json"]["model"] == "m"


def test_api_embedder_error_returns_none():
    """APIEmbedder 异常/错误 → None（如实，不抛穿）."""
    from llm_loop.memory.embedder import APIEmbedder

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.post.side_effect = Exception("boom")
        e = APIEmbedder(api_key="k", base_url="https://x/v1", model="m")
        assert e.embed("x") is None


# ── SemanticRetriever（T30）──
def _memory_with_entries(tmp_path):
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"]))
    mem.save_entry(
        MemoryEntry(id="", type="fact", content="项目技术栈是 Python", keywords=["Python"])
    )
    return mem


def test_semantic_hit_without_keyword_overlap(tmp_path):
    """语义相关但关键词不重叠的记忆被召回（HashEmbedder）."""
    mem = _memory_with_entries(tmp_path)
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    # "钟爱的颜色" 与 "蓝色" 语义相关但无关键词重叠（2-gram 不同）
    result = retriever.search("喜欢的色彩", top_k=5, scope="memory", memory=mem)
    assert result.mode in {"semantic", "mixed"}
    contents = [h["content"] for h in result.entries]
    assert any("蓝色" in c for c in contents)


def test_keyword_fallback_when_semantic_unavailable(tmp_path):
    """NullEmbedder/无 embedder → keyword 结果（P0 回归安全）."""
    mem = _memory_with_entries(tmp_path)
    retriever = SemanticRetriever(NullEmbedder(), memory_dir=tmp_path / "memory")
    keyword_hits = [{"kind": "memory", "id": "x", "content": "Python 内容", "key": "memory:x"}]
    result = retriever.search(
        "Python", top_k=5, scope="memory", memory=mem, keyword_results=keyword_hits
    )
    assert result.mode == "keyword"


def test_semantic_timeout_fallback(tmp_path):
    """语义检索超时 → 关键词兜底 + note（不阻塞 LLM 决策）."""
    mem = _memory_with_entries(tmp_path)

    class _SlowEmbedder:
        provider = "hash"

        def embed(self, text: str) -> list[float] | None:
            import time

            time.sleep(0.5)
            return HashEmbedder().embed(text)

    retriever = SemanticRetriever(_SlowEmbedder(), timeout_s=0.05, memory_dir=tmp_path / "memory")
    keyword_hits = [{"kind": "memory", "id": "y", "content": "Python", "key": "memory:y"}]
    result = retriever.search(
        "Python 技术", top_k=5, scope="memory", memory=mem, keyword_results=keyword_hits
    )
    assert result.mode == "keyword"
    assert "超时" in result.note


def test_embedder_exception_fallback(tmp_path):
    """嵌入异常 → 关键词兜底 + note（如实降级）."""
    mem = _memory_with_entries(tmp_path)

    class _BadEmbedder:
        provider = "hash"

        def embed(self, text: str) -> list[float]:
            raise RuntimeError("embed 服务崩溃")

    retriever = SemanticRetriever(_BadEmbedder(), memory_dir=tmp_path / "memory")
    keyword_hits = []
    result = retriever.search(
        "Python", top_k=5, scope="memory", memory=mem, keyword_results=keyword_hits
    )
    assert result.mode == "keyword"
    assert "不可用" in result.note


def test_api_embedder_no_auth_when_api_key_empty():
    """本地 embedding 端点（api_key 空）不发 Authorization 头（httpx Illegal header value 防护）."""
    from unittest import mock

    from llm_loop.memory.embedder import APIEmbedder
    fake_resp = mock.Mock(status_code=200, json=lambda: {"data": [{"embedding": [0.1] * 4}]})
    embedder = APIEmbedder(api_key="", base_url="http://localhost:1234/v1", model="text-emb", timeout_s=10)
    with mock.patch.object(embedder._client, "post", return_value=fake_resp) as post:
        embedder.embed("hi")
    _, kwargs = post.call_args
    headers = kwargs["headers"]
    assert "Authorization" not in headers, f"空 api_key 不应发 Authorization, 实际: {headers}"
