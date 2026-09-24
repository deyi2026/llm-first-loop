"""多查询融合评测：原查询 + 盲自动改写变体，各走一遍线上 fused 链路，RRF 融合排序。

对照锚点（docs/REPORT-20260922-retrieval-miss-attribution.md）：
- 基线（单查询 paraphrase fused）: h@5 = 14/25
- oracle 上限（gold 词面改写）:   h@5 = 21/25
本实验测定：LLM 盲改写（不见 gold）+ 多查询 RRF 融合能吃到多少上限。

口径：
- 每条查询 texts = [原查询, 变体1, 变体2...]，各自 search_once(top_k) 得 fused 列表
- multiquery_fused = RRF(k=60) 融合各列表后的 gold 排名
- any_variant_best = 任一单列表内 gold 最好排名（融合可达上限的诊断）
- miss = gold 不在任何列表

用法：python3 evals/retrieval_ab/run_multiquery_fusion.py <rewrites.json> [--rrf-k 60] [--top-k 20] [--include-control]
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_fused_eval import build, search_once  # noqa: E402

GOLDSET = ROOT / "evals/retrieval_ab/goldset.json"


def rrf_fuse(lists: list[list[str]], k: int = 60) -> list[str]:
    """RRF 融合多个 id 序列（k=60 常规值），返回按融合分降序的 id 列表。"""
    scores: dict[str, float] = {}
    for ids in lists:
        for rank, rid in enumerate(ids, start=1):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
    return [rid for rid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]



def prewarm(mem, sem) -> int:
    """显式预热：把语料缺失向量一次性补齐（对齐 regression_gate 的 bge_batch 前置做法）。

    必要性：retriever._embed_cached 逐条惰性嵌入且每条 persist 整个缓存 JSON，
    冷启动（语料增长后首批查询）在生产 timeout_s=1.0 下必然超时→静默 keyword 回退，
    造成 run 间指标抖动。预热后评测才是可复现的语义通道行为。
    """
    before = len(sem._mem_emb_cache)
    for e in mem.all():
        key = f"memory:{e.id}"
        if key not in sem._mem_emb_cache:
            vec = sem.embedder.embed(f"{e.content} {' '.join(e.keywords or [])}")
            if vec:
                sem._mem_emb_cache[key] = vec
    return len(sem._mem_emb_cache) - before


def metrics(ranks: list[int | None], ks: list[int]) -> dict:
    out = {f"h@{k}": sum(1 for r in ranks if r is not None and r <= k) for k in ks}
    out["mrr"] = round(sum((1.0 / r) for r in ranks if r) / len(ranks), 4) if ranks else 0.0
    out["miss"] = sum(1 for r in ranks if r is None)
    return out


def rank_of(ids: list[str], gold: str) -> int | None:
    return (ids.index(gold) + 1) if gold in ids else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rewrites")
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--include-control", action="store_true")
    args = ap.parse_args()

    queries = json.loads(GOLDSET.read_text(encoding="utf-8"))["queries"]
    gold = [q for q in queries if q["kind"] == "paraphrase" or args.include_control]
    rewrites = json.loads(Path(args.rewrites).read_text(encoding="utf-8"))
    missing = [q["id"] for q in gold if q["id"] not in rewrites]
    if missing:
        print(f"缺改写条目: {missing}（该口径要求全覆盖，中止）")
        return

    workdir = Path("/tmp/rt_mq_fusion")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    mem, sem = build("api", workdir)
    if not sem.semantic_available():
        print("语义不可用，评测中止（如实失败，不降级出数）")
        return
    warmed = prewarm(mem, sem)
    print(f"prewarm: 补嵌 {warmed} 条语料向量（消除冷启动超时回退）")

    ks = [1, 3, 5, 10]
    detail, ranks_fused, ranks_orig, ranks_best = [], [], [], []
    t0 = time.perf_counter()
    for q in gold:
        texts = [q["query"]] + [str(v) for v in rewrites.get(q["id"], [])]
        lists, per = [], []
        for t in texts:
            ids, mode = search_once(mem, sem, t, args.top_k)
            lists.append(ids)
            per.append({"text": t, "rank": rank_of(ids, q["gold"]), "mode": mode})
        fused = rrf_fuse(lists, args.rrf_k)
        r_fused = rank_of(fused, q["gold"])
        r_orig = per[0]["rank"]
        r_best = min((p["rank"] for p in per if p["rank"]), default=None)
        ranks_fused.append(r_fused)
        ranks_orig.append(r_orig)
        ranks_best.append(r_best)
        if r_orig is None:
            verdict = "SAVED" if (r_fused is not None and r_fused <= 5) else "STILL-MISS"
        elif r_orig <= 5:
            verdict = "OK-KEEP" if (r_fused is not None and r_fused <= 5) else "REGRESSION"
        else:
            verdict = "IMPROVED" if (r_fused is not None and r_fused <= 5) else "NO-GAIN"
        detail.append({"id": q["id"], "query": q["query"], "gold": q["gold"],
                       "orig_rank": r_orig, "fused_rank": r_fused, "best_single_rank": r_best,
                       "variants": per[1:], "verdict": verdict})
        print(f"{q['id']} orig={str(r_orig):>4s} fused={str(r_fused):>4s} best={str(r_best):>4s} "
              f"{verdict:10s} | {q['query'][:30]}")
    elapsed = time.perf_counter() - t0

    summary = {
        "n": len(ranks_fused),
        "rrf_k": args.rrf_k,
        "top_k": args.top_k,
        "corpus": len(mem.all()),
        "elapsed_s": round(elapsed, 2),
        "baseline_single_query": metrics(ranks_orig, ks),
        "multiquery_fused": metrics(ranks_fused, ks),
        "any_variant_best_diagnostic": metrics(ranks_best, ks),
        "verdicts": {v: sum(1 for d in detail if d["verdict"] == v)
                     for v in ("SAVED", "OK-KEEP", "REGRESSION", "IMPROVED", "NO-GAIN", "STILL-MISS")},
        "reference": {"baseline_paraphrase_fused_h5_reg": 14, "oracle_ceiling_h5": 21},
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    out = ROOT / f"evals/retrieval_ab/multiquery-fusion-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"rewrites_source": args.rewrites, "summary": summary,
                               "detail": detail}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("写入:", out)


if __name__ == "__main__":
    main()
