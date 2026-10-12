"""EVO-20260924-d9c5ad20: 冷启动批量预热 + embedding 缓存持久化去抖（零 LLM 零网络）.

回归背景：_embed_cached 原对每个未缓存候选逐条 embed 且每条全量重写缓存 JSON
（N 条新文档 = N 次 ~2MB 序列化落盘），语料增长后首批检索在 timeout_s=1.0 下
超时→静默回退 keyword（evals/retrieval_ab 2026-09-24 实测 h@5 14→9~12）。
"""
from __future__ import annotations

import json

from llm_loop.memory.embedder import APIEmbedder, HashEmbedder
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry, MemoryStore


class _CountingHash(HashEmbedder):
    """带单条计数的 HashEmbedder（基类不带 embed_batch = 模拟旧实现）。"""

    def __init__(self) -> None:
        super().__init__()
        self.n_embed = 0

    def embed(self, text: str):
        self.n_embed += 1
        return super().embed(text)


class _BatchCountingHash(_CountingHash):
    """带批量计数的 HashEmbedder；批量内部用 super().embed（不污染单条计数）。"""

    def __init__(self) -> None:
        super().__init__()
        self.n_batch = 0

    def embed_batch(self, texts):
        self.n_batch += 1
        return [HashEmbedder.embed(self, t) for t in texts]


def _store(n: int, tmp_path):
    mem = MemoryStore(tmp_path / "memory")
    for i in range(n):
        mem.save_entry(MemoryEntry(id=f"m{i}", type="fact", content=f"事实条目编号{i}的内容",
                                   keywords=[f"条目{i}"]))
    return mem


def _retriever(embedder, tmp_path, timeout_s: float = 5.0):
    return SemanticRetriever(embedder, timeout_s=timeout_s, memory_dir=tmp_path / "memory")


