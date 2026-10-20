"""D7 两段式语义检索单测: LocalOnnxEmbedder 档 + 词法粗筛→本地 ONNX cosine 重排.

分层:
- 管线逻辑（不依赖真实模型）: 注入 fake reranker 断言重排顺序变化 / 向量缓存
  命中（调用计数器）/ 缓存损坏重建 / RERANK_POOL 截断 / 降级零变化
- LocalOnnxEmbedder 档: 目录解析优先级 / 缺模型降级 / 依赖导入失败降级
- 真实模型（三级目录解析任一含两文件才跑，否则 skip）: 统筹者三文本余弦对 +
  端到端 search + 内嵌评估集 AUC（两段式 ≥ 纯词法 且 ≥ 0.75）
"""

from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from llm_loop.memory.embedder import (
    LocalOnnxEmbedder,
    NullEmbedder,
    cosine_similarity,
)
from llm_loop.memory.retrieve import extract_keywords
from llm_loop.memory.retriever import SemanticRetriever, _rerank_model_id
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _resolve_probe_dir() -> Path:
    """三级解析真实模型目录（修订: 原 .tmp-d7-probe 硬编码已随目录迁移失效）.

    env LFL_SEMANTIC_MODEL_DIR > ~/.cache/lfl/models/bge-small-zh-v1.5 >
    原 repo probe 目录；任一含 model_quantized.onnx + tokenizer.json
    两文件（即 LocalOnnxEmbedder.model_files_present）即 ready。
    """
    candidates: list[Path] = []
    env_dir = (os.environ.get("LFL_SEMANTIC_MODEL_DIR") or "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(
        Path.home() / ".cache" / "lfl" / "models" / "bge-small-zh-v1.5"
    )
    candidates.append(Path(__file__).resolve().parents[2] / ".tmp-d7-probe")
    for cand in candidates:
        if LocalOnnxEmbedder(cand).model_files_present():
            return cand
    return candidates[0]


PROBE_DIR = _resolve_probe_dir()
REAL_MODEL_READY = (PROBE_DIR / "model_quantized.onnx").is_file() and (
    PROBE_DIR / "tokenizer.json"
).is_file()
requires_real_model = pytest.mark.skipif(
    not REAL_MODEL_READY,
    reason=(
        "真实模型不在 env LFL_SEMANTIC_MODEL_DIR > ~/.cache/lfl/models/"
        "bge-small-zh-v1.5 > repo .tmp-d7-probe 任一位置"
        "（scripts/download_semantic_model.sh 落位后启用）"
    ),
)


# ── fake reranker（固定向量映射，调用计数）──
class _FakeReranker:
    """规则式 fake: 依序取第一条 子串命中 规则的向量（"" 规则 = 兜底）."""

    provider = "local-onnx"

    def __init__(self, rules: list[tuple[str, list[float]]] | None = None) -> None:
        self.rules: list[tuple[str, list[float]]] = rules or [("", [1.0, 0.0])]
        self.calls = 0

    def embed(self, text: str) -> list[float] | None:
        self.calls += 1
        for needle, vec in self.rules:
            if needle in text:
                return vec
        return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return [self.embed(t) for t in texts]


def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """隔离环境: LFL_SEMANTIC_MODEL_DIR 指向不存在目录 → 无本地模型可自动探测."""
    monkeypatch.setenv("LFL_SEMANTIC_MODEL_DIR", str(tmp_path / "no-model-here"))


def _memory_with(tmp_path: Path, entries: list[tuple[str, list[str]]]) -> MemoryStore:
    mem = MemoryStore(tmp_path / "memory")
    for content, keywords in entries:
        mem.save_entry(
            MemoryEntry(id="", type="fact", content=content, keywords=keywords)
        )
    return mem


