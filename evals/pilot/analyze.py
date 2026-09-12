import json, statistics
from collections import defaultdict

AGENT_ORDER = ["lfl", "da", "cline"]
rows = [json.loads(l) for l in open("data/results.jsonl") if l.strip()]

# dedupe: per (agent, task, run) keep latest ts
best = {}
for r in rows:
    key = (r["agent"], r["task"], r["run"])
    if key not in best or r.get("ts","") >= best[key].get("ts",""):
        best[key] = r
recs = list(best.values())

by_agent_task = defaultdict(list)
for r in recs:
    by_agent_task[(r["agent"], r["task"])].append(r)

TASK_ORDER = [f"t{i:02d}_{s}" for i,s in enumerate([
 "read_first_line","retry_transient","build_module","fix_bug","multi_file_sum","log_count",
 "json_flatten","resume_todo","big_file_line","fs_invariant","env_facts","interrupt_resume"],1)]
tasks = [t for t in TASK_ORDER if any(k[1]==t for k in by_agent_task)] + \
        sorted(t for t in {k[1] for k in by_agent_task} if t not in TASK_ORDER)
agents = [a for a in AGENT_ORDER if any(k[0]==a for k in by_agent_task)]

print("== Pass matrix (pass/runs) ==")
print("task".ljust(22) + "".join(a.ljust(10) for a in agents))
agg = {a: [0,0] for a in agents}
for t in tasks:
    line = t.ljust(22)
    for a in agents:
        rs = by_agent_task.get((a,t),[])
        p = sum(1 for r in rs if r.get("pass"))
        line += f"{p}/{len(rs)}".ljust(10)
        agg[a][0]+=p; agg[a][1]+=len(rs)
    print(line)
print()
print("== Aggregate ==")
for a in agents:
    p,n = agg[a]
    print(f"{a}: {p}/{n} = {p/n*100:.1f}%" if n else f"{a}: 0/0")
print()
print("== Duration (s) by agent: median / mean / p90 ==")
for a in agents:
    ds = sorted(r.get("dur", r.get("resume_dur")) for r in recs if r["agent"]==a)
    if ds:
        med = statistics.median(ds); mean = statistics.mean(ds)
        p90 = ds[max(int(len(ds)*0.9)-1,0)]
        print(f"{a}: {med:.0f} / {mean:.0f} / {p90:.0f}  (n={len(ds)})")
print()
print("== Failed runs detail ==")
for a in agents:
    fails = [r for r in recs if r["agent"]==a and not r.get("pass")]
    if not fails:
        print(f"{a}: none")
    for r in fails:
        note = (r.get("verify_err") or ("harness_err" if not r.get("ok_run") else ""))[:100]
        print(f"{a} {r['task']} run{r['run']}: {note}")
