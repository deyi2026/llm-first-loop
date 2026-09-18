"""A/B 对照 v2: HashEmbedder(字符n-gram哈希) vs bge-small-zh-v1.5(真语义)。
方法修正:
1. gold 先验证确实存在于语料(不在则剔除该测试)
2. 语料同时含 memory.content + archive.summary/content(截断800字)
3. 语义模型批量编码(一次前向), 查询加 bge 官方检索前缀
"""
import sys, json, glob, time
sys.path.insert(0, "src")
from llm_loop.memory.embedder import HashEmbedder, cosine_similarity

TESTS = [
    ("怎么把那个 8901 的模型服务重新启动起来，让它重新加载配置",
     "qwen8901_switch.sh", "重启8901服务", "literal"),
    ("之前讨论过的那个能提升推理深度的模型堆栈配置，winner 是哪套",
     "1.807902", "winner stack", "semantic"),
    ("怎么判断一个任务是不是在原地打转、没有推进",
     "stagnation 0.52", "停滞评估", "semantic"),
    ("调用外部工具失败后应该如实说明还是假装成功",
     "嵌入失败如实返回 None", "诚实降级", "semantic"),
    ("怎么把一个操作经验固化成以后能直接复用的步骤",
     "record_skill", "技能固化", "semantic"),
    ("跨会话接管任务时，怎么让下一个会话知道前情",
     "handoff_now", "跨会话交接", "semantic"),
    ("怎么把架构改进建议提交给人工审阅",
     "submit_evolution", "架构演进建议", "semantic"),
    ("检索历史经验时，怎么判断它现在还能不能用",
     "task applicability", "经验适用性", "semantic"),
    ("怎么给一个本地运行的中文文本模型做评估",
     "bench_method_curriculum", "中文模型评估", "semantic"),
]

def load_corpus(max_docs=100000):
    docs, seen = [], set()
    mem = json.load(open("data/memory/index.json"))
    for e in mem:
        t = (e.get("content","") or "").strip()
        if len(t) > 60:
            docs.append({"src":"mem","text":t[:800]}); seen.add(t[:200])
    print(f"  memory docs: {len(docs)}", flush=True)
    for f in sorted(glob.glob("data/archives/*.jsonl")):
        try:
            with open(f) as fh:
                for line in fh:
                    try: d = json.loads(line)
                    except: continue
                    for field in ("summary","content"):
                        t = (d.get(field,"") or "").strip()
                        if len(t) > 80:
                            k = t[:200]
                            if k not in seen:
                                seen.add(k); docs.append({"src":f"arc:{field}","text":t[:800]})
                    if len(docs) >= max_docs: break
        except Exception: pass
        if len(docs) >= max_docs: break
    return docs

def main():
    print("加载真实语料...", flush=True)
    docs = load_corpus()
    print(f"语料总规模: {len(docs)} 条", flush=True)
    # 验证 gold 在语料内
    valid = []
    for q, gold, note, kind in TESTS:
        idx = [i for i,d in enumerate(docs) if gold in d["text"]]
        if idx:
            valid.append({"q":q,"gold":gold,"note":note,"kind":kind,"gold_idx":idx})
            print(f"  [ok] {note}: gold 在 {len(idx)} 条文档中", flush=True)
        else:
            print(f"  [DROP] {note}: gold 不在语料, 剔除", flush=True)
    print(f"有效测试: {len(valid)}/{len(TESTS)}", flush=True)

    # hash 批量
    t0=time.time()
    he = HashEmbedder(dim=128)
    hash_vecs = [he.embed(d["text"]) for d in docs]
    print(f"hash 编码完成 ({time.time()-t0:.1f}s)", flush=True)
    # semantic 批量
    t0=time.time()
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    sem_vecs = m.encode([d["text"] for d in docs], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    print(f"语义编码完成 ({time.time()-t0:.1f}s)", flush=True)

    results = {"hash": [], "bge": []}
    for v in valid:
        qh = he.embed(v["q"])
        qb = m.encode("为这个句子生成表示以用于检索相关文章：" + v["q"], normalize_embeddings=True)
        for name, qv, mat in (("hash", qh, hash_vecs), ("bge", qb, sem_vecs)):
            qlist = qv.tolist() if hasattr(qv,"tolist") else qv
            scores = []
            for i, dv in enumerate(mat):
                dl = dv.tolist() if hasattr(dv,"tolist") else dv
                if dl is None: continue
                s = cosine_similarity(qlist, dl)
                scores.append((s, i))
            scores.sort(reverse=True)
            rank = next((r+1 for r,(s,i) in enumerate(scores) if i in v["gold_idx"]), None)
            results[name].append({"note": v["note"], "kind": v["kind"], "rank": rank})
    for name in ("hash","bge"):
        rs = results[name]
        top1 = sum(1 for r in rs if r["rank"]==1)
        top5 = sum(1 for r in rs if r["rank"] and r["rank"]<=5)
        top20 = sum(1 for r in rs if r["rank"] and r["rank"]<=20)
        miss = sum(1 for r in rs if r["rank"] is None)
        print(f"\n=== {name} === Top1:{top1}/{len(rs)}  Top5:{top5}/{len(rs)}  Top20:{top20}/{len(rs)}  Miss:{miss}", flush=True)
        for r in rs:
            print(f"  {'OK' if r['rank'] else 'XX'} {('#'+str(r['rank'])) if r['rank'] else 'miss':>6}  [{r['kind']}] {r['note']}", flush=True)

if __name__ == "__main__":
    main()
