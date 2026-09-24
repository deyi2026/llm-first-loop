"""线上检索管线离线评测（RRF 三通道融合，非单通道余弦）。

与 run_ab_retrieval.py 的区别（关键）：
  run_ab_retrieval 只测「语义通道纯余弦排序」，其结论不能外推到线上；
  线上 search_records 实际跑的是 _search_memory 链路：
      MemoryStore.search(关键词) → SemanticRetriever.search(RRF 语义+关键词+实体)
  本 runner 直接调用生产类（MemoryStore / SemanticRetriever / RecordSearcher._memory_record），
  参数与 factory.py 构造点一致（timeout_s=1.0, semantic_top_k=20, threshold=bge 校准 0.50），
  因此测到的就是线上真实排序行为。

安全：评测在 data/memory 的临时副本上进行，绝不写生产索引/向量缓存。
用法：python3 evals/retrieval_ab/run_fused_eval.py [--top-k 10] [--provider api|hash]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.memory.embedder import APIEmbedder, HashEmbedder  # noqa: E402
from llm_loop.memory.retriever import SemanticRetriever  # noqa: E402
from llm_loop.memory.store import MemoryStore  # noqa: E402
from llm_loop.introspection.search import RecordSearcher  # noqa: E402

GOLDSET = ROOT / "evals/retrieval_ab/goldset.json"
PROD_MEMORY = ROOT / "data/memory"
# factory.py:1146 构造点实参 + config.py 默认值
TIMEOUT_S, SEMANTIC_TOP_K = 1.0, 20
THRESHOLD = {"api": 0.50, "hash": 0.22}  # retriever._default_threshold 校准值


def build(provider: str, workdir: Path):
    """把生产索引/向量缓存复制到临时目录后构造检索器（只读评测，不写生产）。"""
    for p in PROD_MEMORY.iterdir():
        if p.is_file() and (p.name == "index.json" or p.name.startswith("embeddings")):
            shutil.copy2(p, workdir / p.name)
    mem = MemoryStore(workdir)
    if provider == "api":
        emb = APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge")
    else:
        emb = HashEmbedder()
    sem = SemanticRetriever(
        emb,
        timeout_s=TIMEOUT_S,
        semantic_top_k=SEMANTIC_TOP_K,
        threshold=THRESHOLD[provider],
        memory_dir=workdir,
        archive_dir=workdir,
        fallback_embedder=HashEmbedder(),
    )
    return mem, sem


def search_once(mem, sem, query: str, top_k: int) -> tuple[list[str], str]:
    """复刻 _search_memory：关键词 → RRF 融合。返回 (id 序列, 生效模式)。"""
    keyword = [RecordSearcher._memory_record(e) for e in mem.search(query.split(), top_k=top_k, session_id="")]
    res = sem.search(query, top_k=top_k, scope="memory", session_id="", memory=mem, keyword_results=keyword)
    return [str(e.get("id") or "") for e in res.entries], res.mode


def metrics(ranks: list[int | None], ks: list[int]) -> dict:
    out = {f"h@{k}": sum(1 for r in ranks if r is not None and r <= k) for k in ks}
    out["mrr"] = round(sum((1.0 / r) for r in ranks if r) / len(ranks), 4) if ranks else 0.0
    out["miss"] = sum(1 for r in ranks if r is None)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--provider", default="api", choices=["api", "hash"])
    args = ap.parse_args()

    gold = json.loads(GOLDSET.read_text(encoding="utf-8"))["queries"]
    workdir = Path("/tmp/rt_eval_run")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    mem, sem = build(args.provider, workdir)
    if not sem.semantic_available():
        print("语义不可用，评测中止（如实失败，不降级出数）")
        return

    detail, ranks = [], []
    t0 = time.perf_counter()
    for q in gold:
        ids, mode = search_once(mem, sem, q["query"], args.top_k)
        rank = (ids.index(q["gold"]) + 1) if q["gold"] in ids else None
        ranks.append(rank)
        detail.append({"id": q["id"], "kind": q["kind"], "query": q["query"],
                       "gold": q["gold"], "rank": rank, "mode": mode,
                       "top5": ids[:5]})
        print(f"{q['id']} {q['kind']:10s} rank={str(rank):>4s} mode={mode:8s} {q['query'][:34]}")
    elapsed = time.perf_counter() - t0

    ks = [1, 3, 5, 10]
    summary = metrics(ranks, ks)
    summary["n"] = len(ranks)
    summary["provider"] = args.provider
    summary["corpus"] = len(mem.all())
    summary["elapsed_s"] = round(elapsed, 2)
    by_kind: dict[str, list[int | None]] = {}
    for d, r in zip(detail, ranks):
        by_kind.setdefault(d["kind"], []).append(r)
    summary["by_kind"] = {k: metrics(v, ks) for k, v in by_kind.items()}

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    out = ROOT / f"evals/retrieval_ab/fused-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("写入:", out)


if __name__ == "__main__":
    main()
