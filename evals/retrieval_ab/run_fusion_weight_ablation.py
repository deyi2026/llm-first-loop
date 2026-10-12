"""融合权重消融：orig 加权 RRF / 一致性重排 vs 等权 RRF（REPORT-20260924 建议下一步）。

背景（docs/REPORT-20260924-retrieval-multiquery-fusion.md）：
- 等权 list-RRF(k=60) 融合 [orig, v1, v2]：h@5 16 vs 单查询 14；剩余损失主要在融合权重
  （稀释 3 条 + 主动伤害 1 条），变体诊断上限 h@5=19。
- goldset 25 条已兼作 dev set，继续调参必须 held-out 验证 → 复用 09-22 的 8 条 N-queries
  （auto-rewrite-validation-20260922.json，含盲变体文本）。

策略（全部离线计算，共享同一次检索收集，零重复嵌入）：
- equal    : w=[1,1,1] 等权 RRF（对照，应≈上次 16）
- ow{1.5,2,3,5}: 加权 RRF score=Sum w_i/(k+rank_i)，orig 列表权重 >1
- vote     : equal RRF 分 × 出现列表数（共识投票乘法重排）
- ow2vote  : ow2 加权分 × 出现列表数

预先声明的决策规则（防事后挑选）：
- dev 上按 (h@5, h@1, MRR) 字典序选最优策略；
- 该策略在 held-out 上相对 equal 的 Delta 做方向性验证（n=8，只看方向不谈显著）。

用法：python3 evals/retrieval_ab/run_fusion_weight_ablation.py [--rrf-k 60] [--top-k 20]
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
from run_multiquery_fusion import prewarm  # noqa: E402

GOLDSET = ROOT / "evals/retrieval_ab/goldset.json"
DEV_REWRITES = ROOT / "evals/retrieval_ab/auto-rewrites-goldset25-20260924.json"
HELDOUT = ROOT / "evals/retrieval_ab/auto-rewrite-validation-20260922.json"

STRATEGIES: dict[str, dict] = {
    "equal": {"w_orig": 1.0, "vote": False},
    "ow1.5": {"w_orig": 1.5, "vote": False},
    "ow2": {"w_orig": 2.0, "vote": False},
    "ow3": {"w_orig": 3.0, "vote": False},
    "ow5": {"w_orig": 5.0, "vote": False},
    "vote": {"w_orig": 1.0, "vote": True},
    "ow2vote": {"w_orig": 2.0, "vote": True},
}


def fuse(lists: list[list[str]], k: int, w_orig: float, vote: bool) -> list[str]:
    """加权 RRF；vote=True 时融合分乘以出现列表数（共识乘法重排）。"""
    scores: dict[str, float] = {}
    nlists: dict[str, int] = {}
    for i, ids in enumerate(lists):
        w = w_orig if i == 0 else 1.0
        for rank, rid in enumerate(ids, start=1):
            scores[rid] = scores.get(rid, 0.0) + w / (k + rank)
            nlists[rid] = nlists.get(rid, 0) + 1
    final = {rid: s * (nlists[rid] if vote else 1) for rid, s in scores.items()}
    return [rid for rid, _ in sorted(final.items(), key=lambda kv: (-kv[1], kv[0]))]


def rank_of(ids: list[str], gold: str) -> int | None:
    return (ids.index(gold) + 1) if gold in ids else None


def metrics(ranks: list[int | None]) -> dict:
    out = {f"h@{k}": sum(1 for r in ranks if r is not None and r <= k) for k in (1, 3, 5, 10)}
    out["mrr"] = round(sum((1.0 / r) for r in ranks if r) / len(ranks), 4) if ranks else 0.0
    out["miss"] = sum(1 for r in ranks if r is None)
    return out


def collect(mem, sem, rows, rewrites, top_k: int) -> list[dict]:
    """rows: [{id,query,gold}]；返回每查询的完整 3-列表（含 orig），供离线融合。"""
    out = []
    for q in rows:
        texts = [q["query"]] + [str(v) for v in rewrites.get(q["id"], [])]
        if len(texts) < 2:
            print(f"{q['id']} 缺变体，跳过（要求全覆盖）")
            return []
        lists, per = [], []
        for t in texts:
            ids, mode = search_once(mem, sem, t, top_k)
            lists.append(ids)
            per.append({"text": t, "rank": rank_of(ids, q["gold"]), "mode": mode})
        out.append({"id": q["id"], "query": q["query"], "gold": q["gold"], "lists": lists, "per": per})
        best = min((p["rank"] for p in per if p["rank"]), default=None)
        print(f"  {q['id']} orig={str(per[0]['rank']):>4s} best={str(best):>4s} | {q['query'][:30]}")
    return out


def evaluate(collected: list[dict], k: int) -> tuple[dict[str, dict], dict[str, list[int | None]]]:
    table, rankmap = {}, {}
    for name, cfg in STRATEGIES.items():
        ranks = []
        for row in collected:
            fused = fuse(row["lists"], k, cfg["w_orig"], cfg["vote"])
            ranks.append(rank_of(fused, row["gold"]))
        table[name] = metrics(ranks)
        rankmap[name] = ranks
    return table, rankmap


def pick_dev_best(table: dict[str, dict]) -> str:
    return max(table, key=lambda n: (table[n]["h@5"], table[n]["h@1"], table[n]["mrr"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

    dev_rows = [q for q in json.loads(GOLDSET.read_text(encoding="utf-8"))["queries"]
                if q["kind"] == "paraphrase"]
    dev_rw = json.loads(DEV_REWRITES.read_text(encoding="utf-8"))
    ho_raw = json.loads(HELDOUT.read_text(encoding="utf-8"))["rows"]
    ho_rows = [{"id": r["id"], "query": r["query"], "gold": r["gold"]} for r in ho_raw]
    ho_rw = {r["id"]: [v["variant"] for v in r["variants"]] for r in ho_raw}

    workdir = Path("/tmp/rt_mq_weight")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    mem, sem = build("api", workdir)
    if not sem.semantic_available():
        print("语义不可用，评测中止（如实失败，不降级出数）")
        return
    t0 = time.perf_counter()
    warmed = prewarm(mem, sem)
    print(f"prewarm: 补嵌 {warmed} 条（{time.perf_counter() - t0:.1f}s），corpus={len(mem.all())}")

    print("\n=== collect: dev (goldset25 paraphrase) ===")
    dev = collect(mem, sem, dev_rows, dev_rw, args.top_k)
    print("=== collect: held-out (N-queries 8) ===")
    ho = collect(mem, sem, ho_rows, ho_rw, args.top_k)
    if not dev or not ho:
        return

    dev_table, dev_ranks = evaluate(dev, args.rrf_k)
    ho_table, ho_ranks = evaluate(ho, args.rrf_k)
    best = pick_dev_best(dev_table)

    for name, table in (("DEV(25)", dev_table), ("HELD-OUT(8)", ho_table)):
        print(f"\n=== {name} ===")
        print(f"{'strategy':9s} h@1 h@3 h@5 h@10  MRR    miss")
        for sname, m in sorted(table.items(), key=lambda kv: -kv[1]["h@5"]):
            mark = " <-dev-best" if sname == best and name.startswith("DEV") else ""
            print(f"{sname:9s} {m['h@1']:3d} {m['h@3']:3d} {m['h@5']:3d} {m['h@10']:3d}  "
                  f"{m['mrr']:.3f}  {m['miss']:3d}{mark}")

    d_h1 = ho_table[best]["h@1"] - ho_table["equal"]["h@1"]
    d_h5 = ho_table[best]["h@5"] - ho_table["equal"]["h@5"]
    d_mrr = round(ho_table[best]["mrr"] - ho_table["equal"]["mrr"], 3)
    print(f"\n决策：dev 最优 = {best}；held-out 相对 equal Dh@1={d_h1:+d} Dh@5={d_h5:+d} DMRR={d_mrr:+.3f}"
          f"（n=8，方向性验证）")

    out = ROOT / f"evals/retrieval_ab/fusion-weight-ablation-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({
        "config": {"rrf_k": args.rrf_k, "top_k": args.top_k, "corpus": len(mem.all()),
                   "strategies": STRATEGIES,
                   "decision_rule": "dev (h@5,h@1,mrr) 字典序最优 -> held-out 方向性验证"},
        "dev": {"table": dev_table, "ranks": dev_ranks,
                "collected": [{k: v for k, v in r.items() if k != "lists"} for r in dev]},
        "heldout": {"table": ho_table, "ranks": ho_ranks,
                    "collected": [{k: v for k, v in r.items() if k != "lists"} for r in ho]},
        "dev_best": best, "heldout_delta": {"h@1": d_h1, "h@5": d_h5, "mrr": d_mrr},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("写入:", out)


if __name__ == "__main__":
    main()
