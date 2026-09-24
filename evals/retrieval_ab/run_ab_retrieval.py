#!/usr/bin/env python3
"""hash vs bge 语义检索 A/B（验证「缺的是语义不是系统」）.

零 env 依赖（文件化运行）:
- hash: 直接 import 生产 HashEmbedder（字符 2+3-gram md5 → 128 维）
- bge:  本地 8765 OpenAI 兼容端点（当前生产 EMBEDDING_PROVIDER=api 同款）
- 关键词基线: 复刻 store.search 的子串包含计数
文档向量文本构造复刻 retriever._candidates: content + ' ' + keywords.join(' ')
"""
import json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from llm_loop.memory.embedder import HashEmbedder, cosine_similarity  # noqa: E402

BGE_URL = "http://127.0.0.1:8765/v1/embeddings"
BGE_MODEL = "bge"
GOLD = json.loads((ROOT / "evals/retrieval_ab/goldset.json").read_text())["queries"]

# ── 语料（与生产检索同一候选池）──
idx = json.loads((ROOT / "data/memory/index.json").read_text())
docs = {e["id"]: f"{e.get('content','')} {' '.join(e.get('keywords', []) or [])}" for e in idx}
ids, texts = list(docs.keys()), list(docs.values())
print(f"语料: {len(ids)} 条")

# ── 三通道向量/分数 ──
h = HashEmbedder()
t0 = time.time()
H = [h.embed(t) for t in texts]
print(f"hash 向量: {len(H)} 条, {time.time()-t0:.1f}s")

import urllib.request
def bge_batch(inputs):
    req = urllib.request.Request(BGE_URL, method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"model": BGE_MODEL, "input": inputs}).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return [x["embedding"] for x in d["data"]]

t0 = time.time()
B = []
for i in range(0, len(texts), 64):
    B.extend(bge_batch(texts[i:i+64]))
print(f"bge 向量: {len(B)} 条, {time.time()-t0:.1f}s")

q_texts = [q["query"] for q in GOLD]
QB = bge_batch(q_texts)  # 单请求批量
QH = [h.embed(t) for t in q_texts]

def rank(qv, M):
    sc = [cosine_similarity(qv, m) for m in M]
    order = sorted(range(len(ids)), key=lambda i: sc[i], reverse=True)
    return [(ids[i], round(sc[i], 4)) for i in order]

KW_STOP = set("了 的 吗 有 什么 怎么 为什么 哪个 哪里 是 在 和 与 用 会 到 从 按 应该 实际 现在 一个".split())
def kw_score(query):
    toks = [w for w in re.split(r"[\s，。？?、,]+", query.lower()) if len(w) >= 2 and w not in KW_STOP]
    hay = {i: texts[k].lower() for k, i in enumerate(ids)}
    sc = {i: sum(1 for w in toks if w in hay[i]) for i in ids}
    order = sorted(ids, key=lambda i: sc[i], reverse=True)[: 200]
    return [(i, sc[i]) for i in order if sc[i] > 0]

# ── 评测 ──
res = []
for q, qh, qb in zip(GOLD, QH, QB):
    rh, rb = rank(qh, H), rank(qb, B)
    rk = kw_score(q["query"])
    def pos(lst, g):  # rank 位置（1-based）
        for n, (i, s) in enumerate(lst, 1):
            if i == g: return n
        return None
    res.append({
        "id": q["id"], "kind": q["kind"], "query": q["query"], "gold": q["gold"],
        "hash_rank": pos(rh, q["gold"]), "bge_rank": pos(rb, q["gold"]), "kw_rank": pos(rk, q["gold"]),
        "hash_top3": rh[:3], "bge_top3": rb[:3], "kw_top3": rk[:3],
    })

def mrr_hit(rows, key):
    m = {k: sum(1 for r in rows if r[key] == 1) / len(rows) for k in ("h1", "h5")}
    m["mrr"] = round(sum(1 / r[key] for r in rows if r[key]) / len(rows), 3)
    return m

out = {}
for kind in ("paraphrase", "control", "ALL"):
    rows = res if kind == "ALL" else [r for r in res if r["kind"] == kind]
    out[kind] = {
        "n": len(rows),
        "hash": mrr_hit(rows, "hash_rank"),
        "bge": mrr_hit(rows, "bge_rank"),
        "keyword": mrr_hit(rows, "kw_rank"),
    }

ts = time.strftime("%Y%m%d-%H%M%S")
p = ROOT / f"evals/retrieval_ab/results-{ts}.json"
p.write_text(json.dumps({"summary": out, "detail": res}, ensure_ascii=False, indent=1))
print("\n══ A/B 结果（语义通道纯余弦排序；kw=关键词子串基线）══")
for kind in ("paraphrase", "control", "ALL"):
    s = out[kind]
    print(f"\n[{kind}] n={s['n']}")
    for ch in ("hash", "bge", "keyword"):
        m = s[ch]
        print(f"  {ch:9s} hit@1={m['h1']:.2f} hit@5={m['h5']:.2f} MRR={m['mrr']}")
print(f"\n结果文件: {p}")