# ══ LocalOnnxEmbedder 档（D7-1）══
def test_local_onnx_model_dir_resolution(monkeypatch, tmp_path):
    """目录解析优先级: 显式入参 > env LFL_SEMANTIC_MODEL_DIR > ~/.cache 默认."""
    monkeypatch.setenv("LFL_SEMANTIC_MODEL_DIR", str(tmp_path / "from-env"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
    assert LocalOnnxEmbedder(tmp_path / "explicit").model_dir == tmp_path / "explicit"
    assert LocalOnnxEmbedder().model_dir == tmp_path / "from-env"
    monkeypatch.delenv("LFL_SEMANTIC_MODEL_DIR")
    assert (
        LocalOnnxEmbedder().model_dir
        == tmp_path / "fakehome" / ".cache" / "lfl" / "models" / "bge-small-zh-v1.5"
    )


def test_local_onnx_missing_model_degrades(monkeypatch, tmp_path):
    """缺模型文件: embed 恒 None + semantic_unavailable 标记，不抛出（Null 档语义）."""
    _isolated_env(monkeypatch, tmp_path)
    emb = LocalOnnxEmbedder()
    assert emb.model_files_present() is False
    assert emb.embed("任何文本") is None
    assert emb.embed_batch(["a", "b"]) == [None, None]
    assert emb.semantic_unavailable is True
    assert "missing" in emb.unavailable_reason


def test_local_onnx_dependency_import_failure_degrades(monkeypatch, tmp_path):
    """onnxruntime 导入失败（无依赖环境）: 不抛出，降级标记 + 恒 None."""
    model_dir = tmp_path / "dummy-model"
    model_dir.mkdir()
    (model_dir / "model_quantized.onnx").write_bytes(b"not-a-real-model")
    (model_dir / "tokenizer.json").write_text("{}")
    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # import → ImportError
    emb = LocalOnnxEmbedder(model_dir)
    assert emb.embed("text") is None
    assert emb.semantic_unavailable is True
    assert emb.unavailable_reason.startswith("load failed")


def test_local_onnx_protocol_shape():
    """符合现有 Embedder 三档接口形状（provider/vector_version/MODEL_ID）."""
    assert LocalOnnxEmbedder.provider == "local-onnx"
    assert _rerank_model_id() == LocalOnnxEmbedder.MODEL_ID
    assert _rerank_model_id() in LocalOnnxEmbedder.vector_version


def test_rerank_model_id_derived_from_local_onnx_embedder():
    """修订（批次2 D7 后审）: 重排缓存模型分量派生自 LocalOnnxEmbedder.MODEL_ID.

    原手抄常量副本在换模型时会造成缓存跨模型污染；retriever 不再持有独立
    常量，构造时经 _rerank_model_id() 解析一次存实例属性。
    """
    assert _rerank_model_id() == LocalOnnxEmbedder.MODEL_ID
    retriever = SemanticRetriever(NullEmbedder())
    assert retriever._rerank_model_id == LocalOnnxEmbedder.MODEL_ID
    # 缓存文件名同样由派生 id 决定（防手抄回潮的端到端 pin）
    assert retriever._rerank_cache_file(Path("/tmp/x")).name == (
        f"embeddings-rerank-{LocalOnnxEmbedder.MODEL_ID}.json"
    )


# ══ 两段式管线（fake reranker，不依赖真实模型）══
def test_two_stage_rerank_reorders_lexical_order(tmp_path):
    """词法强者/语义弱者被重排到语义强者之后（两段式改变纯词法顺序）."""
    query = "信号测试偶发失败怎么治理"
    gold = "信号用例需要 serial marker 串行隔离消除时序竞争"  # 词法弱（1 个 bigram）
    trap = "信号测试偶发失败治理 值班记录 时间线 排期看板归档"  # 词法强（bigram 堆叠）
    mem = _memory_with(tmp_path, [(gold, []), (trap, [])])
    fake = _FakeReranker(
        rules=[
            (query, [1.0, 0.0]),  # 查询向量（精确规则优先）
            ("serial", [0.95, 0.05]),  # gold → 高余弦
            ("值班", [0.60, 0.80]),  # trap → 低余弦但过阈值
        ]
    )
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake,
        threshold=0.3,
    )
    # 前置断言: 纯词法粗筛顺序 = trap 在前（重排必须真正改变顺序才有意义）
    pool = retriever._lexical_pool(query, retriever._candidates("memory", "", mem, None, None))
    assert pool[0]["content"].startswith("信号测试偶发失败治理")
    result = retriever.search(query, top_k=5, scope="memory", memory=mem)
    assert result.mode == "semantic"
    assert result.diagnostics["semantic_rerank"] is True
    assert result.diagnostics["rerank_pool_size"] == 2
    contents = [e["content"].strip() for e in result.entries]  # 空 keywords join 尾空格
    assert contents.index(gold) < contents.index(trap)  # 语义重排翻转词法顺序


def test_two_stage_vector_cache_hit(tmp_path):
    """同实例第二次检索: 全部向量缓存命中，embed 调用数不再增长."""
    mem = _memory_with(tmp_path, [("缓存命中率优化降低 API 成本", [])])
    fake = _FakeReranker()  # 兜底规则: 任意文本 → [1,0]
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake,
        threshold=0.3,
    )
    retriever.search("缓存命中", top_k=5, scope="memory", memory=mem)
    first = fake.calls
    assert first > 0
    retriever.search("缓存命中", top_k=5, scope="memory", memory=mem)
    assert fake.calls == first  # 查询+候选全部命中，0 次重算


