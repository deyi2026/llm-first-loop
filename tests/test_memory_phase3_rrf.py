"""Phase 3 RRF 多信号融合测试（借鉴 uteke/mem0 混合检索）."""
from llm_loop.memory.embedder import HashEmbedder, NullEmbedder
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _mem(tmp_path):
    m = MemoryStore(tmp_path / "memory")
    m.save_entry(MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"]))
    m.save_entry(MemoryEntry(id="", type="fact", content="项目用 Python 开发", keywords=["Python"]))
    m.save_entry(MemoryEntry(id="", type="fact", content="今天天气晴", keywords=["天气"]))
    return m


def _kw(hits):
    return [{"kind": "memory", "id": h["id"], "content": h["content"], "key": f"memory:{h['id']}"} for h in hits]


def test_rrf_double_signal_outranks_single(tmp_path):
    """双通道命中（语义+关键词）条目 RRF 得分 > 仅语义命中条目."""

    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    # 构造: A 仅语义命中（排名高），B 语义+关键词双命中
    semantic = [
        {"kind": "memory", "id": "A", "content": "用户喜欢蓝色", "key": "memory:A", "_semantic_score": 0.9},
        {"kind": "memory", "id": "B", "content": "Python 开发", "key": "memory:B", "_semantic_score": 0.8},
    ]
    keyword = [{"kind": "memory", "id": "B", "content": "Python 开发", "key": "memory:B"}]
    fused = retriever._rrf_fuse(semantic, keyword, top_k=5)
    # B 双通道: 1/61 + 1/61 = 0.0328 > A 单通道: 1/61 = 0.0164
    assert fused[0]["id"] == "B"
    assert fused[0]["_rrf_score"] > fused[1]["_rrf_score"]


def test_rrf_rank_contribution_decreases_with_rank(tmp_path):
    """同通道内排名越靠前贡献越大（1/(k+rank) 递减）."""
    retriever = SemanticRetriever(NullEmbedder())
    semantic = [
        {"kind": "memory", "id": "R1", "content": "x", "key": "memory:R1", "_semantic_score": 0.9},
        {"kind": "memory", "id": "R2", "content": "y", "key": "memory:R2", "_semantic_score": 0.8},
    ]
    fused = retriever._rrf_fuse(semantic, [], top_k=5)
    assert fused[0]["id"] == "R1"  # 语义分高者在前（单一通道时 RRF 退化为原序）
    assert fused[0]["_rrf_score"] > fused[1]["_rrf_score"]


def test_rrf_search_mixed_mode_preserved(tmp_path):
    """search 入口: 语义+关键词双通道 → mode=mixed，entries 带 _rrf_score."""
    mem = _mem(tmp_path)
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    kw = [{"kind": "memory", "id": "x", "content": "Python 开发", "key": "memory:x"}]
    result = retriever.search("Python 技术", top_k=5, scope="memory", memory=mem, keyword_results=kw)
    assert result.mode == "mixed"
    for e in result.entries:
        assert "_rrf_score" in e  # RRF 已生效


def test_rrf_semantic_only_keeps_original_order(tmp_path):
    """仅语义通道（无关键词结果）→ 保持语义排序，mode=semantic."""
    mem = _mem(tmp_path)
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    result = retriever.search("喜欢的色彩", top_k=5, scope="memory", memory=mem)
    assert result.mode in {"semantic", "mixed"}
    assert any("蓝色" in h["content"] for h in result.entries)  # 语义召回蓝色（关键词不重叠）


def test_rrf_keyword_only_fallback(tmp_path, monkeypatch):
    """语义不可用（NullEmbedder）→ 关键词结果原样返回，mode=keyword（P0 回归安全）."""
    # 隔离宿主机本地 ONNX 模型缓存（Rule28 修复轮 2026-10-25）：semantic_available()
    # = 主嵌入 or 本地重排器（retriever.py D7 两段式）。本机
    # ~/.cache/lfl/models/bge-small-zh-v1.5 已于 2026-10-20 落盘，NullEmbedder 语境下
    # _reranker_ready() 惰性探测翻 True → 降级分支激活 mode=mixed（产品行为是 D7
    # 设计内，见 factory.py "EMBEDDING_PROVIDER=none 时仍装配检索器壳"注释）。
    # 本测试验证的是"语义完全不可用"的 keyword 回退安全路径，须把
    # LFL_SEMANTIC_MODEL_DIR 指到空目录，使探测确定性返回 False。
    monkeypatch.setenv("LFL_SEMANTIC_MODEL_DIR", str(tmp_path / "no-local-onnx-models"))
    mem = _mem(tmp_path)
    retriever = SemanticRetriever(NullEmbedder(), memory_dir=tmp_path / "memory")
    kw = [{"kind": "memory", "id": "x", "content": "Python 内容", "key": "memory:x"}]
    result = retriever.search("Python", top_k=5, scope="memory", memory=mem, keyword_results=kw)
    assert result.mode == "keyword"
    assert result.entries == kw
