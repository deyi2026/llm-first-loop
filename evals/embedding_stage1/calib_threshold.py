import json, re, urllib.request
import numpy as np

qs = json.load(open('/tmp/calib_queries.json'))
# 语义型查询过滤：排除 ref/精确引用式查询
def is_semantic(q):
    if re.match(r'^(evidence:|episode:|method:|experience:|attachment:|artifact:)', q): return False
    cjk = len(re.findall(r'[\u4e00-\u9fff]', q))
    words = len(re.findall(r'[A-Za-z]{2,}', q))
    return cjk >= 3 or words >= 2
sem = [q for q in qs if is_semantic(q)]
print(f'total {len(qs)} → semantic-type {len(sem)}')

# 候选向量矩阵
emb = json.load(open('data/memory/embeddings.json'))
data = emb['data']; keys = list(data.keys())
M = np.array([data[k] for k in keys], dtype=np.float32)
M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
print('candidates:', M.shape)

# batch embed via local service
def batch_embed(texts, bs=64):
    out = []
    for i in range(0, len(texts), bs):
        chunk = texts[i:i+bs]
        req = urllib.request.Request('http://127.0.0.1:8765/v1/embeddings',
            data=json.dumps({'model':'bge','input':chunk}).encode(),
            headers={'Content-Type':'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        out.extend([d['embedding'] for d in sorted(r['data'], key=lambda d: d['index'])])
    return out

Q = np.array(batch_embed(sem), dtype=np.float32)
Q /= (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9)
S = Q @ M.T   # [nq, ncand] 余弦
np.save('/tmp/calib_S.npy', S)
np.save('/tmp/calib_keys.npy', np.array(keys))
json.dump(sem, open('/tmp/calib_sem.json','w'), ensure_ascii=False)

# 分布统计
flat = S.flatten()
qs_max = S.max(axis=1); qs_p5 = np.partition(S, -5, axis=1)[:, -5]
qs_p20 = np.sort(S, axis=1)[:, -20]
print(f'\n== 全 pair 相似度分布 (n={flat.size}) ==')
for p in (10,25,50,75,90,95,99): print(f'  P{p}: {np.percentile(flat,p):.4f}')
print(f'  0.22 之下占比: {(flat<0.22).mean()*100:.2f}%  |  0.30 之下: {(flat<0.30).mean()*100:.2f}%  |  0.40 之下: {(flat<0.40).mean()*100:.2f}%')
print(f'\n== 每查询 top 相似度 ==')
for name, arr in (('top1',qs_max),('top5min',qs_p5),('top20min',qs_p20)):
    print(f'  {name}: min={arr.min():.4f} P10={np.percentile(arr,10):.4f} P50={np.percentile(arr,50):.4f} P90={np.percentile(arr,90):.4f} max={arr.max():.4f}')
print(f'\n  top1 < 0.22 的查询数: {(qs_max<0.22).sum()}/{len(sem)}')
print(f'  top1 < 0.30 的查询数: {(qs_max<0.30).sum()}/{len(sem)}')
print(f'  top1 < 0.40 的查询数: {(qs_max<0.40).sum()}/{len(sem)}')