def test_two_stage_cache_persisted_across_instances(tmp_path):
    """向量缓存落盘（json, key=sha256(text), v=MODEL_ID）→ 新实例 0 次重算."""
    mem = _memory_with(tmp_path, [("缓存命中率优化降低 API 成本", [])])
    fake1 = _FakeReranker()
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake1,
        threshold=0.3,
    )
    retriever.search("缓存命中", top_k=5, scope="memory", memory=mem)
    cache_file = tmp_path / "memory" / f"embeddings-rerank-{LocalOnnxEmbedder.MODEL_ID}.json"
    assert cache_file.is_file()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["v"] == LocalOnnxEmbedder.MODEL_ID  # key 的模型分量派生自 embedder
    assert all(len(key) == 64 for key in payload["data"])  # sha256 hex 键
    fake2 = _FakeReranker()
    retriever2 = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake2,
        threshold=0.3,
    )
    result = retriever2.search("缓存命中", top_k=5, scope="memory", memory=mem)
    assert fake2.calls == 0  # 磁盘缓存全命中
    assert result.diagnostics["semantic_rerank"] is True


def test_two_stage_cache_corrupt_rebuild(tmp_path):
    """缓存文件损坏/截断 → cache miss 重建（不抛错），文件恢复为合法 JSON."""
    mem = _memory_with(tmp_path, [("缓存命中率优化降低 API 成本", [])])
    fake1 = _FakeReranker()
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake1,
        threshold=0.3,
    )
    retriever.search("缓存命中", top_k=5, scope="memory", memory=mem)
    cache_file = tmp_path / "memory" / f"embeddings-rerank-{LocalOnnxEmbedder.MODEL_ID}.json"
    cache_file.write_bytes(b'{"v": "bge-small-zh-v1.5-in')  # 模拟截断
    fake2 = _FakeReranker()
    retriever2 = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake2,
        threshold=0.3,
    )
    result = retriever2.search("缓存命中", top_k=5, scope="memory", memory=mem)
    assert fake2.calls > 0  # 损坏 → miss → 重算
    assert result.mode == "semantic"
    payload = json.loads(cache_file.read_text(encoding="utf-8"))  # 重建后合法
    assert payload["v"] == LocalOnnxEmbedder.MODEL_ID and payload["data"]


def test_two_stage_pool_truncation(tmp_path, monkeypatch):
    """粗筛池截断: RERANK_POOL=3 → 仅 query + top-3 候选进入重排（5 个词法命中）."""
    assert SemanticRetriever.RERANK_POOL == 200  # 常量契约
    monkeypatch.setattr(SemanticRetriever, "RERANK_POOL", 3)
    entries = [(f"治理方案版本{i} 缓存治理要点", []) for i in range(5)]
    mem = _memory_with(tmp_path, entries)
    fake = _FakeReranker()
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=fake,
        threshold=0.3,
    )
    result = retriever.search("缓存治理", top_k=5, scope="memory", memory=mem)
    assert fake.calls == 1 + 3  # 1 query + 截断后 3 候选
    assert result.diagnostics["rerank_pool_size"] == 3
    assert result.diagnostics["semantic_hit_count"] == 3


