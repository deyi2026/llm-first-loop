#!/usr/bin/env python3
"""hash vs bge 检索质量 A/B（embedding_stage2）.

设计: 同一语料(1488 条 memory)+同一标注集(40 条), 只换 embedder。
- hash: src HashEmbedder(128) 字符 n-gram（当前生产 EMBEDDING_PROVIDER=hash）
- bge : bge-small-zh-v1.5 @ http://127.0.0.1:8765（候选向量复用
        data/memory/embeddings.json, 版本校验含 api-v1）
通道: 纯余弦排名（隔离 embedder 差异; 关键词/实体通道与 embedder 无关,
      两臂输入相同, 差值全部来自语义通道）。阈值用各自校准值: hash 0.22 / bge 0.50。
指标: A/B 类 Recall@5, MRR@10; C 类 top1 分数与过阈值返回数。
另: 词面重叠控制变量 = hash_cos(query, target)，改写类(A)必须低才构成语义测试。
"""
import json, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from llm_loop.memory.embedder import HashEmbedder

EPOCH = "2026-09-16"
EMB_URL = "http://127.0.0.1:8765/v1/embeddings"

# ── 语料（复刻 SemanticRetriever._candidates 的 content 构造）──
idx = json.load(open(ROOT / "data/memory/index.json"))
corpus_key, corpus_text = [], []
for e in idx:
    corpus_key.append(f"memory:{e['id']}")
    corpus_text.append(f"{e['content']} {' '.join(e.get('keywords', []) or [])}")
print(f"corpus: {len(corpus_key)} entries")

# ── bge 候选矩阵（复用缓存, 缺失现场补）──
cachef = Path(__file__).parent / "bge_cache.json"
if not cachef.exists():
    cachef.write_text(json.dumps({"v": "api-v1-bge", "data": {}}))
raw = json.load(open(cachef))
assert "api-v1" in str(raw.get("v", "")), f"cache version mismatch: {raw.get('v')}"
bge_cache = raw["data"]

def bge_embed(texts, bs=64):
    out = []
    for i in range(0, len(texts), bs):
        chunk = texts[i:i+bs]
        req = urllib.request.Request(EMB_URL,
            data=json.dumps({"model": "bge", "input": chunk}).encode(),
            headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=300).read())
        out.extend([d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])])
    return out

missing = [k for k in corpus_key if k not in bge_cache]
if missing:
    print(f"embedding {len(missing)} missing candidates...")
    for k, v in zip(missing, bge_embed([corpus_text[corpus_key.index(k)] for k in missing])):
        bge_cache[k] = v
M_bge = np.array([bge_cache[k] for k in corpus_key], dtype=np.float32)
M_bge /= (np.linalg.norm(M_bge, axis=1, keepdims=True) + 1e-9)

# ── hash 矩阵（现场算, 确定性）──
he = HashEmbedder(128)
M_hash = np.array([he.embed(t) for t in corpus_text], dtype=np.float32)
M_hash /= (np.linalg.norm(M_hash, axis=1, keepdims=True) + 1e-9)
assert M_hash.shape[1] == 128 and not np.isnan(M_hash).any()

# ── 查询向量 ──
labels = json.load(open(Path(__file__).parent / "ab_labels.json"))["labels"]
queries = [l["query"] for l in labels]
Q_bge = np.array(bge_embed(queries), dtype=np.float32)
Q_bge /= (np.linalg.norm(Q_bge, axis=1, keepdims=True) + 1e-9)
Q_hash = np.array([he.embed(q) for q in queries], dtype=np.float32)
Q_hash /= (np.linalg.norm(Q_hash, axis=1, keepdims=True) + 1e-9)

# ── 近重复 alternates: content 3-gram Jaccard > 0.6 视为同靶 ──
def grams3(t):
    s = set()
    for n in (2, 3):
        s |= {t[i:i+n] for i in range(max(1, len(t)-n+1))}
    return s
gcorp = [grams3(t[:400]) for t in corpus_text]
key2i = {k: i for i, k in enumerate(corpus_key)}

