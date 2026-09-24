"""检索回归护栏：goldset 三通道指标 + 基线比对（run 1: 护栏固化）。

必跑场景：
  - 嵌入模型变更（EMBEDDING_PROVIDER / 端点模型版本）
  - data/memory 索引重建 / 向量缓存重建
  - SemanticRetriever 参数（threshold / semantic_top_k / RRF）调整
  - MemoryStore.search 关键词逻辑变更
用法：
  首次基线: .venv/bin/python evals/retrieval_ab/regression_gate.py --write-baseline
  回归检查: .venv/bin/python evals/retrieval_ab/regression_gate.py
退出码: 0=达标  2=任一通道退化  3=环境不可用（语义端点离线等）

通道说明（分通道打分的理由：融合总分对单通道退化不敏感，融合会稀释退化信号）：
  keyword  = store.search 子串计数（注意：scope=session 条目在 session_id=""
             下结构性不可召回——设计行为，goldset 中 Q10 在本通道恒 miss）
  semantic = 纯余弦（复刻 retriever._candidates 文本构造: content+keywords）
  fused    = 线上 RRF 三通道（run_fused_eval.search_once）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_loop.memory.embedder import cosine_similarity  # noqa: E402
from llm_loop.introspection.search import RecordSearcher  # noqa: E402
from run_fused_eval import build, search_once, metrics  # noqa: E402

BGE_URL = "http://127.0.0.1:8765/v1/embeddings"
BASELINE = ROOT / "evals/retrieval_ab/regression-baseline.json"
KS = [1, 3, 5, 10]


def bge_batch(inputs: list[str]) -> list[list[float]]:
    req = urllib.request.Request(BGE_URL, method="POST",
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps({"model": "bge", "input": inputs}).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return [x["embedding"] for x in json.loads(r.read())["data"]]


def run_channels(mem, sem, goldset) -> dict:
    entries = mem.all()
    doc_ids = [str(e.id) for e in entries]
    doc_texts = [f"{e.content} {' '.join(e.keywords or [])}" for e in entries]
    doc_vecs = []
    for i in range(0, len(doc_texts), 64):
        doc_vecs.extend(bge_batch(doc_texts[i:i + 64]))
    q_vecs = bge_batch([q["query"] for q in goldset])

    ch: dict[str, list[int | None]] = {"keyword": [], "semantic": [], "fused": []}
    by_kind: dict[str, dict[str, list[int | None]]] = {}
    for q, qv in zip(goldset, q_vecs):
        # keyword 通道
        kw = [RecordSearcher._memory_record(e) for e in mem.search(q["query"].split(), top_k=10, session_id="")]
        kwi = [str(r.get("id") or "") for r in kw]
        ch["keyword"].append((kwi.index(q["gold"]) + 1) if q["gold"] in kwi else None)
        # semantic 通道（纯余弦）
        sc = sorted(range(len(doc_ids)), key=lambda i: cosine_similarity(qv, doc_vecs[i]), reverse=True)
        order = [doc_ids[i] for i in sc[:10]]
        ch["semantic"].append((order.index(q["gold"]) + 1) if q["gold"] in order else None)
        # fused 通道
        fids, _ = search_once(mem, sem, q["query"], 10)
        ch["fused"].append((fids.index(q["gold"]) + 1) if q["gold"] in fids else None)
        by_kind.setdefault(q["kind"], {k: [] for k in ch})
        for k in ch:
            by_kind[q["kind"]][k].append(ch[k][-1])
    return {
        "overall": {k: metrics(v, KS) for k, v in ch.items()},
        "by_kind": {kind: {k: metrics(v, KS) for k, v in m.items()} for kind, m in by_kind.items()},
        "corpus": len(doc_ids),
    }


def check_regression(base: dict, cur: dict) -> list[str]:
    bad = []
    for scope in ("overall", "by_kind"):
        for grp, channels in cur[scope].items():
            for chan, m in channels.items():
                b = base[scope][grp][chan]
                for k in ("h@1", "h@3", "h@5", "h@10"):
                    if m[k] < b[k]:
                        bad.append(f"{scope}/{grp}/{chan}: {k} {b[k]}->{m[k]}")
                if m["mrr"] < b["mrr"] - 1e-9:
                    bad.append(f"{scope}/{grp}/{chan}: mrr {b['mrr']}->{m['mrr']}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()
    goldset = json.loads((ROOT / "evals/retrieval_ab/goldset.json").read_text(encoding="utf-8"))["queries"]
    workdir = Path("/tmp/rt_gate")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    mem, sem = build("api", workdir)
    if not sem.semantic_available():
        print("REGRESSION-GATE: 语义端点不可用，无法出数（exit 3）")
        return 3
    cur = run_channels(mem, sem, goldset)
    print(json.dumps(cur, ensure_ascii=False, indent=2))
    if args.write_baseline:
        BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        print("基线已写入:", BASELINE)
        return 0
    if not BASELINE.exists():
        print("无基线文件，先运行 --write-baseline（exit 2）")
        return 2
    bad = check_regression(json.loads(BASELINE.read_text(encoding="utf-8")), cur)
    if bad:
        print("REGRESSION-GATE: FAIL")
        for b in bad:
            print("  退化:", b)
        return 2
    print("REGRESSION-GATE: PASS（三通道均不低于基线）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