def test_two_stage_unavailable_keeps_keyword_behavior(monkeypatch, tmp_path):
    """模型目录不存在 → search 行为与现状完全一致（keyword 原样返回）."""
    _isolated_env(monkeypatch, tmp_path)
    mem = _memory_with(tmp_path, [("sigterm 信号测试时序竞争", [])])
    retriever = SemanticRetriever(NullEmbedder(), memory_dir=tmp_path / "memory")
    assert retriever.semantic_available() is False
    keyword_hits = [
        {"kind": "memory", "id": "x", "content": "关键词命中", "key": "memory:x"}
    ]
    result = retriever.search(
        "信号测试", top_k=5, scope="memory", memory=mem, keyword_results=keyword_hits
    )
    assert result.mode == "keyword"
    assert result.entries == keyword_hits
    assert result.note == ""
    assert result.diagnostics["semantic_effective"] is False
    # D7 pin: 模型缺失/加载失败 → 降级纯词法且结果携带 semantic_unavailable 标记
    assert result.diagnostics["semantic_unavailable"] is True


def test_rank_texts_with_reranker(tmp_path):
    """rank_texts 本地重排分支: 注入 fake → 语义排序；无重排器 → []（回退词法）."""
    retriever = SemanticRetriever(
        NullEmbedder(), semantic_reranker=_FakeReranker(
            rules=[("查询", [1.0, 0.0]), ("近", [0.9, 0.1]), ("", [0.0, 1.0])]
        )
    )
    ranked = retriever.rank_texts("查询", ["远的东西", "近的东西"])
    assert [idx for idx, _score in ranked] == [1, 0]
    assert retriever.last_rank_texts_diagnostics["semantic_effective"] is True
    assert retriever.last_rank_texts_diagnostics["engine"] == "rerank"


def test_rerank_cache_concurrent_insert_and_persist(tmp_path):
    """修订（批次2 D7 后审）: 并发缓存写 × 锁内落盘迭代不得抛 RuntimeError.

    回归场景: _rerank_vectors 无锁插入 × _persist_rerank_cache 锁内
    dict.update 迭代 → "dictionary changed size during iteration"
    （未被 except OSError 捕获，违反降级不失败契约）。8 线程 × 50 轮
    并发 _rerank_vectors + _persist_rerank_cache，断言全程无异常。
    """
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory", semantic_reranker=_FakeReranker(),
        threshold=0.3,
    )
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)  # 生产装配中目录恒存在
    errors: list[BaseException] = []

    def churn(worker: int) -> None:
        try:
            reranker = retriever._get_reranker()
            assert reranker is not None
            for i in range(50):
                texts = [f"并发缓存写-{worker}-{i}-{j}" for j in range(4)]
                retriever._rerank_vectors(texts, reranker)  # type: ignore[arg-type]
                retriever._persist_rerank_cache()
        except BaseException as exc:  # noqa: BLE001 — 收集线程内异常统一断言
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(churn, range(8)))

    assert errors == []
    cache_file = (
        tmp_path / "memory" / f"embeddings-rerank-{LocalOnnxEmbedder.MODEL_ID}.json"
    )
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["v"] == LocalOnnxEmbedder.MODEL_ID
    # 无丢失: 8×50×4 个并发写入键必须同时存活于内存缓存与落盘文件
    # （旧代码中无锁插入若落在 persist 的"读缓存→clear"间隙会被静默清除）
    expected_keys = {
        retriever._rerank_cache_key(f"并发缓存写-{w}-{i}-{j}")
        for w in range(8)
        for i in range(50)
        for j in range(4)
    }
    assert expected_keys <= set(payload["data"]), "并发写入在落盘文件中丢失"
    assert expected_keys <= set(retriever._rerank_emb_cache), "并发写入在内存缓存中丢失"


# ══ 真实模型（skipif: 三级目录解析 env > ~/.cache > repo probe，两文件在场）══
@requires_real_model
def test_real_model_gold_beats_filler():
    """统筹者验证三文本: cos(query, gold) > cos(query, filler)."""
    query = "终端信号类测试偶发失败怎么治理"
    gold = "sigterm 信号测试在 CI 并行时序竞争导致 flaky，需要 serial marker 隔离"
    filler = "缓存命中率优化降低 API 成本"
    emb = LocalOnnxEmbedder(PROBE_DIR)
    assert emb.semantic_unavailable is False
    vecs = [emb.embed(t) for t in (query, gold, filler)]
    assert all(v is not None for v in vecs)
    for vec in vecs:
        assert abs(math.sqrt(sum(x * x for x in vec)) - 1.0) < 1e-3  # L2 归一化
    cos_gold = cosine_similarity(vecs[0], vecs[1])
    cos_filler = cosine_similarity(vecs[0], vecs[2])
    print(f"\nreal model cos: gold={cos_gold:.4f} filler={cos_filler:.4f}")
    assert cos_gold > cos_filler


