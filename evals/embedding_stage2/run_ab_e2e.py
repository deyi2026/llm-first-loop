#!/usr/bin/env python3
"""端到端 A/B: 同一 SemanticRetriever(RRF: 语义+关键词+实体), 只换 embedder.

复刻真实链路 introspection/search.py::_search_memory:
  keyword seed = MemoryStore.search(query.split(), top_k=5)  (子串计数+衰减排序)
  → SemanticRetriever.search(query, scope='memory', keyword_results=seed)
向量缓存预填两臂(内存, 不落盘), 语义通道差异=向量本身。
"""
import json, sys, re
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from llm_loop.memory.embedder import HashEmbedder, APIEmbedder
from llm_loop.memory.retriever import SemanticRetriever

HALF_LIFE = 30.0

@dataclass
class Entry:
    id: str; type: str; content: str; keywords: list
    scope: str = "global"; source_session_id: str = ""
    access_count: int = 0; last_access_at: str | None = None
    created_at: str = ""; updated_at: str = ""; decay_score: float = 1.0

def decay(e):
    if not e.last_access_at:
        return 1.0
    try:
        days = (datetime.now(UTC) - datetime.fromisoformat(e.last_access_at)).total_seconds()/86400
        return round(1.0 * 0.5 ** max(0.0, days/HALF_LIFE), 4)
    except Exception:
        return 1.0

class StubStore:
    def __init__(self, entries): self._e = entries
    def all(self): return self._e
    def search(self, keywords, top_k=5, session_id=""):
        scored = []
        for e in self._e:
            if e.scope == "session" and not session_id: continue
            hay = " ".join([e.content, *e.keywords]).lower()
            s = sum(1 for k in keywords if k.lower() in hay)
            if s > 0:
                e.decay_score = decay(e)
                scored.append((s, e))
        scored.sort(key=lambda x: (x[0], x[1].decay_score, x[1].updated_at or x[1].created_at), reverse=True)
        return [e for _, e in scored[:top_k]]

idx = json.load(open(ROOT / "data/memory/index.json"))
entries = [Entry(**{k: e.get(k, Entry.__dataclass_fields__[k].default if k in Entry.__dataclass_fields__ else None)
                    for k in Entry.__dataclass_fields__}) for e in idx]
store = StubStore(entries)
keymap = {f"memory:{e.id}": e for e in entries}

def kw_record(e):
    return {"kind": "memory", "ts": e.created_at, "id": e.id,
            "summary": e.content[:120], "file": "memory/index.json", "key": f"memory:{e.id}"}

def build(arm):
    emb = (HashEmbedder(128) if arm == "hash"
           else APIEmbedder(api_key="", base_url="http://127.0.0.1:8765/v1", model="bge", timeout_s=300))
    r = SemanticRetriever(emb, timeout_s=120, semantic_top_k=20,
                          threshold=0.22 if arm == "hash" else 0.50,
                          memory_dir=None, archive_dir=None)
    if arm == "hash":
        for e in entries:
            r._mem_emb_cache[f"memory:{e.id}"] = emb.embed(f"{e.content} {' '.join(e.keywords)}")
    else:
        raw = json.load(open(ROOT / "data/memory/embeddings.json"))
        assert "api-v1" in str(raw.get("v", ""))
        r._mem_emb_cache.update({k: v for k, v in raw["data"].items() if k in keymap})
    return r

labels = json.load(open(Path(__file__).parent / "ab_labels.json"))["labels"]
out = {}
for arm in ("hash", "bge"):
    r = build(arm)
    rows = []
    for l in labels:
        seed = store.search(l["query"].split(), top_k=5)
        res = r.search(l["query"], top_k=5, scope="memory",
                       memory=store, keyword_results=[kw_record(e) for e in seed])
        hit_ids = [h.get("key") or h.get("id") for h in res.entries]
        rows.append({"class": l["class"], "q": l["query"],
                     "target": l.get("target"), "modes": res.mode,
                     "kw_seed_hits": len(seed), "top5_keys": hit_ids[:5]})
    out[arm] = rows

# 近重复 alternates 同 run_ab.py
def grams(t):
    s = set()
    for n in (2, 3): s |= {t[i:i+n] for i in range(max(1, len(t)-n+1))}
    return s
gc = [grams(f"{e.content} {' '.join(e.keywords)}"[:400]) for e in entries]
def acc_set(t):
    ti = next(i for i, e in enumerate(entries) if f"memory:{e.id}" == t)
    gt = gc[ti]; out_ = {t}
    for j, gj in enumerate(gc):
        if j != ti and len(gt & gj) and len(gt & gj)/len(gt | gj) > 0.6:
            out_.add(f"memory:{entries[j].id}")
    return out_

summary = {}
for arm, rows in out.items():
    m = {}
    for cls in ("A", "B"):
        rs = [r for r in rows if r["class"] == cls]
        hits = 0
        for r in rs:
            acc = acc_set(r["target"])
            r["hit"] = any(k in acc for k in r["top5_keys"])
            hits += r["hit"]
        m[cls] = {"n": len(rs), "recall@5": hits/len(rs)}
    m["kw_only_A"] = sum(1 for r in rows if r["class"]=="A" and r["kw_seed_hits"]>0)
    summary[arm] = m
    modes = {}
    for r in rows: modes[r["modes"]] = modes.get(r["modes"], 0) + 1
    m["modes"] = modes

Path(Path(__file__).parent / "ab_e2e_results.json").write_text(
    json.dumps({"summary": summary, "detail": out}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{'':22} {'hash(现状)':>12} {'bge(真语义)':>12}")
for cls in ("A", "B"):
    print(f"{cls}类 端到端 recall@5  {summary['hash'][cls]['recall@5']:>11.0%} {summary['bge'][cls]['recall@5']:>12.0%}")
print(f"A类 关键词通道有seed的查询数 {summary['hash']['kw_only_A']}/20 (两臂相同, embedder 无关)")
print("modes:", summary["hash"]["modes"], summary["bge"]["modes"])