def test_persist_debounce_single_write(tmp_path, monkeypatch):
    """N 条未缓存候选一次 search → 落盘恰好 1 次（原实现为 N 次），文件含全部键。"""
    mem = _store(5, tmp_path)
    r = _retriever(_CountingHash(), tmp_path)
    calls = []
    orig = SemanticRetriever._persist_emb_cache
    monkeypatch.setattr(SemanticRetriever, "_persist_emb_cache",
                        lambda self, path, cache, emb=None: calls.append(path) or orig(self, path, cache, emb))
    r.search("事实条目", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    assert len(calls) == 1, f"去抖后应恰好 1 次落盘，实际 {len(calls)}"
    assert r._mem_cache_path is not None
    raw = json.loads(r._mem_cache_path.read_text(encoding="utf-8"))
    assert sum(1 for k in raw["data"] if k.startswith("memory:")) == 5


def test_cache_hit_no_rewrite(tmp_path, monkeypatch):
    """第二次 search 全命中缓存 → 0 次落盘。"""
    mem = _store(4, tmp_path)
    r = _retriever(_CountingHash(), tmp_path)
    r.search("条目", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    calls = []
    monkeypatch.setattr(SemanticRetriever, "_persist_emb_cache",
                        lambda self, path, cache, emb=None: calls.append(1))
    r.search("条目", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    assert calls == [], "全命中缓存不应再落盘"


def test_batch_prewarm_used(tmp_path):
    """冷启动走批量预热：embed_batch 1 次、单条 embed 0 次（全部成功时）。"""
    mem = _store(6, tmp_path)
    emb = _BatchCountingHash()
    r = _retriever(emb, tmp_path)
    res = r.search("事实条目编号三", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    assert res.mode in ("semantic", "mixed")
    assert emb.n_batch == 1
    assert emb.n_embed == 1  # 仅查询向量 1 次单条；候选全走批量
    assert len(r._mem_emb_cache) == 6


def test_no_batchattr_fallback(tmp_path):
    """旧实现无 embed_batch → 循环内逐条 embed 兜底，结果/缓存一致。"""
    mem = _store(4, tmp_path)
    emb = _CountingHash()  # 基类无 embed_batch → getattr 探测 None
    r = _retriever(emb, tmp_path)
    res = r.search("条目", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    assert res.mode in ("semantic", "mixed")
    assert emb.n_embed == 5  # 1 查询 + 4 候选逐条
    assert len(r._mem_emb_cache) == 4


def test_batch_mismatch_fallback(tmp_path, monkeypatch):
    """批量结果条数不齐 → 整批丢弃，逐条路径兜底（不写错位向量）。"""
    mem = _store(4, tmp_path)
    emb = _BatchCountingHash()
    r = _retriever(emb, tmp_path)
    seen = {}

    def bad_batch(texts):
        seen["n"] = len(texts)
        return [[0.1] * 128] * (len(texts) - 1)  # 少一条

    monkeypatch.setattr(emb, "embed_batch", bad_batch)
    res = r.search("条目", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    assert seen["n"] == 4
    assert res.mode in ("semantic", "mixed")
    assert emb.n_embed == 5  # 批量作废后逐条兜底
    # 逐条真向量（非错位哨兵）
    assert all(len(v) == 128 and any(x for x in v) for v in r._mem_emb_cache.values())


def test_timeout_path_flushes_cache(tmp_path, monkeypatch):
    """超时降级 keyword 也不丢已预热向量（finally 去抖落盘）。

    fake clock：预热片检查时预算充足 → 5 条全部批量嵌入；打分循环首候选时
    时钟跳到远超 deadline → 超时降级返回；finally flush 应把预热成果落盘。
    """
    from llm_loop.memory import retriever as rt

    mem = _store(5, tmp_path)
    emb = _BatchCountingHash()
    r = _retriever(emb, tmp_path, timeout_s=10.0)
    clock = iter([
        0.0,  # search start
        0.0,  # query deadline remaining
        0.0,  # query embed start
        0.0,  # query embed elapsed
        1.0,  # prewarm 首片前 deadline 检查（1 < 10，放行）
    ])
    monkeypatch.setattr(rt.time, "monotonic", lambda: next(clock, 999.0))
    res = r.search("条目", top_k=3, scope="memory", session_id="", memory=mem, archive=None)
    assert res.mode == "keyword", "循环首候选时钟=999 应超时降级"
    assert emb.n_batch == 1 and len(r._mem_emb_cache) == 5
    assert r._mem_cache_path is not None
    raw = json.loads(r._mem_cache_path.read_text(encoding="utf-8"))
    assert sum(1 for k in raw["data"] if k.startswith("memory:")) == 5, "超时路径应保留批量预热成果"


def test_api_embed_batch_roundtrip(monkeypatch):
    """APIEmbedder.embed_batch：按位对齐；空文本位置 None。"""
    api = APIEmbedder(api_key="", base_url="http://127.0.0.1:9/v1", model="bge")
    calls = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json["input"])
        assert headers["X-LFL-Embedding-Class"] == "background"
        assert headers["X-LFL-Embedding-Deadline-Ms"] == "250"
        assert timeout == 1.5
        return _Resp()

    monkeypatch.setattr(api._client, "post", fake_post)
    out = api.embed_batch(["甲", "", "乙"])
    assert out == [[0.1, 0.2], None, [0.3, 0.4]]
    assert calls == [["甲", "乙"]], "空文本不应进批"


def test_api_embed_batch_mismatch_falls_back(monkeypatch):
    """API 响应条数不齐 → 当前后台 chunk 留空，后续预热轮次再重试。"""
    api = APIEmbedder(api_key="", base_url="http://127.0.0.1:9/v1", model="bge")

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": [{"embedding": [0.1]}]}  # 请求 2 条只回 1 条

    monkeypatch.setattr(api._client, "post", lambda *a, **k: _Resp())
    out = api.embed_batch(["甲", "乙"])
    assert out == [None, None], "后台批次失败不应串行逐条放大"


def test_api_embed_batch_yields_between_background_chunks(monkeypatch):
    """后台预热多片之间主动 yield，最后一片后不额外 sleep."""
    api = APIEmbedder(api_key="", base_url="http://127.0.0.1:9/v1", model="bge")
    api._BATCH_CHUNK = 2
    api._BATCH_YIELD_S = 0.02
    sleeps = []
    calls = []

    class _Resp:
        status_code = 200

        def __init__(self, n):
            self._n = n

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2]} for _ in range(self._n)]}

    def fake_post(_url, **kwargs):
        batch = kwargs["json"]["input"]
        calls.append(list(batch))
        return _Resp(len(batch))

    monkeypatch.setattr(api._client, "post", fake_post)
    monkeypatch.setattr("llm_loop.memory.embedder.time.sleep", lambda s: sleeps.append(s))

    out = api.embed_batch(["a", "b", "c", "d", "e"])

    assert all(v == [0.1, 0.2] for v in out)
    assert calls == [["a", "b"], ["c", "d"], ["e"]]
    assert sleeps == [0.02, 0.02]
