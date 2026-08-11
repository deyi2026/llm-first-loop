"""Phase 5 实体通道测试（mem0 式 Entity Linking 轻量版）."""
from llm_loop.memory.embedder import HashEmbedder, NullEmbedder
from llm_loop.memory.retriever import SemanticRetriever, extract_entities
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _mem(tmp_path):
    m = MemoryStore(tmp_path / "memory")
    m.save_entry(MemoryEntry(id="", type="fact", content="Alice 负责 Python 项目", keywords=["Alice"]))
    m.save_entry(MemoryEntry(id="", type="fact", content="Bob 负责运维部署", keywords=["Bob"]))
    m.save_entry(MemoryEntry(id="", type="fact", content="今天天气晴", keywords=["天气"]))
    return m


def test_extract_entities_rule():
    """实体提取: 首字母大写专有名词；排除句首/停用词."""
    ents = extract_entities("Alice and Bob worked on the LM Studio project")
    assert "Alice" in ents and "Bob" in ents and "Studio" in ents
    # ≥3 字符规则: 2 字符缩写（LM/OK/IT）不提取；句首/停用词排除
    assert "LM" not in ents and "The" not in ents and "And" not in ents


def test_entity_overlap():
    r = SemanticRetriever(NullEmbedder())
    assert r._entity_overlap(["Alice", "Bob"], ["Alice", "Python"]) == 1
    assert r._entity_overlap(["Alice"], ["Bob"]) == 0
    assert r._entity_overlap([], ["Alice"]) == 0


def test_entity_only_hit_recalled(tmp_path):
    """实体匹配但语义/关键词均未命中 → 仍被召回（mode=mixed_entity）."""
    mem = _mem(tmp_path)
    retriever = SemanticRetriever(HashEmbedder(), memory_dir=tmp_path / "memory")
    # "Alice 的近况" 关键词 2-gram 与条目无重叠、语义弱，但实体 Alice 匹配
    result = retriever.search("Alice 的近况", top_k=5, scope="memory", memory=mem)
    contents = [h["content"] for h in result.entries]
    assert any("Alice" in c for c in contents)
    assert result.mode in {"mixed", "mixed_entity", "semantic"}


def test_rrf_three_signal_stacking():
    """三通道全命中 > 双通道 > 单通道（RRF 叠加）."""
    r = SemanticRetriever(NullEmbedder())
    semantic = [
        {"kind": "m", "id": "A", "content": "x", "key": "m:A", "_semantic_score": 0.9},
        {"kind": "m", "id": "B", "content": "y", "key": "m:B", "_semantic_score": 0.8},
        {"kind": "m", "id": "C", "content": "z", "key": "m:C", "_semantic_score": 0.7},
    ]
    keyword = [{"kind": "m", "id": "B", "content": "y", "key": "m:B"}]
    entity = [{"kind": "m", "id": "C", "content": "z", "key": "m:C"}]
    fused = r._rrf_fuse(semantic, keyword, entity, top_k=5)
    # A 仅语义(rank1)=1/61≈0.0164; B 语义+关键词=2/61≈0.0328; C 语义+实体=2/61≈0.0328
    # B、C 并列最高，A 最低
    assert fused[0]["id"] in {"B", "C"}
    assert fused[-1]["id"] == "A"
    # 双信号条目得分 > 单信号
    scores = {e["id"]: e["_rrf_score"] for e in fused}
    assert scores["B"] > scores["A"] and scores["C"] > scores["A"]


def test_rrf_backward_compat_two_args():
    """Phase 3 双参调用兼容（entity_hits 缺省 → 行为不变）."""
    r = SemanticRetriever(NullEmbedder())
    semantic = [{"kind": "m", "id": "X", "content": "a", "key": "m:X", "_semantic_score": 0.9}]
    keyword = [{"kind": "m", "id": "Y", "content": "b", "key": "m:Y"}]
    fused = r._rrf_fuse(semantic, keyword, top_k=5)
    assert len(fused) == 2
    assert fused[0]["id"] == "X"  # 语义 rank1 贡献 1/61 > 关键词 rank1 1/61? 相等时语义先入
    assert fused[0]["_rrf_score"] == fused[1]["_rrf_score"]  # 双通道各自 rank1 → 同分


def test_extract_cn_entity_suffix():
    """中文实体: 常见后缀词整词提取."""
    ents = extract_entities("智能体系统处理记忆检索，飞书平台用于通知")
    assert "智能体系统" in ents and "飞书平台" in ents


def test_extract_cn_quoted_entity():
    """中文实体: 引号/书名号包裹专名."""
    ents = extract_entities("「记忆引擎」和「演进闭环」是核心组件")
    assert "记忆引擎" in ents and "演进闭环" in ents


def test_extract_mixed_cn_en():
    """中英混合: 英文专名 + 中文实体共存."""
    ents = extract_entities("DeepSeek 模型与字节跳动 deer-flow 都是热门项目")
    assert "DeepSeek" in ents
    assert any("字节" in e for e in ents) or any("项目" in e for e in ents)
