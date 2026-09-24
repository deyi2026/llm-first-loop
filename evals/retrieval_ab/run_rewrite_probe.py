"""miss 归因分桶之 oracle 改写干预实验（run 1: 查询侧桶上限测定）。

问题：8 条 miss 是否可通过「术语桥接改写」救回？
方法：对每条 miss 用其 gold 记录的真实词面（keywords/text 术语）构造
     oracle 改写查询，跑线上融合链路 + 关键词单通道，观察 gold rank。
分桶判据：
  查询侧 = oracle 后融合 rank<=5（词面桥接即可救，值得做查询改写）
  语料/模型侧 = oracle 后仍 miss（词面到位仍不行，改写无收益）
依赖：本地 8765 bge 端点；goldset.json（bbff7f4f2 版）。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_loop.introspection.search import RecordSearcher  # noqa: E402
from run_fused_eval import build, search_once  # noqa: E402

ORACLE = {
    "Q03": "配置非法值回退默认 fail-safe Method Learning",
    "Q04": "LLM调用异常 回答前缀 honesty.py 三件套",
    "Q07": "tool_trim 上下文占用率 裁剪规则",
    "Q10": "用户工作模式 源码深读 交叉验证",
    "Q11": "Evidence Recoverability R7-V2 验证结果",
    "Q15": "完成声明 工具回执 校验 如实声明",
    "Q21": "LLMHTTPError HTTP 500 reasoning effort 参数错误",
    "Q22": "已知红清单 known-reds 测试失败 基线",
}


def kw_rank(mem, query: str, gold: str, topk: int = 20):
    kw = [RecordSearcher._memory_record(e) for e in mem.search(query.split(), top_k=topk, session_id="")]
    ids = [str(e.get("id") or "") for e in kw]
    return (ids.index(gold) + 1) if gold in ids else None


def main() -> None:
    goldset = json.loads((ROOT / "evals/retrieval_ab/goldset.json").read_text(encoding="utf-8"))["queries"]
    workdir = Path("/tmp/rt_rewrite_probe")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    mem, sem = build("api", workdir)
    if not sem.semantic_available():
        print("语义不可用，中止")
        return

    rows = []
    for q in goldset:
        if q["kind"] != "paraphrase":
            continue
        ids, _ = search_once(mem, sem, q["query"], 10)
        rank = (ids.index(q["gold"]) + 1) if q["gold"] in ids else None
        rows.append((q["id"], q["query"], q["gold"], rank))
        print(f"{q['id']} orig_rank={str(rank):>4s} {q['query'][:30]}")
    miss = [r for r in rows if r[3] is None]
    print(f"\n原查询 miss={len(miss)}/25: {[r[0] for r in miss]}")

    print("\n===== oracle rewrite =====")
    results = []
    for qid, query, gid, _ in miss:
        rw = ORACLE.get(qid)
        ids, mode = search_once(mem, sem, rw, 10)
        rank = (ids.index(gid) + 1) if gid in ids else None
        kr = kw_rank(mem, rw, gid)
        ok = rank is not None and rank <= 5
        results.append({"id": qid, "orig": query, "oracle": rw, "fused_rank": rank,
                        "kw_rank": kr, "mode": mode, "saved": ok})
        print(f"{qid} fused={str(rank):>4s} kw={str(kr):>4s} mode={mode:8s} "
              f"{'SAVED' if ok else 'STILL-MISS'} | {rw}")
    saved = sum(r["saved"] for r in results)
    print(f"\noracle 救回 {saved}/{len(results)}  (查询侧桶上限)")
    out = ROOT / "evals/retrieval_ab/rewrite-probe-20260922.json"
    out.write_text(json.dumps({"miss_ids": [r[0] for r in miss], "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("写入:", out)


if __name__ == "__main__":
    main()
