"""自动改写验证（非 oracle）：8 条全新查询 × LLM 自动改写变体。

与 run_rewrite_probe.py（oracle，改写含 gold 词面）的区别：
- 改写由 LLM 子代理生成，构造时不见 gold keywords（生产形态）；
- 查询为全新 8 条，不在 goldset 30 条内，gold 均为语料中未被 goldset 用过的记录；
- 查询措辞由 goldset 同一构造方起草（构造者偏差仍在查询侧，如实声明），
  但改写主角非构造者，语义漂移判定交新鲜评测者。

判定口径：原查询 fused rank vs 变体 best fused rank（top10 内）
  - 救回 = 原 miss（>10）而变体 best ≤5
  - 不伤 = 原命中时变体 best 不劣于原（容差：仍在 top5）
  - 退化 = 原 ≤5 而变体 best >5
用法：python3 evals/retrieval_ab/run_auto_rewrite_validation.py <rewrites.json>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_fused_eval import build, search_once  # noqa: E402

NEW_QUERIES = [
    {"id": "N01", "query": "换模型要记住我之前选过哪个吗", "gold": "MEM-20260811-7d273d76"},
    {"id": "N02", "query": "规则写太多反而碍事，该留多少", "gold": "MEM-20260901-fff7eafc"},
    {"id": "N03", "query": "改动后怎么知道性能没退步", "gold": "MEM-20260819-4fdb7d80"},
    {"id": "N04", "query": "静态检查工具自己崩了是什么问题", "gold": "MEM-20260818-e575f8eb"},
    {"id": "N05", "query": "输出太长被切断怎么办", "gold": "MEM-20260813-b2364eeb"},
    {"id": "N06", "query": "手滑删了还在用的文件能找回来吗", "gold": "MEM-20260811-c54bb631"},
    {"id": "N07", "query": "什么条件才算第一次就能用", "gold": "MEM-20260913-722e3d3d"},
    {"id": "N08", "query": "远程连回内网机器的网络分流配置", "gold": "MEM-20260811-9dde9612"},
]

def rank_of(ids: list[str], gold: str):
    return (ids.index(gold) + 1) if gold in ids else None

def main() -> None:
    rewrites = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    workdir = Path("/tmp/rt_auto_rewrite")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    mem, sem = build("api", workdir)
    if not sem.semantic_available():
        print("语义不可用，中止"); return

    rows = []
    for q in NEW_QUERIES:
        ids, mode = search_once(mem, sem, q["query"], 10)
        orig = rank_of(ids, q["gold"])
        vr = []
        for v in rewrites.get(q["id"], []):
            vids, _ = search_once(mem, sem, v, 10)
            vr.append({"variant": v, "rank": rank_of(vids, q["gold"])})
        best = min((r["rank"] for r in vr if r["rank"]), default=None)
        if orig is None:
            verdict = "SAVED" if (best is not None and best <= 5) else "STILL-MISS"
        elif orig <= 5:
            verdict = "OK-KEEP" if (best is not None and best <= 5) else "REGRESSION"
        else:
            verdict = "IMPROVED" if (best is not None and best <= 5) else ("GAINED" if best is not None else "NO-GAIN")
        rows.append({"id": q["id"], "query": q["query"], "gold": q["gold"],
                     "orig_rank": orig, "variants": vr, "best_variant_rank": best, "verdict": verdict})
        print(f"{q['id']} orig={str(orig):>4s} best={str(best):>4s} {verdict:10s} | {q['query']}")
        for r in vr:
            print(f"      v rank={str(r['rank']):>4s} | {r['variant']}")

    n_saved = sum(1 for r in rows if r["verdict"] == "SAVED")
    n_reg = sum(1 for r in rows if r["verdict"] == "REGRESSION")
    print(f"\n救回(miss→top5)={n_saved}  退化(top5→出top5)={n_reg}  共{len(rows)}条")
    out = ROOT / "evals/retrieval_ab/auto-rewrite-validation-20260922.json"
    out.write_text(json.dumps({"rewrites_source": sys.argv[1], "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("写入:", out)

if __name__ == "__main__":
    main()