@requires_real_model
def test_real_model_search_end_to_end(tmp_path):
    """端到端: NullEmbedder 主通道 + 真实本地重排器 → gold 排在 filler 前."""
    query = "终端信号类测试偶发失败怎么治理"
    gold = "sigterm 信号测试在 CI 并行时序竞争导致 flaky，需要 serial marker 隔离"
    filler = "缓存命中率优化降低 API 成本"
    mem = _memory_with(tmp_path, [(gold, []), (filler, [])])
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory",
        semantic_reranker=LocalOnnxEmbedder(PROBE_DIR), timeout_s=10.0,
    )
    result = retriever.search(query, top_k=5, scope="memory", memory=mem)
    assert result.mode == "semantic"
    assert result.diagnostics["semantic_rerank"] is True
    contents = [e["content"].strip() for e in result.entries]  # 空 keywords join 尾空格
    assert contents[0] == gold  # gold 第一；filler（cos≈0.38 低于阈值）或被滤除或居后
    if filler in contents:
        assert contents.index(gold) < contents.index(filler)


# ── AUC 评估（D7-4: 内嵌小评估集，题材 = 本 repo 真实概念）──
# (query, gold, [lexical-trap filler, off-topic filler])
# trap filler: 词法 bigram 命中多于 gold（纯词法排序会误排在前），但语义上是
# 归档/记录类稀释文本；off-topic filler: 其他概念主题，词法≈0。
_EVAL_SET: list[tuple[str, str, list[str]]] = [
    (
        "workspace 解析应该以哪条路径为权威",
        "workspace 解析以 RuntimePaths 为唯一权威，禁止 cwd 定位可变状态",
        [
            "workspace 解析路径权威这个问题在历史评审里讨论过很多次，当时的结论记录在周会纪要的附录章节，还附带了幻灯片链接",
            "缓存命中率优化降低 API 成本",
        ],
    ),
    (
        "投影契约变更时如何保证不静默丢字段",
        "投影契约字段显式声明，缺失即报错，绝不静默截断丢失",
        [
            "投影契约变更静默丢字段是大家关心的老话题，例会上有人提起过，相关的讨论归档在月度回顾文档的末尾章节里",
            "briefing 摘要按 token 预算截断",
        ],
    ),
    (
        "终端信号类测试偶发失败怎么治理",
        "sigterm 信号测试在 CI 并行时序竞争导致 flaky，需要 serial marker 隔离",
        [
            "终端信号类测试偶发失败治理的完整时间线记录在值班交接文档里，排期与负责人见任务看板",
            "惰性迁移把迁移成本推迟到首次访问",
        ],
    ),
    (
        "惰性迁移和立即迁移怎么取舍",
        "惰性迁移推迟迁移成本到首次访问，冷启动零开销",
        [
            "惰性迁移立即迁移取舍的争论在架构评审上出现过两轮，双方的观点摘要都写进了会议备忘录供后续查阅",
            "知识评分对旧证据按半衰期衰减",
        ],
    ),
    (
        "pyright 门禁失败该怎么处理",
        "pyright 门禁失败先修 touched 文件类型错误，禁止扩宽基线",
        [
            "pyright 门禁失败处理流程的历史版本存在三份草案，最早的草案在迁移到新仓库后就已经作废不再维护了",
            "briefing 聚焦未决风险",
        ],
    ),
    (
        "知识评分如何对待旧证据",
        "知识评分按半衰期衰减旧证据，近期证据权重更高",
        [
            "知识评分旧证据的问题在季度复盘时被列为待办，负责小组后来把背景材料整理到了共享网盘的深处",
            "sigterm 信号测试需要 serial marker",
        ],
    ),
    (
        "briefing 应该汇报哪些内容",
        "briefing 应该汇报当前目标、关键决策与未决风险三块，帮接手者快速对齐",
        [
            "briefing 汇报内容模板经历过五次改版，旧版留在归档目录深处，新版说明又散落在几篇互相引用的文档之间",
            "pyright 门禁失败先修类型",
        ],
    ),
    (
        "两段式语义检索是怎么工作的",
        "两段式语义检索先词法粗筛 top-200，再本地 ONNX 模型 cosine 重排",
        [
            "两段式语义检索的提案最初写在白板照片里，后来有人口述整理成了非正式笔记，保存在个人的草稿箱内",
            "惰性迁移推迟迁移成本",
        ],
    ),
]


