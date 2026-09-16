import json, numpy as np, random
S = np.load('/tmp/calib_S.npy'); keys = np.load('/tmp/calib_keys.npy')
sem = json.load(open('/tmp/calib_sem.json'))
mem = {e['id']: e for e in json.load(open('data/memory/index.json'))}
random.seed(42)
idx = random.sample(range(len(sem)), 12)
out = []
for qi in idx:
    q = sem[qi]
    sims = S[qi]
    top = np.argsort(-sims)[:8]
    print(f'\n### Q: {q[:70]}')
    for r in top:
        k = str(keys[r]); mid = k.split(':',1)[1] if ':' in k else k
        e = mem.get(mid, {})
        c = (e.get('content','') or '')[:110].replace('\n',' ')
        print(f'  {sims[r]:.3f}  {c}')