def alternates(target):
    ti = key2i[target]; gt = gcorp[ti]; out = [target]
    for j, gj in enumerate(gcorp):
        if j == ti: continue
        inter = len(gt & gj)
        if inter and inter / len(gt | gj) > 0.6:
            out.append(corpus_key[j])
    return out

for l in labels:
    if "target" in l:
        l["accept"] = alternates(l["target"])

# ── 排名与指标 ──
THR = {"hash": 0.22, "bge": 0.50}
detail = []
agg = {}
for arm, Q, M in (("hash", Q_hash, M_hash), ("bge", Q_bge, M_bge)):
    S = Q @ M.T
    for qi, l in enumerate(labels):
        row = dict(l)
        scores = S[qi]
        order = np.argsort(-scores)
        top5 = [(corpus_key[i], float(scores[i])) for i in order[:5]]
        row["top5"] = [(k, round(s, 4)) for k, s in top5]
        row["top1"] = top5[0]
        cls = l["class"]
        if cls in ("A", "B"):
            acc = set(l["accept"])
            ranks = [r + 1 for r, k in enumerate([corpus_key[i] for i in order]) if k in acc]
            row["rank"] = ranks[0] if ranks else None
            row["hash_lexical_cos_q_target"] = round(float(
                (Q_hash[qi] @ M_hash[key2i[l["target"]]])), 4)
            row["bge_cos_q_target"] = round(float(
                (Q_bge[qi] @ M_bge[key2i[l["target"]]])), 4)
        else:
            row["returned_above_thr"] = int((scores >= THR[arm]).sum())
        detail.append({"arm": arm, **row})

    m = {}
    for cls in ("A", "B"):
        rows = [r for r in detail if r["arm"] == arm and r["class"] == cls]
        m[cls] = {
            "n": len(rows),
            "recall@5": sum(1 for r in rows if r.get("rank") and r["rank"] <= 5) / len(rows),
            "mrr@10": sum(1 / r["rank"] for r in rows if r.get("rank") and r["rank"] <= 10) / len(rows),
            "miss_ranks": [r.get("rank") for r in rows if not r.get("rank") or r["rank"] > 5],
        }
    crows = [r for r in detail if r["arm"] == arm and r["class"] == "C"]
    m["C"] = {
        "n": len(crows),
        "top1_mean": float(np.mean([r["top1"][1] for r in crows])),
        "top1_max": max(r["top1"][1] for r in crows),
        "returned_gt0_pct": sum(1 for r in crows if r["returned_above_thr"] > 0) / len(crows),
        "returned_mean": float(np.mean([r["returned_above_thr"] for r in crows])),
    }
    agg[arm] = m

out = {"epoch": EPOCH, "corpus": len(corpus_key), "labels": len(labels),
       "thresholds": THR, "agg": agg, "detail": detail}
Path(Path(__file__).parent / "ab_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"\n{'':16} {'hash (现状)':>14} {'bge (真语义)':>14}")
for cls in ("A", "B"):
    for met in ("recall@5", "mrr@10"):
        print(f"{cls}类 {met:10} {agg['hash'][cls][met]:>14.2%} {agg['bge'][cls][met]:>14.2%}")
print(f"C类 top1_mean   {agg['hash']['C']['top1_mean']:>14.4f} {agg['bge']['C']['top1_mean']:>14.4f}")
print(f"C类 returned%   {agg['hash']['C']['returned_gt0_pct']:>14.0%} {agg['bge']['C']['returned_gt0_pct']:>14.0%}")
la = [r for r in detail if r["arm"] == "hash" and r["class"] == "A"]
print(f"\nA类词面控制变量 hash_cos(q,target): min={min(r['hash_lexical_cos_q_target'] for r in la):.3f} "
      f"mean={float(np.mean([r['hash_lexical_cos_q_target'] for r in la])):.3f} "
      f"max={max(r['hash_lexical_cos_q_target'] for r in la):.3f} (低=改写有效, hash 视角目标≈随机文档)")