def _candidate_dicts(texts: list[str]) -> list[dict]:
    return [
        {"kind": "memory", "id": str(i), "content": text, "key": f"m{i}"}
        for i, text in enumerate(texts)
    ]


def _lexical_order(query: str, cands: list[dict]) -> list[str]:
    """(a) 纯词法排序: 现有打分函数（extract_keywords + 子串命中计数）降序."""
    keywords = extract_keywords(query)
    ranked = sorted(
        cands, key=lambda c: (-SemanticRetriever._lexical_score(keywords, c), int(c["id"]))
    )
    return [c["key"] for c in ranked]


def _two_stage_order(retriever: SemanticRetriever, query: str, cands: list[dict]) -> list[str]:
    """(b) 两段式排序: 词法粗筛入池 → 本地 ONNX cosine 重排；池外垫底."""
    pool = retriever._lexical_pool(query, cands)
    reranker = retriever._get_reranker()
    assert reranker is not None
    vectors = retriever._rerank_vectors(
        [query] + [c["content"] for c in pool], reranker
    )
    assert vectors is not None and vectors[0] is not None
    cos = {
        c["key"]: cosine_similarity(vectors[0], vec)
        for c, vec in zip(pool, vectors[1:], strict=True)
        if vec is not None
    }
    tail = [c["key"] for c in cands if c not in pool]
    head = [c["key"] for c in sorted(pool, key=lambda c: -cos.get(c["key"], 0.0))]
    return head + tail


def _pairwise_auc(pairs: list[tuple[int, int]]) -> float:
    """AUC = 正确对/总对（gold 排在 filler 前 = 1；并列 = 0.5）."""
    if not pairs:
        return 0.0
    correct = sum(
        1.0 if gold_rank < filler_rank else 0.5 if gold_rank == filler_rank else 0.0
        for gold_rank, filler_rank in pairs
    )
    return correct / len(pairs)


@requires_real_model
def test_real_model_auc_two_stage_vs_lexical(tmp_path):
    """内嵌评估集（8 query × 1 gold + 2 filler）: 两段式 AUC ≥ 纯词法 且 ≥ 0.75."""
    retriever = SemanticRetriever(
        NullEmbedder(), memory_dir=tmp_path / "memory",
        semantic_reranker=LocalOnnxEmbedder(PROBE_DIR), timeout_s=60.0,
    )
    lexical_pairs: list[tuple[int, int]] = []
    two_stage_pairs: list[tuple[int, int]] = []
    for query, gold, fillers in _EVAL_SET:
        cands = _candidate_dicts([gold, *fillers])
        lex_order = _lexical_order(query, cands)
        two_order = _two_stage_order(retriever, query, cands)
        for filler_idx in range(len(fillers)):
            gold_key, filler_key = "m0", f"m{filler_idx + 1}"
            lexical_pairs.append(
                (lex_order.index(gold_key), lex_order.index(filler_key))
            )
            two_stage_pairs.append(
                (two_order.index(gold_key), two_order.index(filler_key))
            )
    auc_lexical = _pairwise_auc(lexical_pairs)
    auc_two_stage = _pairwise_auc(two_stage_pairs)
    print(
        f"\nAUC: 纯词法={auc_lexical:.4f}  两段式={auc_two_stage:.4f} "
        f"(评估集: {len(_EVAL_SET)} query × {len(lexical_pairs)} 对)"
    )
    assert auc_two_stage >= auc_lexical  # 容差 0: 严格不降
    assert auc_two_stage >= 0.75
